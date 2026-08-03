#!/usr/bin/env python3
import re
from typing import Dict, List, Optional, Tuple


SHEET2_FIELDS = [
    "filename",
    "sample_id",
    "pollutant_name",
    "pH",
    "T_K",
    "Te_min",
    "SLR_g_L",
    "Qmax",
]


HEADER_PATTERNS = {
    "sample_id": [
        r"\bsample\b",
        r"\badsorbent\b",
        r"\bsorbent\b",
        r"\bmaterial\b",
        r"\bbiochar\b",
        r"\bcode\b",
        r"\bid\b",
    ],
    "pollutant_name": [
        r"\bpollutant\b",
        r"\badsorbate\b",
        r"\bmetal\b",
        r"\bion\b",
        r"\bcontaminant\b",
        r"\bsolute\b",
    ],
    "pH": [r"^ph\b", r"\bsolution\s*ph\b", r"\binitial\s*ph\b"],
    "T_K": [r"\btemperature\b", r"\btemp\b", r"^t$", r"\bt\s*\(?k\)?\b", r"\b\(?k\)?\b"],
    "Te_min": [
        r"\bequilibrium\s*time\b",
        r"\bcontact\s*time\b",
        r"\btime\b",
        r"\bte\b",
        r"\bmin\b",
        r"\bhour",
        r"\bhr\b",
    ],
    "SLR_g_L": [
        r"\bslr\b",
        r"\bsolid\s*liquid\s*ratio\b",
        r"\bsolid/liquid\b",
        r"\badsorbent\s*dose\b",
        r"\bdosage\b",
        r"\bg/?l\b",
    ],
    "Qmax": [
        r"\bq\s*max\b",
        r"\bqmax\b",
        r"\bqm\b",
        r"\bmaximum\s+(?:adsorption\s+)?capacity\b",
        r"\bmonolayer\s+(?:adsorption\s+)?capacity\b",
        r"\blangmuir\s+(?:adsorption\s+)?capacity\b",
    ],
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
    return [r for r in out if not _is_sep_row(r)]


def _is_unit_cell(s: str) -> bool:
    t = _norm(s)
    if not t:
        return False
    return bool(re.search(r"(mg/?l|mg/?g|g/?l|k|°c|c|min|h|hr|hour|hours|%)", t, re.I))


def _is_unitish_row(row: List[str]) -> bool:
    if not row:
        return False
    n_unit = sum(1 for c in row if _is_unit_cell(c))
    n_empty = sum(1 for c in row if not str(c or "").strip())
    return (n_unit + n_empty) >= max(1, int(0.6 * len(row)))


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
    merge_steps = 0
    while data and merge_steps < 2 and _is_unitish_row(data[0]):
        header = [_merge_header_cells(a, b) for a, b in zip(header, data[0])]
        data = data[1:]
        merge_steps += 1
    return header, data


def _map_headers(headers: List[str]) -> Dict[str, int]:
    mapped = {}
    for idx, h in enumerate(headers):
        hn = _norm(h)
        for field, pats in HEADER_PATTERNS.items():
            if field in mapped:
                continue
            for p in pats:
                if re.search(p, hn):
                    mapped[field] = idx
                    break
    return mapped


def _looks_sample_token(s: str) -> bool:
    t = str(s or "").strip()
    if not t:
        return False
    if len(t) > 60:
        return False
    if re.fullmatch(r"[0-9.]+", t):
        return False
    if re.search(r"(table|figure|references?|content)", t, re.I):
        return False
    return bool(re.search(r"[A-Za-z]", t))


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


def _infer_pollutant_col_idx(headers: List[str], data_rows: List[List[str]], mapped: Dict[str, int]) -> Optional[int]:
    if "pollutant_name" in mapped:
        return mapped["pollutant_name"]
    # no reliable fallback; keep strict
    return None


def _extract_first_number(text: str) -> str:
    t = str(text or "").replace(",", "")
    m = re.search(r"[-+]?[0-9]+(?:\.[0-9]+)?", t)
    if not m:
        return ""
    return m.group(0)


def _to_num(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _fmt_float(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s


def _normalize_field(field: str, value: str, header_text: str) -> str:
    v = _clean_cell(value)
    if not v:
        return ""
    hn = _norm(header_text)
    num = _extract_first_number(v)
    if field in {"pH", "T_K", "Te_min", "SLR_g_L", "Qmax"}:
        if not num:
            return ""
    if field == "pH":
        return num
    if field == "T_K":
        x = _to_num(num)
        if x is None:
            return num
        # If clearly Celsius, convert to Kelvin.
        if re.search(r"(°\s*c|\bc\b|\bcelsius\b)", hn) and not re.search(r"\bk\b", hn):
            return _fmt_float(x + 273.15)
        return num
    if field == "Te_min":
        x = _to_num(num)
        if x is None:
            return num
        if re.search(r"(\bhour\b|\bhr\b|\bh\b)", hn) and not re.search(r"\bmin\b", hn):
            return _fmt_float(x * 60.0)
        if re.search(r"(\bhour\b|\bhr\b|\bh\b)", _norm(v)) and not re.search(r"\bmin\b", _norm(v)):
            return _fmt_float(x * 60.0)
        return num
    if field == "SLR_g_L":
        return num
    if field == "Qmax":
        return num
    return v


def _looks_adsorption_table(headers: List[str], mapped: Dict[str, int]) -> bool:
    # Conservative gate to avoid pulling non-adsorption tables.
    header_text = " ".join(_norm(h) for h in headers)
    has_condition = any(k in mapped for k in ("pH", "T_K", "Te_min", "SLR_g_L"))
    has_ads_hint = bool(
        re.search(
            r"(adsorption|isotherm|kinetic|adsorbent|adsorbate|pollutant|metal|ion|qe|qmax|langmuir|freundlich)",
            header_text,
        )
    )
    return has_condition and has_ads_hint


def extract_sheet2_rows_from_markdown_table(markdown: str) -> List[Dict[str, str]]:
    matrix = _to_matrix(markdown)
    if len(matrix) < 2:
        return []

    headers, data_rows = _merge_header_rows(matrix)
    if not headers or not data_rows:
        return []

    mapped = _map_headers(headers)
    if not _looks_adsorption_table(headers, mapped):
        return []

    sample_idx = _infer_sample_col_idx(headers, data_rows, mapped)
    pollutant_idx = _infer_pollutant_col_idx(headers, data_rows, mapped)

    if sample_idx is None:
        return []

    out: List[Dict[str, str]] = []
    prev_sample = ""
    prev_pollutant = ""
    for row_cells in data_rows:
        r = {k: "" for k in SHEET2_FIELDS}

        sid = row_cells[sample_idx] if sample_idx < len(row_cells) else ""
        sid = _clean_cell(sid)
        if not sid:
            sid = prev_sample
        if sid:
            prev_sample = sid
        r["sample_id"] = sid

        if pollutant_idx is not None and pollutant_idx < len(row_cells):
            pol = _clean_cell(row_cells[pollutant_idx])
            if not pol:
                pol = prev_pollutant
            if pol:
                prev_pollutant = pol
            r["pollutant_name"] = pol

        for field in ("pH", "T_K", "Te_min", "SLR_g_L", "Qmax"):
            idx = mapped.get(field)
            if idx is None or idx >= len(row_cells):
                continue
            r[field] = _normalize_field(field, row_cells[idx], headers[idx])

        # Keep only rows that can be bound to a concrete sample.
        if not _looks_sample_token(r["sample_id"]):
            continue
        non_empty_cond = sum(1 for k in ("pH", "T_K", "Te_min", "SLR_g_L", "Qmax") if r.get(k, "").strip())
        if non_empty_cond <= 0 and not r.get("pollutant_name", "").strip():
            continue
        out.append(r)

    # Dedupe
    dedup: List[Dict[str, str]] = []
    seen: Set[Tuple[str, ...]] = set()
    for r in out:
        key = tuple(r.get(k, "") for k in SHEET2_FIELDS if k != "filename")
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup
