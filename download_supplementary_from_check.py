#!/usr/bin/env python3
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

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

EXCLUDE_KEYWORDS = [
    "graphical abstract",
]

FILE_EXTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".zip",
    ".rar",
    ".txt",
    ".ppt",
    ".pptx",
    ".tsv",
    ".jpg",
    ".jpeg",
    ".png",
}

URL_HINTS = [
    "supp",
    "suppl",
    "supplement",
    "supporting",
    "esm",
    "moesm",
    "mediaobjects",
    "additional",
    "dataset",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download supplementary files from a DOI supplementary-check workbook."
    )
    parser.add_argument("--input-xlsx", required=True, help="Output from check_supplementary_by_doi.py")
    parser.add_argument("--out-dir", required=True, help="Directory for downloaded supplementary files.")
    parser.add_argument("--sleep-sec", type=float, default=0.3, help="Sleep between requests.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout.")
    parser.add_argument("--limit", type=int, default=0, help="Download only first N rows with supplementary.")
    parser.add_argument(
        "--max-files-per-paper",
        type=int,
        default=6,
        help="Maximum number of supplementary files to download per paper.",
    )
    return parser.parse_args()


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


def clean_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", str(name or "").strip())
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] if len(name) > 180 else name


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def candidate_score(label: str, href: str) -> int:
    combo = f"{label} {href}".lower()
    if any(x in combo for x in EXCLUDE_KEYWORDS):
        return -999
    score = 0
    for kw in KEYWORDS:
        if kw in combo:
            score += 5
    for hint in URL_HINTS:
        if hint in combo:
            score += 2
    parsed = urlparse(href)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in FILE_EXTS:
        score += 8
    if "download" in combo:
        score += 2
    return score


def guess_ext(url: str, content_type: str = "") -> str:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext in FILE_EXTS:
        return ext
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return ".pdf"
    if "word" in ct or "officedocument.wordprocessingml" in ct:
        return ".docx"
    if "excel" in ct or "spreadsheetml" in ct:
        return ".xlsx"
    if "zip" in ct:
        return ".zip"
    if "csv" in ct:
        return ".csv"
    if "plain" in ct:
        return ".txt"
    if "jpeg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    return ".bin"


def extract_links_from_page(session: requests.Session, url: str, timeout: int) -> Tuple[List[Dict[str, str]], str, str]:
    resp = session.get(url, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text or "", "html.parser")

    found: List[Dict[str, str]] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        label = collapse_ws(a.get_text(" ", strip=True))
        full = urljoin(resp.url, href)
        score = candidate_score(label, full)
        if score <= 0:
            continue
        key = (label, full)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            {
                "label": label,
                "url": full,
                "score": score,
            }
        )

    found.sort(key=lambda x: (-x["score"], x["url"]))
    return found, resp.url, resp.headers.get("content-type", "")


def try_download(session: requests.Session, url: str, dst: Path, timeout: int) -> Tuple[bool, str, str]:
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        resp.raise_for_status()
    except Exception as exc:
        return False, "", f"request_failed: {exc}"

    final_url = resp.url
    content_type = resp.headers.get("content-type", "")
    ext = guess_ext(final_url, content_type)
    real_dst = dst.with_suffix(ext if dst.suffix == "" else dst.suffix)

    # Skip likely HTML landing pages masquerading as candidates.
    if "html" in content_type.lower() and ext == ".bin":
        return False, final_url, "html_page_not_file"

    with open(real_dst, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)
    return True, final_url, ""


def main() -> int:
    args = parse_args()
    input_xlsx = Path(args.input_xlsx).expanduser()
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_xlsx.exists():
        print(f"[ERROR] Input workbook not found: {input_xlsx}", file=sys.stderr)
        return 2

    df = pd.read_excel(input_xlsx)
    if "has_supplementary" not in df.columns:
        print("[ERROR] Missing has_supplementary column.", file=sys.stderr)
        return 2

    df = df[df["has_supplementary"] == True].copy()
    if args.limit > 0:
        df = df.head(args.limit).copy()

    if df.empty:
        print("[ERROR] No rows marked has_supplementary=true.", file=sys.stderr)
        return 1

    session = make_session()
    manifest: List[Dict[str, str]] = []

    for idx, row in df.iterrows():
        title = clean_name(row.get("title_or_filename", "paper"))
        page_url = str(row.get("final_url") or row.get("request_url") or "").strip()
        doi = str(row.get("doi") or "").strip()
        paper_dir = out_dir / title
        paper_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{len(manifest)+1}] PAGE {page_url}")
        try:
            links, resolved_url, _ = extract_links_from_page(session, page_url, timeout=args.timeout)
        except Exception as exc:
            manifest.append(
                {
                    "title_or_filename": title,
                    "doi": doi,
                    "page_url": page_url,
                    "candidate_label": "",
                    "candidate_url": "",
                    "saved_path": "",
                    "status": "page_failed",
                    "note": str(exc),
                }
            )
            time.sleep(args.sleep_sec)
            continue

        if not links:
            manifest.append(
                {
                    "title_or_filename": title,
                    "doi": doi,
                    "page_url": resolved_url,
                    "candidate_label": "",
                    "candidate_url": "",
                    "saved_path": "",
                    "status": "no_candidate_link",
                    "note": "",
                }
            )
            time.sleep(args.sleep_sec)
            continue

        downloaded = 0
        seen_urls = set()
        for j, item in enumerate(links, start=1):
            if downloaded >= args.max_files_per_paper:
                break
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            dst = paper_dir / f"supplement_{j}"
            ok, final_url, note = try_download(session, item["url"], dst, timeout=args.timeout)
            manifest.append(
                {
                    "title_or_filename": title,
                    "doi": doi,
                    "page_url": resolved_url,
                    "candidate_label": item["label"],
                    "candidate_url": item["url"],
                    "saved_path": str(next(paper_dir.glob(f'supplement_{j}*'), Path(''))),
                    "status": "downloaded" if ok else "candidate_failed",
                    "note": note or final_url,
                }
            )
            if ok:
                downloaded += 1
            time.sleep(args.sleep_sec)

    mani_df = pd.DataFrame(manifest)
    mani_json = out_dir / "download_manifest.json"
    mani_csv = out_dir / "download_manifest.csv"
    mani_df.to_csv(mani_csv, index=False, encoding="utf-8-sig")
    mani_json.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    n_ok = int((mani_df["status"] == "downloaded").sum()) if not mani_df.empty else 0
    print("=== Download Summary ===")
    print(f"Papers checked: {len(df)}")
    print(f"Downloaded files: {n_ok}")
    print(f"Manifest CSV: {mani_csv}")
    print(f"Manifest JSON: {mani_json}")
    print(f"Output dir: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
