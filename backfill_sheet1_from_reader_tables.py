#!/usr/bin/env python3
import argparse
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


TARGET_FIELDS = [
    "biomass_source",
    "pyrolysis_temp_C",
    "hold_duration_h",
    "heating_rate_C_min",
    "acid_type",
    "acid_conc_mol_L",
    "acid_time_h",
    "acid_temp_C",
    "modification_sequence",
    "SSA_m2_g",
    "APS_nm",
    "TPV_cm3_g",
    "ash_percent",
    "C_percent",
    "O_percent",
    "N_percent",
    "H_percent",
    "pH_pzc",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill sheet1 from extracted raw rows (table-focused).")
    p.add_argument("--xlsx", required=True, help="Input Excel path.")
    p.add_argument("--reader-root", required=True, help="Reader/output root containing merged raw json files.")
    p.add_argument("--out-xlsx", required=True, help="Output Excel path.")
    p.add_argument("--log", required=True, help="Output detail log path.")
    return p.parse_args()


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    s = str(v).strip()
    if s == "":
        return True
    if s.lower() in {"none", "nan", "na", "n/a", "null", "not_reported"}:
        return True
    return False


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _norm_filename(s: str) -> str:
    return _norm_text(Path(str(s or "")).name)


def _norm_sample_id(s: str) -> str:
    if s is None:
        return ""
    text = str(s)
    trans = str.maketrans(
        {
            "₀": "0",
            "₁": "1",
            "₂": "2",
            "₃": "3",
            "₄": "4",
            "₅": "5",
            "₆": "6",
            "₇": "7",
            "₈": "8",
            "₉": "9",
            "＋": "+",
            "﹢": "+",
            "⁺": "+",
            "þ": "+",
            "–": "-",
            "—": "-",
            "−": "-",
        }
    )
    text = text.translate(trans)
    return _norm_text(text)


def _sid_aliases(s: str) -> List[str]:
    """
    Build conservative alias keys for sample-id matching.
    Example: "SDB350 modified with 96S" -> alias close to "SDB350+96S".
    """
    raw = str(s or "")
    if not raw.strip():
        return []
    base = _norm_sample_id(raw)
    aliases = {base}
    simplified = re.sub(r"(?i)\bmodified\b", " ", raw)
    simplified = re.sub(r"(?i)\bwith\b", " ", simplified)
    simplified = re.sub(r"(?i)\btreated\b", " ", simplified)
    simplified_norm = _norm_sample_id(simplified)
    if simplified_norm:
        aliases.add(simplified_norm)
    return [a for a in aliases if a]


def _norm_key(s: str) -> str:
    return _norm_text(str(s or ""))


def _load_json_rows(path: Path) -> List[dict]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return obj if isinstance(obj, list) else []


def collect_raw_rows(reader_root: Path) -> List[dict]:
    all_rows: List[dict] = []
    batch = reader_root / "batch_merged_raw_target_rows.json"
    if batch.exists():
        all_rows.extend(_load_json_rows(batch))
    for p in reader_root.glob("*/*_merged_raw_target_rows.json"):
        all_rows.extend(_load_json_rows(p))
    return all_rows


def build_lookup(
    raw_rows: List[dict],
) -> Tuple[
    Dict[Tuple[str, str], Dict[str, set]],
    Dict[Tuple[str, str], Dict[str, set]],
    Dict[str, Dict[str, set]],
    int,
]:
    by_file_sample: Dict[Tuple[str, str], Dict[str, set]] = {}
    by_file_alias: Dict[Tuple[str, str], Dict[str, set]] = {}
    by_file: Dict[str, Dict[str, set]] = {}
    sample_keys = set()
    for item in raw_rows:
        key = _norm_key(item.get("key"))
        if key not in {"biocharmodification"}:
            continue
        row = item.get("row")
        if not isinstance(row, dict):
            continue
        fn = _norm_filename(row.get("filename") or "")
        sid_raw = row.get("sample_id") or ""
        sid = _norm_sample_id(sid_raw)
        if not fn:
            continue
        if sid:
            sample_keys.add((fn, sid))
            by_file_sample.setdefault((fn, sid), {})
            for sid_alias in _sid_aliases(str(sid_raw)):
                by_file_alias.setdefault((fn, sid_alias), {})
        by_file.setdefault(fn, {})
        for f in TARGET_FIELDS:
            v = row.get(f, "")
            if _is_blank(v):
                continue
            if sid:
                by_file_sample[(fn, sid)].setdefault(f, set()).add(str(v).strip())
                for sid_alias in _sid_aliases(str(sid_raw)):
                    by_file_alias[(fn, sid_alias)].setdefault(f, set()).add(str(v).strip())
            by_file[fn].setdefault(f, set()).add(str(v).strip())
    return by_file_sample, by_file_alias, by_file, len(sample_keys)


def _unique_value(values: set):
    if not values:
        return None
    if len(values) == 1:
        return next(iter(values))
    return None


def run(args: argparse.Namespace) -> int:
    xlsx = Path(args.xlsx).expanduser().resolve()
    reader_root = Path(args.reader_root).expanduser().resolve()
    out_xlsx = Path(args.out_xlsx).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    book = pd.read_excel(xlsx, sheet_name=None)
    if "sheet1" not in book:
        raise SystemExit("[ERROR] sheet1 not found in input xlsx")
    df = book["sheet1"].copy()

    raw_rows = collect_raw_rows(reader_root)
    by_file_sample, by_file_alias, by_file, sample_key_count = build_lookup(raw_rows)

    if "filename" not in df.columns or "sample_id" not in df.columns:
        raise SystemExit("[ERROR] sheet1 missing filename/sample_id columns")

    # per-file known samples: used only for safe sample-id fill.
    file_to_samples: Dict[str, set] = {}
    for fn, sid in by_file_sample.keys():
        file_to_samples.setdefault(fn, set()).add(sid)

    cells_filled = 0
    sid_filled = 0
    alias_hit = 0
    detail_rows: List[dict] = []

    for idx in df.index:
        fn_raw = df.at[idx, "filename"] if "filename" in df.columns else ""
        sid_raw = df.at[idx, "sample_id"] if "sample_id" in df.columns else ""
        fn = _norm_filename(fn_raw)
        sid = _norm_sample_id(sid_raw)
        if not fn:
            continue

        if _is_blank(sid_raw):
            cands = file_to_samples.get(fn, set())
            if len(cands) == 1:
                sid = next(iter(cands))
                df.at[idx, "sample_id"] = sid
                sid_filled += 1
                cells_filled += 1

        fs_map = by_file_sample.get((fn, sid), {}) if sid else {}
        fa_map: Dict[str, set] = {}
        if sid:
            for sid_alias in _sid_aliases(str(sid_raw)):
                amap = by_file_alias.get((fn, sid_alias), {})
                if not amap:
                    continue
                for f, vals in amap.items():
                    fa_map.setdefault(f, set()).update(vals)
            if fa_map:
                alias_hit += 1
        f_map = by_file.get(fn, {})

        for f in TARGET_FIELDS:
            if f not in df.columns:
                continue
            cur = df.at[idx, f]
            if not _is_blank(cur):
                continue
            v = _unique_value(fs_map.get(f, set()))
            src = "file+sample"
            if v is None:
                v = _unique_value(fa_map.get(f, set()))
                src = "file+sample_alias"
            if v is None:
                v = _unique_value(f_map.get(f, set()))
                src = "file"
            if v is None:
                continue
            df.at[idx, f] = v
            cells_filled += 1
            detail_rows.append({"row": int(idx) + 2, "field": f, "value": v, "source": src})

    book["sheet1"] = df
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        for name, sheet_df in book.items():
            if name == "sheet1":
                df.to_excel(writer, index=False, sheet_name=name)
            else:
                sheet_df.to_excel(writer, index=False, sheet_name=name)

    detail = {
        "input_xlsx": str(xlsx),
        "reader_root": str(reader_root),
        "sample_keys": sample_key_count,
        "rows_sheet1": int(len(df)),
        "cells_filled": int(cells_filled),
        "sample_id_filled": int(sid_filled),
        "sample_alias_hit_rows": int(alias_hit),
        "fills": detail_rows[:2000],
    }
    log_path.write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Backfill Summary ===")
    print(f"Input xlsx: {xlsx}")
    print(f"Reader root: {reader_root}")
    print(f"Sample keys from tables: {sample_key_count}")
    print(f"Cells filled: {cells_filled}")
    print(f"Saved: {out_xlsx}")
    print(f"Saved log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
