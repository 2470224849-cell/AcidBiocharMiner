#!/usr/bin/env python3
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill sheet1 from method text in reader json files.")
    p.add_argument("--xlsx", required=True, help="Input Excel path.")
    p.add_argument("--reader-root", required=True, help="Reader/output root.")
    p.add_argument("--sample-filter", default="acid_pristine", help="Reserved arg for compatibility.")
    p.add_argument("--out-xlsx", required=True, help="Output Excel path.")
    p.add_argument("--log", required=True, help="Detail log path.")
    p.add_argument("--allow-global", action="store_true", help="Allow global fill for acid fields.")
    return p.parse_args()


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip() == ""


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _norm_filename(s: str) -> str:
    return _norm_text(Path(str(s or "")).name)


def _pick_mode(values: List[str], min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[str]:
    if not values:
        return None
    clean = []
    for v in values:
        try:
            x = float(v)
        except Exception:
            continue
        if min_val is not None and x < min_val:
            continue
        if max_val is not None and x > max_val:
            continue
        clean.append(f"{x:g}")
    if not clean:
        return None
    cnt = Counter(clean)
    top = cnt.most_common(2)
    if len(top) == 1 or top[0][1] > top[1][1]:
        return top[0][0]
    if len(cnt) == 1:
        return next(iter(cnt.keys()))
    return None


def _load_reader_text(reader_json: Path) -> str:
    try:
        obj = json.loads(reader_json.read_text(encoding="utf-8"))
    except Exception:
        return ""
    chunks: List[str] = []
    for key in ("elements", "cln_elements"):
        els = obj.get(key)
        if not isinstance(els, list):
            continue
        for e in els:
            if not isinstance(e, dict):
                continue
            t = e.get("clean_text") or e.get("content") or ""
            if isinstance(t, str) and t.strip():
                chunks.append(t)
    return "\n".join(chunks)


def _load_raw_filenames(raw_json: Path) -> List[str]:
    try:
        obj = json.loads(raw_json.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: List[str] = []
    if not isinstance(obj, list):
        return out
    for item in obj:
        if not isinstance(item, dict):
            continue
        row = item.get("row")
        if not isinstance(row, dict):
            continue
        fn = row.get("filename")
        if isinstance(fn, str) and fn.strip():
            out.append(fn.strip())
    return out


def collect_text_by_filename(reader_root: Path) -> Dict[str, str]:
    m: Dict[str, List[str]] = {}
    for d in reader_root.iterdir():
        if not d.is_dir():
            continue
        chunks: List[str] = []
        for rj in d.glob("*_reader.json"):
            txt = _load_reader_text(rj)
            if txt:
                chunks.append(txt)
        if not chunks:
            continue
        combined = "\n".join(chunks)
        names = set()
        for rj in d.glob("*_merged_raw_target_rows.json"):
            for fn in _load_raw_filenames(rj):
                names.add(fn)
        if not names:
            names.add(d.name + ".pdf")
        for fn in names:
            k = _norm_filename(fn)
            if not k:
                continue
            m.setdefault(k, []).append(combined)
    return {k: "\n".join(vs) for k, vs in m.items()}


def extract_candidates(text: str) -> Dict[str, Optional[str]]:
    t = text.lower()
    cand: Dict[str, Optional[str]] = {
        "pyrolysis_temp_C": None,
        "hold_duration_h": None,
        "heating_rate_C_min": None,
        "acid_type": None,
        "acid_conc_mol_L": None,
        "acid_time_h": None,
        "acid_temp_C": None,
    }

    pyro = re.findall(r"(?:pyrolys\w*|carboniz\w*|charred|calcined)[^.\n]{0,80}?(\d{2,4}(?:\.\d+)?)\s*(?:°\s*)?c", t)
    hold = re.findall(r"(?:hold(?:ing)?|residence|maintain(?:ed)?|kept|for)\s*(?:time\s*)?(?:of\s*)?(\d+(?:\.\d+)?)\s*h", t)
    heat = re.findall(r"(\d+(?:\.\d+)?)\s*(?:°\s*)?c\s*/\s*min", t)

    cand["pyrolysis_temp_C"] = _pick_mode(pyro, min_val=100, max_val=1300)
    cand["hold_duration_h"] = _pick_mode(hold, min_val=0.05, max_val=200)
    cand["heating_rate_C_min"] = _pick_mode(heat, min_val=0.01, max_val=200)

    acids = []
    acid_map = [
        (r"\bhcl\b|hydrochloric", "HCl"),
        (r"\bhno3\b|nitric", "HNO3"),
        (r"\bh2so4\b|sulfuric|sulphuric", "H2SO4"),
        (r"\bh3po4\b|phosphoric", "H3PO4"),
        (r"citric", "citric acid"),
        (r"acetic", "acetic acid"),
        (r"oxalic", "oxalic acid"),
    ]
    for p, name in acid_map:
        if re.search(p, t):
            acids.append(name)
    acids = sorted(set(acids))
    if len(acids) == 1:
        cand["acid_type"] = acids[0]

    acid_conc = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:mol\s*/\s*l|m\b)", t):
        span = t[max(0, m.start() - 40): m.end() + 40]
        if "acid" in span or "hcl" in span or "hno3" in span or "h2so4" in span or "h3po4" in span:
            acid_conc.append(m.group(1))
    cand["acid_conc_mol_L"] = _pick_mode(acid_conc, min_val=0.001, max_val=30)

    acid_time = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*h", t):
        span = t[max(0, m.start() - 60): m.end() + 30]
        if "acid" in span or "treated" in span or "modif" in span:
            acid_time.append(m.group(1))
    cand["acid_time_h"] = _pick_mode(acid_time, min_val=0.01, max_val=300)

    acid_temp = []
    for m in re.finditer(r"(\d{2,3}(?:\.\d+)?)\s*(?:°\s*)?c", t):
        span = t[max(0, m.start() - 60): m.end() + 30]
        if "acid" in span or "treated" in span:
            acid_temp.append(m.group(1))
    cand["acid_temp_C"] = _pick_mode(acid_temp, min_val=0, max_val=200)

    return cand


def run(args: argparse.Namespace) -> int:
    xlsx = Path(args.xlsx).expanduser().resolve()
    reader_root = Path(args.reader_root).expanduser().resolve()
    out_xlsx = Path(args.out_xlsx).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    book = pd.read_excel(xlsx, sheet_name=None)
    if "sheet1" not in book:
        raise SystemExit("[ERROR] sheet1 not found")
    df = book["sheet1"].copy()
    if "filename" not in df.columns:
        raise SystemExit("[ERROR] sheet1 missing filename column")

    txt_map = collect_text_by_filename(reader_root)
    file_keys_with_text = len(txt_map)
    detail = []
    cells_filled = 0

    groups = df.groupby(df["filename"].map(_norm_filename))
    for fn_key, idxs in groups.groups.items():
        text = txt_map.get(fn_key, "")
        if not text.strip():
            continue
        cand = extract_candidates(text)
        for idx in idxs:
            # General process fields
            for f in ("pyrolysis_temp_C", "hold_duration_h", "heating_rate_C_min"):
                if f not in df.columns:
                    continue
                if _is_blank(df.at[idx, f]) and cand.get(f):
                    df.at[idx, f] = cand[f]
                    cells_filled += 1
                    detail.append({"row": int(idx) + 2, "field": f, "value": cand[f], "source": "method_text"})

            # Acid-related fields are more sensitive.
            acid_related = False
            acid_type_val = str(df.at[idx, "acid_type"]).strip() if "acid_type" in df.columns and not _is_blank(df.at[idx, "acid_type"]) else ""
            mod_seq = str(df.at[idx, "modification_sequence"]).lower() if "modification_sequence" in df.columns and not _is_blank(df.at[idx, "modification_sequence"]) else ""
            if acid_type_val or "acid" in mod_seq:
                acid_related = True
            if args.allow_global:
                acid_related = True

            if acid_related:
                if "acid_type" in df.columns and _is_blank(df.at[idx, "acid_type"]) and cand.get("acid_type"):
                    df.at[idx, "acid_type"] = cand["acid_type"]
                    cells_filled += 1
                    detail.append({"row": int(idx) + 2, "field": "acid_type", "value": cand["acid_type"], "source": "method_text"})
                for f in ("acid_conc_mol_L", "acid_time_h", "acid_temp_C"):
                    if f in df.columns and _is_blank(df.at[idx, f]) and cand.get(f):
                        df.at[idx, f] = cand[f]
                        cells_filled += 1
                        detail.append({"row": int(idx) + 2, "field": f, "value": cand[f], "source": "method_text"})

    book["sheet1"] = df
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        for name, sheet_df in book.items():
            if name == "sheet1":
                df.to_excel(writer, index=False, sheet_name=name)
            else:
                sheet_df.to_excel(writer, index=False, sheet_name=name)

    log_obj = {
        "input_xlsx": str(xlsx),
        "reader_root": str(reader_root),
        "file_keys_with_text": file_keys_with_text,
        "cells_filled": cells_filled,
        "allow_global": bool(args.allow_global),
        "fills": detail[:2000],
    }
    log_path.write_text(json.dumps(log_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Method Text Backfill Summary ===")
    print(f"Input xlsx: {xlsx}")
    print(f"Reader root: {reader_root}")
    print(f"File keys with text: {file_keys_with_text}")
    print(f"Cells filled: {cells_filled}")
    print(f"Saved: {out_xlsx}")
    print(f"Saved log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
