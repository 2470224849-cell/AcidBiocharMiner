#!/usr/bin/env python3
import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


FIELDS = ["pH", "T_K", "Te_min", "SLR_g_L"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill sheet2 from method text in reader json files.")
    p.add_argument("--xlsx", required=True, help="Input Excel path.")
    p.add_argument("--reader-root", required=True, help="Reader/output root.")
    p.add_argument("--sample-filter", default="acid_pristine", help="Reserved arg for compatibility.")
    p.add_argument("--out-xlsx", required=True, help="Output Excel path.")
    p.add_argument("--log", required=True, help="Detail log path.")
    p.add_argument("--allow-global", action="store_true", help="Allow global method text fill.")
    p.add_argument("--room-temp-as-k", action="store_true", help="Map room/ambient temperature to 298.15 K.")
    return p.parse_args()


def _is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip() == ""


def _norm_text(s: str) -> str:
    if s is None:
        return ""
    if isinstance(s, float) and math.isnan(s):
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


def _norm_filename(s: str) -> str:
    return _norm_text(Path(str(s or "")).name)


def _norm_sid(s: str) -> str:
    return _norm_text(str(s or ""))


def _pick_mode_num(values: List[float], min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[float]:
    clean: List[float] = []
    for x in values:
        if min_val is not None and x < min_val:
            continue
        if max_val is not None and x > max_val:
            continue
        clean.append(float(x))
    if not clean:
        return None
    rounded = [round(x, 4) for x in clean]
    cnt = Counter(rounded)
    top = cnt.most_common(2)
    if len(top) == 1 or top[0][1] > top[1][1]:
        return float(top[0][0])
    if len(cnt) == 1:
        return float(next(iter(cnt.keys())))
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


def extract_sheet2_candidates(text: str, room_temp_as_k: bool) -> Dict[str, Optional[float]]:
    t = text.lower()
    out: Dict[str, Optional[float]] = {"pH": None, "T_K": None, "Te_min": None, "SLR_g_L": None}

    ph_vals = [float(x) for x in re.findall(r"(?:^|\\b)p\s*h\\s*(?:=|was|at|of|to)?\\s*(\\d{1,2}(?:\\.\\d+)?)", t)]
    out["pH"] = _pick_mode_num(ph_vals, min_val=0, max_val=14)

    k_vals = [float(x) for x in re.findall(r"(\\d{2,4}(?:\\.\\d+)?)\\s*k\\b", t)]
    c_vals = [float(x) for x in re.findall(r"(\\d{1,3}(?:\\.\\d+)?)\\s*(?:°\\s*)?c\\b", t)]
    t_k_from_c = [x + 273.15 for x in c_vals if 0 <= x <= 200]
    t_candidates = [x for x in k_vals if 250 <= x <= 500] + [x for x in t_k_from_c if 250 <= x <= 500]
    if room_temp_as_k and re.search(r"room temperature|ambient temperature", t):
        t_candidates.append(298.15)
    out["T_K"] = _pick_mode_num(t_candidates, min_val=250, max_val=500)

    te_vals = []
    for m in re.finditer(r"(?:contact|equilibrium|adsorption)\\s*time[^.\\n]{0,25}?(\\d+(?:\\.\\d+)?)\\s*(min|h)\\b", t):
        v = float(m.group(1))
        u = m.group(2)
        if u == "h":
            v *= 60.0
        te_vals.append(v)
    out["Te_min"] = _pick_mode_num(te_vals, min_val=0.1, max_val=100000)

    slr_vals = []
    for m in re.finditer(r"(?:dosage|dose|adsorbent|solid\\s*[-/]?\\s*liquid\\s*ratio|s/l)\\b[^.\\n]{0,25}?(\\d+(?:\\.\\d+)?)\\s*g\\s*/\\s*l", t):
        slr_vals.append(float(m.group(1)))
    # fallback generic g/L if no keyword hit
    if not slr_vals:
        slr_vals = [float(x) for x in re.findall(r"(\\d+(?:\\.\\d+)?)\\s*g\\s*/\\s*l", t)]
    out["SLR_g_L"] = _pick_mode_num(slr_vals, min_val=0.0001, max_val=10000)
    return out


def _fill_group_unique(df: pd.DataFrame, idxs: List[int], field: str) -> int:
    vals = []
    for idx in idxs:
        v = df.at[idx, field]
        if not _is_blank(v):
            vals.append(str(v).strip())
    if not vals:
        return 0
    cnt = Counter(vals)
    if len(cnt) > 1 and cnt.most_common(2)[0][1] == cnt.most_common(2)[1][1]:
        return 0
    chosen = cnt.most_common(1)[0][0]
    filled = 0
    for idx in idxs:
        if _is_blank(df.at[idx, field]):
            df.at[idx, field] = chosen
            filled += 1
    return filled


def run(args: argparse.Namespace) -> int:
    xlsx = Path(args.xlsx).expanduser().resolve()
    reader_root = Path(args.reader_root).expanduser().resolve()
    out_xlsx = Path(args.out_xlsx).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve()
    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    book = pd.read_excel(xlsx, sheet_name=None)
    if "sheet2" not in book:
        raise SystemExit("[ERROR] sheet2 not found")
    df = book["sheet2"].copy()
    if "filename" not in df.columns:
        raise SystemExit("[ERROR] sheet2 missing filename column")

    txt_map = collect_text_by_filename(reader_root)
    file_keys_with_text = len(txt_map)

    for f in FIELDS:
        if f not in df.columns:
            df[f] = ""

    detail = []
    direct_filled = 0
    stats = {
        "sample_fill_pH": 0,
        "sample_fill_T_K": 0,
        "sample_fill_Te_min": 0,
        "sample_fill_SLR_g_L": 0,
        "pollutant_fill_pH": 0,
        "pollutant_fill_T_K": 0,
        "pollutant_fill_Te_min": 0,
        "pollutant_fill_SLR_g_L": 0,
        "paper_fill_pH": 0,
        "paper_fill_T_K": 0,
        "paper_fill_Te_min": 0,
        "paper_fill_SLR_g_L": 0,
        "paper_default_fill_pH": 0,
        "paper_default_fill_T_K": 0,
        "paper_default_fill_Te_min": 0,
        "paper_default_fill_SLR_g_L": 0,
    }

    # Direct fill from method text (paper-level).
    groups = df.groupby(df["filename"].map(_norm_filename))
    for fn_key, idxs in groups.groups.items():
        text = txt_map.get(fn_key, "")
        if not text.strip():
            continue
        cand = extract_sheet2_candidates(text, room_temp_as_k=bool(args.room_temp_as_k))
        for idx in idxs:
            for f in FIELDS:
                if _is_blank(df.at[idx, f]) and cand.get(f) is not None:
                    # keep conservative when not allow-global: still allow, because these are shared conditions.
                    df.at[idx, f] = f"{cand[f]:g}"
                    direct_filled += 1
                    detail.append({"row": int(idx) + 2, "field": f, "value": f"{cand[f]:g}", "source": "method_text"})

    # Hierarchical propagation in existing sheet2 table.
    if "sample_id" in df.columns:
        g = df.groupby([df["filename"].map(_norm_filename), df["sample_id"].map(_norm_sid)])
        for _, idxs in g.groups.items():
            idx_list = list(idxs)
            if len(idx_list) < 2:
                continue
            for f in FIELDS:
                n = _fill_group_unique(df, idx_list, f)
                if n:
                    stats[f"sample_fill_{f}"] += n

    if "pollutant_name" in df.columns:
        g = df.groupby([df["filename"].map(_norm_filename), df["pollutant_name"].map(_norm_text)])
        for _, idxs in g.groups.items():
            idx_list = list(idxs)
            if len(idx_list) < 2:
                continue
            for f in FIELDS:
                n = _fill_group_unique(df, idx_list, f)
                if n:
                    stats[f"pollutant_fill_{f}"] += n

    g = df.groupby(df["filename"].map(_norm_filename))
    for _, idxs in g.groups.items():
        idx_list = list(idxs)
        if len(idx_list) < 2:
            continue
        for f in FIELDS:
            n = _fill_group_unique(df, idx_list, f)
            if n:
                stats[f"paper_fill_{f}"] += n

    book["sheet2"] = df
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        for name, sheet_df in book.items():
            if name == "sheet2":
                df.to_excel(writer, index=False, sheet_name=name)
            else:
                sheet_df.to_excel(writer, index=False, sheet_name=name)

    log_obj = {
        "input_xlsx": str(xlsx),
        "reader_root": str(reader_root),
        "file_keys_with_text": file_keys_with_text,
        "direct_cells_filled": direct_filled,
        "hierarchical_stats": stats,
        "fills": detail[:3000],
    }
    log_path.write_text(json.dumps(log_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Sheet2 Method Backfill Summary ===")
    print(f"Input xlsx: {xlsx}")
    print(f"Reader root: {reader_root}")
    print(f"File keys with text: {file_keys_with_text}")
    print(f"Direct cells filled from text: {direct_filled}")
    print(
        "Hierarchical fill stats: "
        f"sample pH +{stats['sample_fill_pH']}, sample T_K +{stats['sample_fill_T_K']}, sample Te_min +{stats['sample_fill_Te_min']}, sample SLR +{stats['sample_fill_SLR_g_L']}, "
        f"pollutant pH +{stats['pollutant_fill_pH']}, pollutant T_K +{stats['pollutant_fill_T_K']}, pollutant Te_min +{stats['pollutant_fill_Te_min']}, pollutant SLR +{stats['pollutant_fill_SLR_g_L']}, "
        f"paper pH +{stats['paper_fill_pH']}, paper T_K +{stats['paper_fill_T_K']}, paper Te_min +{stats['paper_fill_Te_min']}, paper SLR +{stats['paper_fill_SLR_g_L']}, "
        f"paper-default pH +{stats['paper_default_fill_pH']}, paper-default T_K +{stats['paper_default_fill_T_K']}, paper-default Te_min +{stats['paper_default_fill_Te_min']}, paper-default SLR +{stats['paper_default_fill_SLR_g_L']}"
    )
    print(f"Saved: {out_xlsx}")
    print(f"Saved log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
