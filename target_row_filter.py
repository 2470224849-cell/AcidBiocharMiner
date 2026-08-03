#!/usr/bin/env python3
import os
import re
from typing import Dict, List, Optional, Tuple


ACID_KEYWORDS = [
    "acid",
    "hcl",
    "hno3",
    "h2so4",
    "h3po4",
    "hydrochloric",
    "nitric",
    "sulfuric",
    "sulphuric",
    "phosphoric",
    "citric",
    "oxalic",
    "acetic",
    "formic",
    "tartaric",
    "maleic",
    "lactic",
]

NON_ACID_MOD_KEYWORDS = [
    "naoh",
    "koh",
    "alkali",
    "alkaline",
    "base-modified",
    "kmno4",
    "permanganate",
    "ferric",
    "fecl3",
    "metal-loaded",
    "loaded",
    "doped",
    "doping",
    "magnetic",
    "nzvi",
    "composite",
    "biochar/",
]

# Base-post-treatment cues that should NOT be hard-excluded by themselves.
# Typical in acid-route papers: acid treatment followed by Na2CO3 neutralization.
SOFT_POST_TREATMENT_KEYWORDS = [
    "na2co3",
    "neutralization",
    "neutralisation",
    "base wash",
]

# Hard-exclude routes for this project even if acid appears in process text.
# Example: amination-focused samples (such as APBC) should not be kept.
HARD_EXCLUDE_MOD_KEYWORDS = [
    "amin",
    "amine",
    "aminated",
    "amination",
    "pei",
    "edta",
]

PRISTINE_KEYWORDS = [
    "pristine",
    "raw biochar",
    "raw bc",
    "unmodified",
    "original biochar",
    "pristine biochar",
]

# Group-label sample IDs that should be dropped rather than treated as
# concrete materials (e.g., SCRH-S-m-T / SCRH-W-m-T in one paper).
BLOCKLIST_SAMPLE_IDS = {
    "scrhsmt",
    "scrhwmt",
}

# Project-specific override requested by user:
# - drop APBC from target set (amination route).
FORCE_DROP_SAMPLE_IDS = {
    "apbc",
}

# Common adsorption/isotherm/kinetic parameter labels that are sometimes
# mis-extracted as sample_id from model-fitting tables. These are not
# concrete materials and should be dropped before sheet1 export.
PSEUDO_SAMPLE_ID_EXACT = {
    "qmax",
    "kl",
    "kf",
    "ks",
    "krp",
    "qmfs",
    "kfs",
    "nfs",
    "r2",
}


def _norm_text(*parts: str) -> str:
    text = " ".join(str(x or "") for x in parts).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _norm_sid(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


def _looks_reference_sample_id(sample_id: str) -> bool:
    s = str(sample_id or "").strip()
    if not s:
        return False
    sl = s.lower()
    # Typical literature-reference pattern in comparative tables:
    # "Hydrochar (Wang et al., 2010)", "BC0c* (Wang et al., 2017)", etc.
    if "et al" in sl and re.search(r"\b(19|20)\d{2}\b", sl):
        return True
    return False


def _looks_pseudo_sample_id(sample_id: str) -> bool:
    s = str(sample_id or "").strip().lower()
    sid = _norm_sid(sample_id)
    if not s:
        return False
    if sid in PSEUDO_SAMPLE_ID_EXACT:
        return True

    compact = re.sub(r"\s+", " ", s)
    # Typical model-parameter labels seen in adsorption tables.
    if compact in {
        "q max",
        "k l",
        "r 2",
        "k f",
        "k rp",
        "α rp",
        "a rp",
        "k s",
        "β s",
        "b s",
        "a s",
        "b t",
        "n t",
        "q mfs",
        "k fs",
        "n fs",
        "n",
    }:
        return True

    if re.fullmatch(
        r"(q\s*max|qmax|k\s*l|k\s*f|k\s*rp|k\s*s|q\s*mfs|k\s*fs|n\s*fs|r\s*2|r2|n|a\s*s|b\s*s|b\s*t|n\s*t)",
        compact,
    ):
        return True
    return False


def _canonical_file_key(filename: str) -> str:
    base = os.path.basename(str(filename or "")).strip().lower()
    if not base:
        return ""
    base = re.sub(r"\.[a-z0-9]{1,6}$", "", base)
    base = base.replace("_", " ")
    base = re.sub(r"\s+", " ", base).strip()
    # Repeatedly strip common suffix markers so main and SI filenames can share one key.
    suffix_patterns = [
        r"(?:^|[\s\-])main$",
        r"(?:^|[\s\-])mmc\d*$",
        r"(?:^|[\s\-])si\d*$",
        r"(?:^|[\s\-])supp(?:lement|lementary)?$",
        r"(?:^|[\s\-])supporting(?:\s+information)?$",
        r"(?:^|[\s\-])supp\s*info$",
        r"(?:^|[\s\-])appendix$",
        r"(?:^|[\s\-])esm$",
        r"(?:^|[\s\-])moesm$",
        r"(?:^|[\s\-])sm$",
    ]
    prev = None
    while base and prev != base:
        prev = base
        base = base.strip(" -_()[]")
        for pat in suffix_patterns:
            base = re.sub(pat, "", base, flags=re.I).strip(" -_()[]")
        base = re.sub(r"\s+", " ", base).strip()
    return base


def _split_tokens(s: str) -> List[str]:
    return [x for x in re.split(r"[^a-z0-9]+", str(s or "").lower()) if x]


def _score_sid_match(a: str, b: str) -> float:
    a_norm = _norm_sid(a)
    b_norm = _norm_sid(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    if a_norm in b_norm or b_norm in a_norm:
        short = min(len(a_norm), len(b_norm))
        long = max(len(a_norm), len(b_norm))
        return max(0.65, short / long)

    at = set(_split_tokens(a))
    bt = set(_split_tokens(b))
    if at and bt:
        inter = len(at & bt)
        uni = len(at | bt)
        if uni > 0:
            jacc = inter / uni
            if jacc > 0:
                return jacc
    return 0.0


def _infer_from_file_context(
    file_key: str,
    sample_id: str,
    file_sid_cls: Dict[str, Dict[str, str]],
) -> Optional[str]:
    keep_classes = {"acid", "pristine"}
    sid_norm = _norm_sid(sample_id)
    cls_map = file_sid_cls.get(file_key, {})
    if not cls_map:
        return None

    # Direct hit in current file map.
    if sid_norm and sid_norm in cls_map and cls_map[sid_norm] in keep_classes:
        return cls_map[sid_norm]

    # Fuzzy match against current file sample ids.
    best_cls = None
    best_score = 0.0
    for known_sid, known_cls in cls_map.items():
        if known_cls not in keep_classes:
            continue
        score = _score_sid_match(sid_norm, known_sid)
        if score > best_score:
            best_score = score
            best_cls = known_cls
    if best_cls and best_score >= 0.30:
        return best_cls

    # Baseline heuristic: "MB" with "HMB/NaMB/FeMB", "BC" with "OPBC/APBC", etc.
    if sid_norm:
        with_suffix = [k for k in cls_map.keys() if k.endswith(sid_norm) and k != sid_norm]
        if with_suffix:
            return "pristine"

    # Empty sid rows can inherit when file is consistently one class.
    if not sid_norm:
        non_unknown = {v for v in cls_map.values() if v in keep_classes}
        if len(non_unknown) == 1:
            return list(non_unknown)[0]

    return None


def _infer_acid_by_family(
    sample_id: str,
    file_key: str,
    sample_cls_file: Dict[str, Dict[str, str]],
) -> Optional[str]:
    """
    Project rule:
    keep N*-family samples (e.g., NSC/NDC/NHC) when their base family
    sample (SC/DC/HC) in the same paper is acid/pristine target.
    """
    sid = _norm_sid(sample_id)
    if not sid or not file_key:
        return None
    cls_map = sample_cls_file.get(file_key, {})
    if not cls_map:
        return None

    # N-prefix family inheritance (NSC -> SC, NDC -> DC, NHC -> HC, etc.).
    if sid.startswith("n") and len(sid) > 1:
        base = sid[1:]
        base_cls = cls_map.get(base, "")
        if base_cls in {"acid", "pristine"}:
            return "acid"

    return None


def classify_sample(
    sample_id: str = "",
    acid_type: str = "",
    modification_sequence: str = "",
) -> str:
    text = _norm_text(sample_id, acid_type, modification_sequence)
    sid = _norm_sid(sample_id)

    if not text and not sid:
        return "unknown"

    # Drop comparative/reference rows from other papers.
    if _looks_reference_sample_id(sample_id):
        return "other"
    # Drop model-parameter labels misread as sample ids.
    if _looks_pseudo_sample_id(sample_id):
        return "other"

    acid_hit = _contains_any(text, ACID_KEYWORDS)
    non_acid_hit = _contains_any(text, NON_ACID_MOD_KEYWORDS)
    soft_post_treat_hit = _contains_any(text, SOFT_POST_TREATMENT_KEYWORDS)
    hard_exclude_hit = _contains_any(text, HARD_EXCLUDE_MOD_KEYWORDS)
    pristine_hit = _contains_any(text, PRISTINE_KEYWORDS)

    # Common pristine sample ids.
    if sid in {"bc", "biochar", "rawbc", "rawbiochar", "pristinebc", "ubc"}:
        pristine_hit = True

    # Explicitly drop group-label IDs (not a concrete sample point).
    if sid in BLOCKLIST_SAMPLE_IDS:
        return "other"
    if sid in FORCE_DROP_SAMPLE_IDS:
        return "other"

    # If an acid-agent field exists and it's not explicitly non-acid, keep it as acid evidence.
    acid_field = _norm_text(acid_type)
    if acid_field and not non_acid_hit:
        acid_hit = True

    # Rule 1: amination-like routes are always non-target in this project.
    if hard_exclude_hit:
        return "other"
    # Rule 2: acid participation is target-positive (e.g., NHC/NSC style routes),
    # even if neutralization/base post-treatment appears.
    if acid_hit:
        return "acid"
    # Rule 3: Na2CO3/neutralization alone is not enough to mark non-target.
    # Keep it as unknown and let same-paper inheritance decide.
    if soft_post_treat_hit and not non_acid_hit:
        return "unknown"
    # Rule 4: non-acid routes without acid evidence are non-target.
    if non_acid_hit:
        return "other"
    if pristine_hit:
        return "pristine"

    # "modified/activated" without acid evidence is treated as other.
    if _contains_any(text, ["modified", "activation", "activated", "treated", "functionalized"]):
        return "other"

    return "unknown"


def _merge_cls(prev: str, new: str) -> str:
    order = {"acid": 4, "pristine": 3, "other": 2, "unknown": 1, "": 0}
    return new if order.get(new, 0) >= order.get(prev, 0) else prev


def filter_rows_keep_acid_pristine(
    bio_rows: List[Dict],
    ads_rows: List[Dict],
) -> Tuple[List[Dict], List[Dict], Dict]:
    sample_cls_global: Dict[str, str] = {}
    # canonical filename key -> normalized sample_id -> class
    sample_cls_file: Dict[str, Dict[str, str]] = {}

    # Build sample-id class map from biochar_modification rows first.
    for row in bio_rows:
        sid_raw = str(row.get("sample_id", "")).strip()
        sid = _norm_sid(sid_raw)
        filename = str(row.get("filename", "")).strip()
        file_key = _canonical_file_key(filename)
        cls = classify_sample(
            sample_id=sid_raw,
            acid_type=str(row.get("acid_type", "")),
            modification_sequence=str(row.get("modification_sequence", "")),
        )
        # Family inheritance for acid-related N* samples in the same paper.
        fam_cls = _infer_acid_by_family(
            sample_id=sid_raw, file_key=file_key, sample_cls_file=sample_cls_file
        )
        if fam_cls:
            cls = fam_cls
        if sid:
            sample_cls_global[sid] = _merge_cls(sample_cls_global.get(sid, ""), cls)
            if file_key not in sample_cls_file:
                sample_cls_file[file_key] = {}
            sample_cls_file[file_key][sid] = _merge_cls(
                sample_cls_file[file_key].get(sid, ""), cls
            )

    keep_classes = {"acid", "pristine"}

    # Second pass: stabilize family inheritance after file maps are populated.
    for file_key, cls_map in sample_cls_file.items():
        for sid, cls in list(cls_map.items()):
            if cls in keep_classes:
                continue
            fam_cls = _infer_acid_by_family(
                sample_id=sid, file_key=file_key, sample_cls_file=sample_cls_file
            )
            if fam_cls:
                cls_map[sid] = _merge_cls(cls_map.get(sid, ""), fam_cls)
                sample_cls_global[sid] = _merge_cls(
                    sample_cls_global.get(sid, ""), fam_cls
                )

    kept_bio: List[Dict] = []
    kept_ads: List[Dict] = []

    dropped_bio = 0
    dropped_ads = 0
    inferred_ads = 0

    for row in bio_rows:
        sid_raw = str(row.get("sample_id", "")).strip()
        sid = _norm_sid(sid_raw)
        filename = str(row.get("filename", "")).strip()
        file_key = _canonical_file_key(filename)
        row_cls = classify_sample(
            sample_id=sid_raw,
            acid_type=str(row.get("acid_type", "")),
            modification_sequence=str(row.get("modification_sequence", "")),
        )
        fam_cls = _infer_acid_by_family(
            sample_id=sid_raw, file_key=file_key, sample_cls_file=sample_cls_file
        )
        if fam_cls:
            row_cls = fam_cls
        if sid and file_key in sample_cls_file and sid in sample_cls_file[file_key]:
            row_cls = sample_cls_file[file_key][sid]
        elif sid and sid in sample_cls_global:
            row_cls = sample_cls_global[sid]

        if row_cls in keep_classes:
            kept_bio.append(row)
        else:
            dropped_bio += 1

    for row in ads_rows:
        sid_raw = str(row.get("sample_id", "")).strip()
        sid = _norm_sid(sid_raw)
        filename = str(row.get("filename", "")).strip()
        file_key = _canonical_file_key(filename)

        if sid and file_key in sample_cls_file and sid in sample_cls_file[file_key]:
            row_cls = sample_cls_file[file_key][sid]
        elif sid and sid in sample_cls_global:
            row_cls = sample_cls_global[sid]
        else:
            # Fall back to sample-id text when no biochar row mapping is available.
            row_cls = classify_sample(sample_id=sid_raw)
            inferred = _infer_from_file_context(
                file_key=file_key, sample_id=sid_raw, file_sid_cls=sample_cls_file
            )
            if inferred:
                row_cls = inferred
                inferred_ads += 1
        if row_cls not in keep_classes:
            fam_cls = _infer_acid_by_family(
                sample_id=sid_raw, file_key=file_key, sample_cls_file=sample_cls_file
            )
            if fam_cls:
                row_cls = fam_cls

        if row_cls in keep_classes:
            kept_ads.append(row)
        else:
            dropped_ads += 1

    stats = {
        "bio_before": len(bio_rows),
        "bio_after": len(kept_bio),
        "bio_dropped": dropped_bio,
        "ads_before": len(ads_rows),
        "ads_after": len(kept_ads),
        "ads_dropped": dropped_ads,
        "ads_inferred_from_file_context": inferred_ads,
        "sample_id_classified_global": len(sample_cls_global),
        "sample_id_classified_files": sum(len(v) for v in sample_cls_file.values()),
    }
    return kept_bio, kept_ads, stats
