#!/usr/bin/env python3
import re
from typing import Dict, List, Optional, Tuple


SHEET1_FIELDS = [
    "filename",
    "sample_id",
    "biomass_source",
    "pyrolysis_temp_C",
    "hold_duration_h",
    "heating_rate_C_min",
    "acid_type",
    "acid_conc_mol_L",
    "acid_conc_original",
    "acid_conc_mol_L_source",
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
    "ratio_CN",
    "ratio_OC",
    "ratio_HC",
    "ratio_ON_C",
    "pH_pzc",
]


HEADER_PATTERNS = {
    "sample_id": [r"\bsample\b", r"\badsorbent\b", r"\bmaterial\b", r"\bbiochar\b", r"\bcode\b", r"\bid\b"],
    "biomass_source": [r"\bbiomass\b", r"\bfeedstock\b", r"\bprecursor\b", r"\bsource\b", r"\braw material\b"],
    "pyrolysis_temp_C": [r"\bpyrolysis\b.*\btemp", r"\bcarbonization\b.*\btemp", r"\bhtc\b.*\btemp", r"\bhydrothermal\b.*\btemp"],
    "hold_duration_h": [r"\bhold\b", r"\bresidence\b", r"\bretention\b", r"\bduration\b", r"\btime at\b"],
    "heating_rate_C_min": [r"\bheating rate\b", r"\bramp\b"],
    "acid_type": [r"\bacid\b", r"\bactivator\b", r"\bmodifier\b", r"\bmodification agent\b"],
    "acid_conc_mol_L": [r"\bconc", r"\bconcentration\b", r"\bmolar", r"\bmol/?l\b", r"\bwt%?\b", r"\bw/w\b", r"\bv/v\b"],
    "acid_time_h": [r"\bacid\b.*\btime\b", r"\btreatment\b.*\btime\b", r"\bactivation\b.*\btime\b", r"\bimpregnation\b.*\btime\b"],
    "acid_temp_C": [r"\bacid\b.*\btemp\b", r"\btreatment\b.*\btemp\b", r"\bactivation\b.*\btemp\b"],
    "modification_sequence": [r"\bmethod\b", r"\bprocedure\b", r"\bsequence\b", r"\broute\b", r"\bmodification\b"],
    "SSA_m2_g": [r"\bssa\b", r"\bs[\s_-]*bet\b", r"\bbet\b", r"\bsurface area\b", r"\bm2/g\b"],
    "APS_nm": [r"\baps\b", r"\baverage pore size\b", r"\bpore diameter\b", r"\bnm\b"],
    "TPV_cm3_g": [r"\btpv\b", r"\bpore volume\b", r"\btotal pore volume\b", r"\bcm3/g\b"],
    "ash_percent": [r"\bash\b"],
    "C_percent": [r"(^|[^a-z])c\s*\(%?\)", r"\bc%$", r"\bcarbon\b", r"\bcomposition\b.*\bc$"],
    "O_percent": [r"(^|[^a-z])o\s*\(%?\)", r"\bo%$", r"\boxygen\b", r"\bcomposition\b.*\bo$"],
    "N_percent": [r"(^|[^a-z])n\s*\(%?\)", r"\bn%$", r"\bnitrogen\b", r"\bcomposition\b.*\bn$"],
    "H_percent": [r"(^|[^a-z])h\s*\(%?\)", r"\bh%$", r"\bhydrogen\b", r"\bcomposition\b.*\bh$"],
    "ratio_CN": [r"\bc/?n\b", r"\bcn\b"],
    "ratio_OC": [r"\bo/?c\b", r"\boc\b"],
    "ratio_HC": [r"\bh/?c\b", r"\bhc\b"],
    "ratio_ON_C": [r"\(o\+n\)/c", r"\bon/?c\b", r"\bon_c\b"],
    "pH_pzc": [r"\bp[hz]?[_\s-]*(?:pzc|zpc)\b", r"\b(?:pzc|zpc)\b", r"^ph$"],
}


ACID_DB = {
    "hcl": {"mw": 36.46094, "density_solution": 1.19, "density_pure": 1.19},
    "hno3": {"mw": 63.01284, "density_solution": 1.41, "density_pure": 1.51},
    "h2so4": {"mw": 98.079, "density_solution": 1.84, "density_pure": 1.84},
    "h3po4": {"mw": 97.994, "density_solution": 1.685, "density_pure": 1.885},
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\[[^\]]+\]", " ", s)
    s = s.replace("_", " ")
    s = re.sub(r"[^a-z0-9%()+./ -]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _clean_cell(s: str) -> str:
    t = str(s or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\[\^[^\]]+\]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _dedupe_repeated_scalar(s: str) -> str:
    t = _clean_cell(s)
    if not t:
        return ""
    # Exact repeated token sequence: "x x" or "x x x"
    parts = t.split()
    if len(parts) >= 2 and len(set(parts)) == 1:
        return parts[0]
    # Repeated numeric scalar: "1505.92 1505.92"
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+(?:\1(?:\s+)*)+", t)
    if m:
        return m.group(1)
    return t


def _is_sep_cell(s: str) -> bool:
    t = str(s or "").strip()
    return bool(t) and bool(re.fullmatch(r":?-{2,}:?", t))


def _is_sep_row(cells: List[str]) -> bool:
    if not cells:
        return False
    return sum(1 for c in cells if _is_sep_cell(c)) >= max(1, int(0.6 * len(cells)))


def _split_row(line: str) -> List[str]:
    line = line.strip()
    if "|" not in line:
        return []
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [_clean_cell(c) for c in line.split("|")]


def _to_matrix(markdown: str) -> List[List[str]]:
    rows = []
    for line in str(markdown or "").splitlines():
        cells = _split_row(line)
        if len(cells) >= 2:
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    out = []
    for r in rows:
        if len(r) < width:
            r = r + [""] * (width - len(r))
        out.append(r[:width])
    out = [r for r in out if not _is_sep_row(r)]
    return out


def _is_unit_cell(s: str) -> bool:
    t = _norm(s)
    if not t:
        return False
    if re.search(
        r"(m\s*2\s*/\s*g|cm\s*3\s*/\s*g|m2/g|cm3/g|nm|mg/?l|mg/?g|mol/?l|wt%|v/v|w/w|%)",
        t,
        re.I,
    ):
        return True
    t2 = t.strip("()[]{} ").strip()
    if re.fullmatch(r"(k|c|°c|min|h|hr|hrs|hour|hours)", t2, re.I):
        return True
    return False


def _is_unitish_row(row: List[str]) -> bool:
    if not row:
        return False
    n_unit = sum(1 for c in row if _is_unit_cell(c))
    n_empty = sum(1 for c in row if not c.strip())
    n_sample = sum(1 for c in row if _looks_sample_token(c) and not _is_unit_cell(c))
    return (n_unit + n_empty) >= max(1, int(0.6 * len(row))) and n_sample <= int(0.4 * len(row))


def _is_subheader_cell(s: str) -> bool:
    t = _norm(s)
    if not t:
        return False
    if re.fullmatch(r"(sample|yield(?:\s*s)?(?:\s*\(%\))?|c|h|o|n|o/c|h/c|\(o\+n\)/c|ph)", t):
        return True
    if re.fullmatch(r"(s\s*bet.*|q\s*m|k\s*l|k\s*f|r\s*2)", t):
        return True
    return False


def _is_subheader_row(row: List[str]) -> bool:
    if not row:
        return False
    non_empty = [c for c in row if str(c or "").strip()]
    if not non_empty:
        return False
    n_known = sum(1 for c in non_empty if _is_subheader_cell(c))
    n_numeric = sum(1 for c in non_empty if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(c).strip()))
    return n_known >= max(2, int(0.4 * len(non_empty))) and n_numeric <= int(0.3 * len(non_empty))


def _merge_header_cells(a: str, b: str) -> str:
    aa = _clean_cell(a)
    bb = _clean_cell(b)
    if not aa:
        return bb
    if not bb:
        return aa
    if _norm(aa) == _norm(bb):
        return aa
    return f"{aa} {bb}".strip()


def _merge_header_rows(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    if not rows:
        return [], []
    header = rows[0]
    data = rows[1:]
    # Support multi-row headers commonly found in SI tables:
    # 1) unit rows, and 2) subheader rows such as C/H/O/N beneath grouped titles.
    merge_steps = 0
    while data and merge_steps < 2 and (
        _is_unitish_row(data[0])
        or _is_subheader_row(data[0])
        or _should_merge_followup_header_row(header, data[0])
    ):
        header = [_merge_header_cells(a, b) for a, b in zip(header, data[0])]
        data = data[1:]
        merge_steps += 1
    return header, data


def _should_merge_followup_header_row(header: List[str], next_row: List[str]) -> bool:
    if not header or not next_row:
        return False
    header_non_empty = sum(1 for c in header if str(c or "").strip())
    if header_non_empty > max(2, int(0.5 * len(header))):
        return False
    mapped = 0
    sample_like = 0
    for cell in next_row:
        if _map_header_text(cell, allow_generic_ph_pzc=False):
            mapped += 1
        elif _looks_sample_token(cell) and not _is_unit_cell(cell):
            sample_like += 1
    return mapped >= 2 and sample_like <= 1


def _map_headers(headers: List[str]) -> Dict[str, int]:
    mapped = {}
    for idx, h in enumerate(headers):
        field = _map_header_text(h)
        if field and field not in mapped:
            mapped[field] = idx
    return mapped


def _looks_sample_token(s: str) -> bool:
    t = str(s or "").strip()
    if not t:
        return False
    if len(t) > 40:
        return False
    if re.fullmatch(r"[0-9.]+", t):
        return False
    if re.fullmatch(r"[A-Z][a-z]{5,}", t):
        # likely a material/common noun instead of sample code
        return False
    if re.search(r"(table|figure|references?|content)", t, re.I):
        return False
    return bool(re.search(r"[A-Za-z]", t))


def _map_header_text(text: str, allow_generic_ph_pzc: bool = True) -> Optional[str]:
    hn = _norm(text)
    if not hn:
        return None
    for field, pats in HEADER_PATTERNS.items():
        for p in pats:
            if field == "pH_pzc" and not allow_generic_ph_pzc and p == r"^ph$":
                continue
            if re.search(p, hn):
                return field
    return None


def _normalize_sample_id(s: str) -> str:
    t = _clean_cell(s)
    parts = [p for p in re.split(r"\s+", t) if p]
    if len(parts) >= 2 and len(set(parts)) == 1:
        t = parts[0]
    return t


def _infer_transposed_property_col_idx(
    headers: List[str], data_rows: List[List[str]]
) -> Optional[int]:
    if not headers or not data_rows:
        return None
    best_idx = None
    best_score = -1
    n = min(30, len(data_rows))
    for idx in range(len(headers)):
        score = 0
        for row in data_rows[:n]:
            if idx >= len(row):
                continue
            label = row[idx]
            field = _map_header_text(label, allow_generic_ph_pzc=False)
            if field and field != "sample_id":
                score += 1
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_idx is None or best_score < 2:
        return None
    sample_cols = [
        i
        for i, h in enumerate(headers)
        if i != best_idx
        and _looks_sample_token(h)
        and not _is_unit_cell(h)
        and _map_header_text(h) is None
    ]
    if len(sample_cols) < 2:
        return None
    return best_idx


def _extract_transposed_sheet1_rows(
    headers: List[str], data_rows: List[List[str]]
) -> List[Dict[str, str]]:
    prop_idx = _infer_transposed_property_col_idx(headers, data_rows)
    if prop_idx is None:
        return []

    sample_cols = []
    for idx, head in enumerate(headers):
        if idx == prop_idx:
            continue
        sid = _normalize_sample_id(head)
        if not _looks_sample_token(sid):
            continue
        if _is_unit_cell(sid):
            continue
        if _map_header_text(sid) is not None:
            continue
        sample_cols.append((idx, sid))
    if len(sample_cols) < 2:
        return []

    out = []
    for col_idx, sid in sample_cols:
        row_obj = {k: "" for k in SHEET1_FIELDS}
        row_obj["sample_id"] = sid
        for row_cells in data_rows:
            if prop_idx >= len(row_cells) or col_idx >= len(row_cells):
                continue
            label = row_cells[prop_idx]
            field = _map_header_text(label, allow_generic_ph_pzc=False)
            if not field or field == "sample_id":
                continue
            val = _clean_cell(row_cells[col_idx])
            if not val or val == "-":
                continue
            row_obj[field] = val
        non_empty = sum(
            1
            for k, v in row_obj.items()
            if k not in {"filename", "sample_id"} and str(v).strip()
        )
        if non_empty <= 0:
            continue
        out.append(_normalize_row(row_obj))
    return out


def _infer_sample_col_idx(headers: List[str], data_rows: List[List[str]], mapped: Dict[str, int]) -> Optional[int]:
    if "sample_id" in mapped:
        return mapped["sample_id"]
    if not data_rows:
        return None
    best = None
    best_score = -1
    n = min(20, len(data_rows))
    for idx in range(len(headers)):
        score = 0
        for r in data_rows[:n]:
            if idx < len(r) and _looks_sample_token(r[idx]):
                score += 1
        if score > best_score:
            best_score = score
            best = idx
    if best is None or best_score <= 0:
        return None
    return best


def _extract_float(text: str) -> Optional[float]:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(text or ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _fmt_float(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


def infer_acid_key(text: str) -> Optional[str]:
    t = _norm(text)
    if "hcl" in t or "hydrochloric" in t:
        return "hcl"
    if "hno3" in t or "nitric" in t:
        return "hno3"
    if "h2so4" in t or "sulfuric" in t or "sulphuric" in t:
        return "h2so4"
    if "h3po4" in t or "phosphoric" in t:
        return "h3po4"
    return None


def normalize_and_convert_acid_conc(acid_conc_text: str, acid_type_text: str) -> Tuple[str, str, str]:
    raw = str(acid_conc_text or "").strip()
    acid_txt = str(acid_type_text or "").strip()
    merged = " ".join([raw, acid_txt]).strip()
    source = ""
    molar = ""

    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(mol\s*/?\s*l|mol\s*l-?1|m\b)", _norm(merged))
    if m:
        molar = m.group(1)
        source = "reported_molar"
        return molar, source, raw or merged

    pct_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:wt|w/w|v/v)?\s*%", _norm(merged))
    if not pct_m:
        return molar, source, raw

    pct = _extract_float(pct_m.group(1))
    acid_key = infer_acid_key(merged)
    if pct is None or not acid_key or acid_key not in ACID_DB:
        return molar, source, raw or merged

    db = ACID_DB[acid_key]
    mw = db["mw"]
    tt = _norm(merged)
    if "v/v" in tt:
        # M ~= volume_fraction * density_pure * 1000 / MW
        mol = (pct / 100.0) * db["density_pure"] * 1000.0 / mw
        return _fmt_float(mol), "converted_from_vv_percent", raw or merged

    # default: wt%
    # M ~= wt% * density_solution * 10 / MW
    mol = pct * db["density_solution"] * 10.0 / mw
    return _fmt_float(mol), "converted_from_wt_percent", raw or merged


def _normalize_row(row: Dict[str, str]) -> Dict[str, str]:
    out = {k: "" for k in SHEET1_FIELDS}
    out.update({k: _dedupe_repeated_scalar(v) for k, v in row.items() if k in out})
    if out["acid_conc_mol_L_source"] == "":
        m, src, raw = normalize_and_convert_acid_conc(out["acid_conc_mol_L"], out["acid_type"])
        if m:
            out["acid_conc_mol_L"] = m
            out["acid_conc_mol_L_source"] = src
        if raw:
            out["acid_conc_original"] = raw
    return out


def extract_sheet1_rows_from_markdown_table(markdown: str) -> List[Dict[str, str]]:
    matrix = _to_matrix(markdown)
    if len(matrix) < 2:
        return []
    headers, data_rows = _merge_header_rows(matrix)
    if not headers or not data_rows:
        return []

    transposed_rows = _extract_transposed_sheet1_rows(headers, data_rows)
    if transposed_rows:
        dedup = []
        seen = set()
        for r in transposed_rows:
            key = tuple(r.get(k, "") for k in SHEET1_FIELDS if k != "filename")
            if key in seen:
                continue
            seen.add(key)
            dedup.append(r)
        return dedup

    mapped = _map_headers(headers)
    sample_idx = _infer_sample_col_idx(headers, data_rows, mapped)
    if sample_idx is None:
        return []

    micro_idx = None
    meso_idx = None
    for i, h in enumerate(headers):
        hn = _norm(h)
        if micro_idx is None and re.search(r"\bmicropore\b|\bmicro pore\b", hn):
            micro_idx = i
        if meso_idx is None and re.search(r"\bmesopore\b|\bmesoporous\b|\bmeso pore\b", hn):
            meso_idx = i

    target_hits = [k for k in mapped.keys() if k not in {"sample_id"}]
    if not target_hits:
        return []

    out = []
    for row_cells in data_rows:
        if sample_idx >= len(row_cells):
            continue
        sid = _normalize_sample_id(row_cells[sample_idx])
        if not _looks_sample_token(sid):
            continue
        r = {k: "" for k in SHEET1_FIELDS}
        r["sample_id"] = sid
        for field, idx in mapped.items():
            if idx < len(row_cells):
                val = _clean_cell(row_cells[idx])
                if field == "sample_id":
                    r["sample_id"] = _normalize_sample_id(val or r["sample_id"])
                else:
                    r[field] = val

        # Fallback: derive TPV from micropore + mesoporous volumes when total pore volume
        # is not directly mapped from headers.
        if not str(r.get("TPV_cm3_g", "")).strip():
            mv = None
            sv = None
            if micro_idx is not None and micro_idx < len(row_cells):
                mv = _extract_float(row_cells[micro_idx])
            if meso_idx is not None and meso_idx < len(row_cells):
                sv = _extract_float(row_cells[meso_idx])
            if mv is not None and sv is not None:
                r["TPV_cm3_g"] = _fmt_float(mv + sv)
            elif mv is not None:
                r["TPV_cm3_g"] = _fmt_float(mv)
            elif sv is not None:
                r["TPV_cm3_g"] = _fmt_float(sv)

        non_empty = sum(1 for k, v in r.items() if k not in {"filename", "sample_id"} and str(v).strip())
        if non_empty <= 0:
            continue
        out.append(_normalize_row(r))

    # dedupe same sample rows with identical extracted payload
    dedup = []
    seen = set()
    for r in out:
        key = tuple(r.get(k, "") for k in SHEET1_FIELDS if k != "filename")
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup
