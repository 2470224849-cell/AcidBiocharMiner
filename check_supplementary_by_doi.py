#!/usr/bin/env python3
import argparse
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


KEYWORDS = [
    "supplementary information",
    "supporting information",
    "supplementary material",
    "supplementary materials",
    "electronic supplementary material",
    "appendix",
    "additional file",
    "dataset",
]

TITLE_CANDIDATES = [
    "filename",
    "article title",
    "title",
    "paper_title",
]

DOI_CANDIDATES = [
    "doi",
    "DOI",
]

LINK_CANDIDATES = [
    "doi link",
    "DOI Link",
    "url",
    "link",
]

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read DOI values from an Excel workbook, visit publisher pages, and "
            "check whether supplementary-information keywords are present."
        )
    )
    parser.add_argument("--input-xlsx", required=True, help="Input Excel workbook.")
    parser.add_argument(
        "--out-xlsx",
        default="output/supplementary_check.xlsx",
        help="Output Excel path.",
    )
    parser.add_argument(
        "--out-csv",
        default="output/supplementary_check.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.8,
        help="Sleep between requests to reduce publisher blocking.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only check the first N unique DOI rows (0 = all).",
    )
    parser.add_argument(
        "--sheet",
        default="",
        help="Optional sheet name to restrict scanning to one sheet.",
    )
    return parser.parse_args()


def normalize_col(col: str) -> str:
    return re.sub(r"\s+", " ", str(col or "").strip()).lower()


def clean_doi(value: object) -> str:
    s = str(value or "").strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    m = DOI_RE.search(s)
    if not m:
        return ""
    return m.group(0).rstrip('.,;)]}"\'')


def find_first_col(columns: Iterable[str], candidates: List[str]) -> Optional[str]:
    norm_map = {normalize_col(c): c for c in columns}
    for cand in candidates:
        if normalize_col(cand) in norm_map:
            return norm_map[normalize_col(cand)]
    return None


def load_rows(xlsx_path: Path, only_sheet: str = "") -> pd.DataFrame:
    xl = pd.ExcelFile(xlsx_path)
    sheet_names = [only_sheet] if only_sheet else xl.sheet_names
    rows: List[Dict[str, str]] = []

    for sheet in sheet_names:
        df = pd.read_excel(xlsx_path, sheet_name=sheet)
        if df.empty:
            continue

        doi_col = find_first_col(df.columns, DOI_CANDIDATES)
        link_col = find_first_col(df.columns, LINK_CANDIDATES)
        title_col = find_first_col(df.columns, TITLE_CANDIDATES)

        if not doi_col and not link_col:
            continue

        for i, row in df.iterrows():
            doi = clean_doi(row.get(doi_col, "")) if doi_col else ""
            doi_link = str(row.get(link_col, "") or "").strip() if link_col else ""
            title = str(row.get(title_col, "") or "").strip() if title_col else ""
            if not doi and not doi_link:
                continue
            rows.append(
                {
                    "sheet": sheet,
                    "row_index_1based": int(i) + 2,
                    "title_or_filename": title,
                    "doi": doi,
                    "doi_link": doi_link,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["dedup_key"] = out["doi"].where(out["doi"].astype(bool), out["doi_link"])
    out = out.drop_duplicates(subset=["dedup_key"]).drop(columns=["dedup_key"])
    return out.reset_index(drop=True)


def make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return sess


def pick_url(row: pd.Series) -> str:
    doi = str(row.get("doi", "") or "").strip()
    doi_link = str(row.get("doi_link", "") or "").strip()
    if doi_link.startswith("http://") or doi_link.startswith("https://"):
        return doi_link
    if doi:
        return f"https://doi.org/{doi}"
    return doi_link


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def find_keyword_hits(text: str) -> List[str]:
    text_l = text.lower()
    hits = [kw for kw in KEYWORDS if kw in text_l]
    return sorted(set(hits))


def extract_candidate_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    links: List[str] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        label = collapse_ws(a.get_text(" ", strip=True))
        combo = f"{label} {href}".lower()
        if "graphical abstract" in combo:
            continue
        if any(kw in combo for kw in KEYWORDS):
            full = urljoin(base_url, href) if href else ""
            val = f"{label} -> {full}".strip(" ->")
            if val and val not in seen:
                seen.add(val)
                links.append(val)
    return links


def check_one(session: requests.Session, url: str, timeout: int) -> Dict[str, str]:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        return {
            "request_ok": "false",
            "final_url": "",
            "has_supplementary": "false",
            "matched_keywords": "",
            "candidate_links": "",
            "status_code": "",
            "note": f"request_failed: {exc}",
        }

    html = resp.text or ""
    soup = BeautifulSoup(html, "html.parser")

    page_text = collapse_ws(soup.get_text(" ", strip=True))
    raw_hits = find_keyword_hits(html)
    text_hits = find_keyword_hits(page_text)
    link_hits = extract_candidate_links(soup, resp.url)

    all_hits = sorted(set(raw_hits + text_hits))
    has_supp = bool(all_hits or link_hits)

    return {
        "request_ok": "true",
        "final_url": resp.url,
        "has_supplementary": "true" if has_supp else "false",
        "matched_keywords": "; ".join(all_hits),
        "candidate_links": " || ".join(link_hits[:12]),
        "status_code": str(resp.status_code),
        "note": "",
    }


def main() -> int:
    args = parse_args()
    input_xlsx = Path(args.input_xlsx).expanduser()
    out_xlsx = Path(args.out_xlsx).expanduser()
    out_csv = Path(args.out_csv).expanduser()

    if not input_xlsx.exists():
        print(f"[ERROR] Input Excel not found: {input_xlsx}", file=sys.stderr)
        return 2

    rows = load_rows(input_xlsx, only_sheet=args.sheet)
    if rows.empty:
        print("[ERROR] No DOI/DOI Link rows found in workbook.", file=sys.stderr)
        return 1

    if args.limit > 0:
        rows = rows.head(args.limit).copy()

    session = make_session()
    out_rows: List[Dict[str, str]] = []

    for idx, row in rows.iterrows():
        url = pick_url(row)
        print(f"[{idx + 1}/{len(rows)}] CHECK {url}")
        result = check_one(session, url, timeout=args.timeout)
        out_rows.append(
            {
                "sheet": row["sheet"],
                "row_index_1based": row["row_index_1based"],
                "title_or_filename": row["title_or_filename"],
                "doi": row["doi"],
                "doi_link": row["doi_link"],
                "request_url": url,
                **result,
            }
        )
        time.sleep(args.sleep_sec)

    out_df = pd.DataFrame(out_rows)
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_excel(out_xlsx, index=False)
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    n_yes = int((out_df["has_supplementary"] == "true").sum())
    n_ok = int((out_df["request_ok"] == "true").sum())
    print("=== Summary ===")
    print(f"Input rows checked: {len(out_df)}")
    print(f"Request OK: {n_ok}")
    print(f"Supplementary keyword hit: {n_yes}")
    print(f"Saved XLSX: {out_xlsx}")
    print(f"Saved CSV: {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
