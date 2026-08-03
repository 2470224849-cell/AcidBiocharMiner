#!/usr/bin/env python3
import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple


TOPIC_KEYWORDS = [
    "biochar",
    "activated carbon",
    "acid-modified",
    "acid modified",
    "acid activation",
    "acid treatment",
    "acid-treated",
    "hcl",
    "h2so4",
    "hno3",
    "phosphoric acid",
    "citric acid",
    "heavy metal",
    "metal ion",
    "pb(ii)",
    "cd(ii)",
    "cu(ii)",
    "zn(ii)",
    "ni(ii)",
    "cr(vi)",
    "cr(iii)",
    "as(iii)",
    "as(v)",
    "hg(ii)",
    "u(vi)",
    "cs(i)",
    "sr(ii)",
    "co(ii)",
    "i⁻",
    "io₃⁻",
    "tco₄⁻",
    "th(iv)",
    "eu(iii)",
    "la(iii)",
    "ce(iii)",
    "reo₄⁻",
    "uranium",
    "cesium",
    "caesium",
    "strontium",
    "cobalt",
    "iodide",
    "iodate",
    "pertechnetate",
    "technetium",
    "thorium",
    "europium",
    "lanthanum",
    "cerium",
    "perrhenate",
    "rhenium",
]

ACID_REAGENT_KEYWORDS = [
    "hcl",
    "h2so4",
    "hno3",
    "h3po4",
    "hydrochloric acid",
    "sulfuric acid",
    "nitric acid",
    "phosphoric acid",
    "citric acid",
    "oxalic acid",
    "acetic acid",
]

ACID_MOD_KEYWORDS = [
    "acid-modified",
    "acid modified",
    "acid activation",
    "acid treatment",
    "acid-treated",
    "acidified",
]

BIOCHAR_PREP_KEYWORDS = [
    "biochar",
    "pyrolysis",
    "feedstock",
    "biomass",
    "activation",
]

ACID_CONTEXT_RULES = {
    "acid_mod_phrase": r"\bacid[- ]?(?:modified|treated|activation|activated|treatment|functionalized|functionalised)\b",
    "reagent_near_modify": (
        r"(?:hcl|h2so4|hno3|h3po4|hydrochloric acid|sulfuric acid|nitric acid|"
        r"phosphoric acid|citric acid|oxalic acid|acetic acid)"
        r"[^.]{0,100}(?:treat|activat|modif|wash|impregnat|functional|oxid)"
    ),
    "modify_near_reagent": (
        r"(?:treat|activat|modif|wash|impregnat|functional|oxid)"
        r"[^.]{0,100}(?:hcl|h2so4|hno3|h3po4|hydrochloric acid|sulfuric acid|"
        r"nitric acid|phosphoric acid|citric acid|oxalic acid|acetic acid)"
    ),
    "biochar_near_reagent": (
        r"(?:biochar)[^.]{0,120}(?:hcl|h2so4|hno3|h3po4|hydrochloric acid|sulfuric acid|"
        r"nitric acid|phosphoric acid|citric acid|oxalic acid|acetic acid)|"
        r"(?:hcl|h2so4|hno3|h3po4|hydrochloric acid|sulfuric acid|nitric acid|"
        r"phosphoric acid|citric acid|oxalic acid|acetic acid)[^.]{0,120}(?:biochar)"
    ),
}

ACID_REAGENT_PATTERN = re.compile(
    r"\b(?:hcl|h2so4|hno3|h3po4|hydrochloric acid|sulfuric acid|nitric acid|"
    r"phosphoric acid|citric acid|oxalic acid|acetic acid)\b",
    flags=re.IGNORECASE,
)

BIOCHAR_PATTERN = re.compile(r"\bbiochar\b", flags=re.IGNORECASE)

PREP_VERB_PATTERN = re.compile(
    r"\b(?:pyroly[sz]\w*|carboni[sz]\w*|activat\w*|modif\w*|treat\w*|"
    r"impregnat\w*|functional\w*|oxid\w*|wash\w*)\b",
    flags=re.IGNORECASE,
)

PREPARATION_CUE_PATTERN = re.compile(
    r"\b(?:prepar\w*|synthesi[sz]\w*|produc\w*|obtain\w*|fabricat\w*|"
    r"impregnat\w*|soak\w*|treated?\s+with|activation\s+was\s+carried\s+out|"
    r"chemical activation|acid treatment)\b",
    flags=re.IGNORECASE,
)

PH_ADJUST_PATTERN = re.compile(
    r"\b(?:pH\s*(?:was|were)?\s*(?:adjusted|adjustment)|adjust(?:ed)?\s*pH|"
    r"using\s+(?:naoh|hcl)\s*(?:and|/)\s*(?:naoh|hcl))\b",
    flags=re.IGNORECASE,
)

NON_MODIFICATION_CONTEXT_PATTERN = re.compile(
    r"\b(?:desorb\w*|desorption|regenerat\w*|elut\w*|titrat\w*|"
    r"adsorbed|adsorption isotherm|isotherm|kinetic|equilibrium)\b",
    flags=re.IGNORECASE,
)

ACID_CONC_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:m|mol/?l|mmol/?l|%|wt%|v/v|w/v)\b",
    flags=re.IGNORECASE,
)

ACID_TIME_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours|min|mins|minute|minutes)\b",
    flags=re.IGNORECASE,
)

ACID_TEMP_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:°\s*c|º\s*c|degrees?\s*c|celsius)\b",
    flags=re.IGNORECASE,
)

METHOD_KEYWORDS = [
    "materials and methods",
    "experimental",
    "preparation",
    "pyrolysis",
    "activation",
    "acidification",
    "adsorbent",
]

DATA_KEYWORDS = [
    "table",
    "langmuir",
    "freundlich",
    "kinetic",
    "pseudo-second-order",
    "surface area",
    "bet",
    "pore volume",
    "pH",
    "c0",
    "qe",
    "mg/g",
    "mg l",
    "mmol/l",
]

HEAVY_METAL_KEYWORDS = [
    "heavy metal",
    "metal ion",
    "pb(ii)",
    "cd(ii)",
    "cu(ii)",
    "zn(ii)",
    "ni(ii)",
    "co(ii)",
    "cr(vi)",
    "cr(iii)",
    "as(iii)",
    "as(v)",
    "hg(ii)",
    "u(vi)",
    "lead",
    "cadmium",
    "copper",
    "zinc",
    "nickel",
    "cobalt",
    "chromium",
    "arsenic",
    "mercury",
    "uranium",
]

RADIONUCLIDE_KEYWORDS = [
    "u(vi)",
    "u(ⅵ)",
    "uranium",
    "cs(i)",
    "cs(ⅰ)",
    "cesium",
    "caesium",
    "sr(ii)",
    "sr(ⅱ)",
    "strontium",
    "co(ii)",
    "co(ⅱ)",
    "cobalt",
    "i⁻",
    "i-",
    "iodide",
    "io3-",
    "io3⁻",
    "io₃-",
    "io₃⁻",
    "iodate",
    "tco4-",
    "tco4⁻",
    "tco₄-",
    "tco₄⁻",
    "pertechnetate",
    "technetium",
    "th(iv)",
    "th(ⅳ)",
    "thorium",
    "eu(iii)",
    "eu(ⅲ)",
    "europium",
    "la(iii)",
    "la(ⅲ)",
    "lanthanum",
    "ce(iii)",
    "ce(ⅲ)",
    "cerium",
    "reo4-",
    "reo4⁻",
    "reo₄-",
    "reo₄⁻",
    "perrhenate",
    "rhenium",
]

NON_HEAVY_POLLUTANT_KEYWORDS = [
    "methylene blue",
    "rhodamine",
    "crystal violet",
    "malachite green",
    "ciprofloxacin",
    "tetracycline",
    "diclofenac",
    "phenol",
    "bisphenol",
    "pesticide",
    "phosphate",
    "nitrate",
    "ammonia",
]

COMPOSITE_DOMINANT_KEYWORDS = [
    "metal-organic framework",
    "mof",
    "composite",
    "nanocomposite",
    "nanoparticle",
    "ldh",
    "graphene",
    "carbon nanotube",
    "fe3o4",
    "magnetite",
]

REVIEW_KEYWORDS = [
    "review",
    "mini-review",
    "perspective",
    "outlook",
    "bibliometric",
    "state-of-the-art",
]

CHARACTERIZATION_DATA_KEYWORDS = [
    "bet",
    "surface area",
    "pore volume",
    "pore size",
    "aps",
    "tpv",
    "ph_pzc",
    "pzc",
    "elemental composition",
    "c/o",
    "o/c",
    "h/c",
]

ADS_CONDITION_KEYWORDS = [
    "c0",
    "initial concentration",
    "solution ph",
    "temperature",
    "contact time",
    "dosage",
    "slr",
]

ADS_PERFORMANCE_KEYWORDS = [
    "qe",
    "qmax",
    "langmuir",
    "freundlich",
    "pseudo-second-order",
    "pseudo first order",
    "kinetics",
]

UNIT_PATTERN = re.compile(
    r"\b("
    r"mg/g|g/l|mg/l|mmol/l|mmol/g|m2/g|cm3/g|nm|k|°c|ph|wt%|%"
    r")\b",
    flags=re.IGNORECASE,
)

TABLE_PATTERN = re.compile(r"\btable\s*\d+\b", flags=re.IGNORECASE)


@dataclass
class ScreenResult:
    profile: str
    path: str
    status: str
    score_total: int
    score_topic: int
    score_method: int
    score_data: int
    pages: int
    text_chars: int
    chars_per_page: float
    unit_hits: int
    table_hits: int
    scanned_suspect: bool
    matched_topic_keywords: List[str]
    matched_acid_reagent_keywords: List[str]
    matched_acid_mod_keywords: List[str]
    matched_biochar_prep_keywords: List[str]
    matched_acid_context_rules: List[str]
    acid_prep_sentence_hits: int
    acid_recipe_sentence_hits: int
    acid_recipe_window_hits: int
    acid_condition_hits: int
    ph_adjustment_sentence_hits: int
    matched_method_keywords: List[str]
    matched_data_keywords: List[str]
    matched_heavy_metal_keywords: List[str]
    matched_radionuclide_keywords: List[str]
    matched_non_heavy_pollutant_keywords: List[str]
    matched_composite_keywords: List[str]
    matched_review_keywords: List[str]
    matched_characterization_keywords: List[str]
    matched_ads_condition_keywords: List[str]
    matched_ads_performance_keywords: List[str]
    reason: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Screen PDF papers for extractability before running structured extraction."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="PDF file path or directory containing PDFs.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Max pages to read from each PDF for screening.",
    )
    parser.add_argument(
        "--out-json",
        default=None,
        help="Optional output JSON file for screening results.",
    )
    parser.add_argument(
        "--pdf-glob",
        default="*.pdf",
        help="Glob pattern for PDFs when --input is a directory (default: *.pdf).",
    )
    parser.add_argument(
        "--profile",
        choices=[
            "legacy",
            "acid-biochar-strict",
            "acid-biochar-radionuclide",
            "acid-biochar-radionuclide-loose",
        ],
        default="acid-biochar-strict",
        help=(
            "Screening profile. "
            "`acid-biochar-strict` requires explicit acid-modification evidence. "
            "`acid-biochar-radionuclide` keeps the same acid-biochar requirement "
            "but restricts pollutants to radionuclide/analog targets. "
            "`acid-biochar-radionuclide-loose` keeps biochar/radionuclide hard "
            "requirements but downgrades incomplete acid-recipe evidence to MAYBE."
        ),
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def strip_references_tail(text: str) -> str:
    """Drop references section to reduce false positives from citation titles."""
    if not text:
        return text
    lower = text.lower()
    # Only trim when the marker appears in the latter part of the document.
    for marker in (r"\breferences\b", r"\breference\b"):
        m = re.search(marker, lower)
        if m and m.start() > len(lower) * 0.4:
            return text[: m.start()]
    return text


RADIONUCLIDE_PATTERNS = [
    ("U(VI)", r"(?<![a-z0-9])u\s*\(\s*(?:vi|ⅵ|6)\s*\)"),
    ("uranium", r"\buranium\b"),
    ("Cs(I)", r"(?<![a-z0-9])cs\s*\(\s*(?:i|ⅰ|1)\s*\)"),
    ("cesium", r"\b(?:cesium|caesium)\b"),
    ("Sr(II)", r"(?<![a-z0-9])sr\s*\(\s*(?:ii|ⅱ|2)\s*\)"),
    ("strontium", r"\bstrontium\b"),
    ("Co(II)", r"(?<![a-z0-9])co\s*\(\s*(?:ii|ⅱ|2)\s*\)"),
    ("cobalt", r"\bcobalt\b"),
    ("I-/I⁻", r"(?<![a-z0-9])i\s*(?:-|−|–|—|⁻)(?![a-z0-9])"),
    ("iodide", r"\biodide\b"),
    ("IO3-/IO₃⁻", r"(?<![a-z0-9])io\s*(?:3|₃)\s*(?:-|−|–|—|⁻)?(?![a-z0-9])"),
    ("iodate", r"\biodate\b"),
    ("TcO4-/TcO₄⁻", r"(?<![a-z0-9])tc\s*o\s*(?:4|₄)\s*(?:-|−|–|—|⁻)?(?![a-z0-9])"),
    ("pertechnetate", r"\bpertechnetate\b"),
    ("technetium", r"\btechnetium\b"),
    ("Th(IV)", r"(?<![a-z0-9])th\s*\(\s*(?:iv|ⅳ|4)\s*\)"),
    ("thorium", r"\bthorium\b"),
    ("Eu(III)", r"(?<![a-z0-9])eu\s*\(\s*(?:iii|ⅲ|3)\s*\)"),
    ("europium", r"\beuropium\b"),
    ("La(III)", r"(?<![a-z0-9])la\s*\(\s*(?:iii|ⅲ|3)\s*\)"),
    ("lanthanum", r"\blanthanum\b"),
    ("Ce(III)", r"(?<![a-z0-9])ce\s*\(\s*(?:iii|ⅲ|3)\s*\)"),
    ("cerium", r"\bcerium\b"),
    ("ReO4-/ReO₄⁻", r"(?<![a-z0-9])re\s*o\s*(?:4|₄)\s*(?:-|−|–|—|⁻)?(?![a-z0-9])"),
    ("perrhenate", r"\bperrhenate\b"),
    ("rhenium", r"\brhenium\b"),
]

RADIONUCLIDE_TARGET_CONTEXT_PATTERN = re.compile(
    r"\b(?:adsorpt\w*|sorpt\w*|biosorpt\w*|remov\w*|uptake|captur\w*|"
    r"extract\w*|recover\w*|decontaminat\w*|separat\w*|immobili[sz]\w*|"
    r"retention|eliminat\w*|bind(?:ing)?|wastewater|aqueous\s+solution|"
    r"contaminat\w*|pollut\w*|ion(?:s)?)\b",
    flags=re.IGNORECASE,
)


def keyword_hits(text: str, keywords: List[str]) -> List[str]:
    hits = []
    for kw in keywords:
        if kw.lower() in text:
            hits.append(kw)
    return hits


def regex_keyword_hits(text: str, patterns: List[Tuple[str, str]]) -> List[str]:
    hits = []
    for label, pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(label)
    return hits


def radionuclide_target_hits(sentences: List[str]) -> List[str]:
    hits = []
    seen = set()
    for sentence in sentences:
        if not RADIONUCLIDE_TARGET_CONTEXT_PATTERN.search(sentence):
            continue
        for label, pattern in RADIONUCLIDE_PATTERNS:
            if label in seen:
                continue
            if re.search(pattern, sentence, flags=re.IGNORECASE):
                hits.append(label)
                seen.add(label)
    return hits


def split_sentences(text: str) -> List[str]:
    if not text:
        return []
    raw = re.split(r"(?<=[\.\!\?])\s+|\n+", text)
    return [s.strip() for s in raw if s and s.strip()]


def sentence_has_acid_prep_context(sentence: str) -> bool:
    if not sentence:
        return False
    has_reagent = bool(ACID_REAGENT_PATTERN.search(sentence))
    has_biochar = bool(BIOCHAR_PATTERN.search(sentence))
    has_prep_verb = bool(PREP_VERB_PATTERN.search(sentence))
    has_prep_cue = bool(PREPARATION_CUE_PATTERN.search(sentence))
    is_ph_adjust = bool(PH_ADJUST_PATTERN.search(sentence))
    is_non_modification = bool(NON_MODIFICATION_CONTEXT_PATTERN.search(sentence))
    return (
        has_reagent
        and (has_biochar or has_prep_verb)
        and has_prep_cue
        and not is_ph_adjust
        and not is_non_modification
    )


def sentence_has_acid_condition(sentence: str) -> bool:
    if not sentence:
        return False
    if not ACID_REAGENT_PATTERN.search(sentence):
        return False
    if PH_ADJUST_PATTERN.search(sentence):
        return False
    if NON_MODIFICATION_CONTEXT_PATTERN.search(sentence):
        return False
    return bool(
        ACID_CONC_PATTERN.search(sentence)
        or ACID_TIME_PATTERN.search(sentence)
        or ACID_TEMP_PATTERN.search(sentence)
    )


def count_acid_recipe_window_hits(sentences: List[str]) -> int:
    if not sentences:
        return 0
    hits = 0
    for i, sent in enumerate(sentences):
        prep_i = sentence_has_acid_prep_context(sent)
        cond_i = sentence_has_acid_condition(sent)
        if prep_i and cond_i:
            hits += 1
            continue
        if i + 1 >= len(sentences):
            continue
        sent_n = sentences[i + 1]
        prep_n = sentence_has_acid_prep_context(sent_n)
        cond_n = sentence_has_acid_condition(sent_n)
        if (prep_i and cond_n) or (cond_i and prep_n):
            hits += 1
    return hits


def decide_status(
    profile: str,
    topic_score: int,
    method_score: int,
    data_score: int,
    unit_hits: int,
    scanned_suspect: bool,
    acid_reagent_hits: int,
    acid_mod_hits: int,
    acid_context_hits: int,
    biochar_prep_hits: int,
    acid_prep_sentence_hits: int,
    acid_recipe_sentence_hits: int,
    acid_recipe_window_hits: int,
    acid_condition_hits: int,
    ph_adjustment_sentence_hits: int,
    biochar_word_hits: int,
    heavy_metal_hits: int,
    radionuclide_hits: int,
    non_heavy_pollutant_hits: int,
    composite_hits: int,
    review_hits: int,
    characterization_hits: int,
    ads_condition_hits: int,
    ads_performance_hits: int,
) -> Tuple[str, str]:
    if scanned_suspect:
        return "FAIL", "Likely scanned PDF or low selectable text; OCR needed first."

    if profile in {
        "acid-biochar-strict",
        "acid-biochar-radionuclide",
        "acid-biochar-radionuclide-loose",
    }:
        # Strict mode: must be true acid-modified biochar preparation evidence.
        # Hard constraints to avoid non-acid-modified papers.
        if review_hits > 0 and method_score <= 2:
            return "FAIL", "Review/conceptual article likely; lacks primary experimental focus."
        if topic_score == 0 or biochar_prep_hits == 0:
            return "FAIL", "No clear biochar preparation context."
        is_radionuclide_profile = profile in {
            "acid-biochar-radionuclide",
            "acid-biochar-radionuclide-loose",
        }
        is_loose_radionuclide_profile = profile == "acid-biochar-radionuclide-loose"
        if is_radionuclide_profile and biochar_word_hits == 0:
            return "FAIL", "No explicit biochar evidence."
        if is_radionuclide_profile:
            if radionuclide_hits == 0:
                return (
                    "FAIL",
                    "No clear radionuclide/analog pollutant evidence "
                    "(U(VI), Cs(I), Sr(II), Co(II), I-/IO3-, TcO4-, Th(IV), "
                    "Eu(III), La(III), Ce(III), ReO4-).",
                )
        if acid_reagent_hits == 0:
            if is_loose_radionuclide_profile and acid_mod_hits > 0:
                return (
                    "MAYBE",
                    "Acid-modified biochar wording found, but no explicit acid reagent was extracted.",
                )
            return "FAIL", "No acid reagent evidence."
        else:
            if heavy_metal_hits == 0:
                return "FAIL", "No clear heavy-metal pollutant evidence."
            if non_heavy_pollutant_hits >= 2 and heavy_metal_hits == 0:
                return "FAIL", "Pollutant focus is likely non-heavy-metal."
        if acid_prep_sentence_hits == 0:
            if is_loose_radionuclide_profile and (acid_mod_hits > 0 or acid_context_hits > 0):
                return (
                    "MAYBE",
                    "Has acid-modified biochar + radionuclide signals, but acid-preparation sentence was not extracted.",
                )
            return (
                "FAIL",
                "No acid-treatment sentence linking reagent with biochar/preparation context.",
            )
        if acid_recipe_window_hits == 0:
            if is_loose_radionuclide_profile:
                return (
                    "MAYBE",
                    "Has acid-biochar + radionuclide signals, but acid-treatment recipe evidence is incomplete.",
                )
            return (
                "FAIL",
                "No acid-treatment recipe evidence (prep context + concentration/time/temperature).",
            )
        if acid_condition_hits == 0:
            if is_loose_radionuclide_profile:
                return (
                    "MAYBE",
                    "Has acid-biochar + radionuclide signals, but explicit acid-treatment conditions were not extracted.",
                )
            return (
                "FAIL",
                "No explicit acid-treatment condition (concentration/time/temperature).",
            )
        if ph_adjustment_sentence_hits > 0 and acid_prep_sentence_hits <= 1 and acid_context_hits == 0:
            return "FAIL", "Acid usage appears to be only pH adjustment, not acid modification."
        if composite_hits >= 3 and acid_prep_sentence_hits == 0 and acid_recipe_window_hits == 0:
            return "FAIL", "Composite/other adsorbent appears dominant over acid-modified biochar."

        # Prefer complete, quantifiable datasets for downstream extraction.
        if characterization_hits == 0:
            return "FAIL", "Missing key adsorbent characterization signals (BET/pore/elemental)."
        if ads_condition_hits == 0:
            return "FAIL", "Missing adsorption experimental condition signals."
        if ads_performance_hits == 0:
            return "FAIL", "Missing adsorption performance/model signals (Qe/Qm/isotherm/kinetics)."

        if method_score >= 1 and (data_score >= 3 or unit_hits >= 6):
            if profile == "acid-biochar-radionuclide":
                return "PASS", "Matched strict acid-biochar + radionuclide criteria for structured extraction."
            if profile == "acid-biochar-radionuclide-loose":
                return "PASS", "Matched loose acid-biochar + radionuclide criteria for manual/structured extraction."
            return "PASS", "Matched strict acid-biochar criteria for structured extraction."
        if data_score >= 2 or unit_hits >= 4:
            if is_radionuclide_profile:
                return "MAYBE", "Has acid-biochar + radionuclide signals but structured data evidence is limited."
            return "MAYBE", "Has acid-biochar signals but structured data evidence is limited."
        if is_radionuclide_profile:
            return "FAIL", "Insufficient structured signals for strict acid-biochar + radionuclide extraction."
        return "FAIL", "Insufficient structured signals for strict acid-biochar extraction."

    if topic_score >= 3 and method_score >= 1 and (data_score >= 4 or unit_hits >= 8):
        return "PASS", "Strong topic/method/data signals for structured extraction."

    if topic_score >= 2 and (data_score >= 2 or unit_hits >= 4):
        return "MAYBE", "Partially matched; inspect manually before full extraction."

    return "FAIL", "Weak topic or insufficient extractable structured signals."


def extract_pdf_text(pdf_path: Path, max_pages: int) -> Tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency `pypdf`. Install with: "
            "python -m pip install pypdf"
        ) from exc

    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)
    n_pages = min(max_pages, total_pages)
    chunks = []
    for i in range(n_pages):
        page_text = reader.pages[i].extract_text() or ""
        chunks.append(page_text)
    return "\n".join(chunks), total_pages


def screen_one_pdf(pdf_path: Path, max_pages: int, profile: str) -> ScreenResult:
    text_raw, total_pages = extract_pdf_text(pdf_path, max_pages=max_pages)
    text_raw = strip_references_tail(text_raw)
    text_norm = normalize_text(text_raw)
    sentences = split_sentences(text_raw)

    topic = keyword_hits(text_norm, TOPIC_KEYWORDS)
    acid_reagent = keyword_hits(text_norm, ACID_REAGENT_KEYWORDS)
    acid_mod = keyword_hits(text_norm, ACID_MOD_KEYWORDS)
    biochar_prep = keyword_hits(text_norm, BIOCHAR_PREP_KEYWORDS)
    acid_context_rules = [
        name
        for name, pattern in ACID_CONTEXT_RULES.items()
        if re.search(pattern, text_norm, flags=re.IGNORECASE)
    ]
    method = keyword_hits(text_norm, METHOD_KEYWORDS)
    data = keyword_hits(text_norm, DATA_KEYWORDS)
    heavy_metal = keyword_hits(text_norm, HEAVY_METAL_KEYWORDS)
    radionuclide = radionuclide_target_hits(sentences)
    non_heavy_pollutant = keyword_hits(text_norm, NON_HEAVY_POLLUTANT_KEYWORDS)
    composite_kw = keyword_hits(text_norm, COMPOSITE_DOMINANT_KEYWORDS)
    review_kw = keyword_hits(text_norm, REVIEW_KEYWORDS)
    characterization_kw = keyword_hits(text_norm, CHARACTERIZATION_DATA_KEYWORDS)
    ads_condition_kw = keyword_hits(text_norm, ADS_CONDITION_KEYWORDS)
    ads_performance_kw = keyword_hits(text_norm, ADS_PERFORMANCE_KEYWORDS)

    acid_prep_sentence_hits = sum(1 for s in sentences if sentence_has_acid_prep_context(s))
    acid_condition_hits = sum(1 for s in sentences if sentence_has_acid_condition(s))
    acid_recipe_sentence_hits = sum(
        1 for s in sentences if sentence_has_acid_prep_context(s) and sentence_has_acid_condition(s)
    )
    acid_recipe_window_hits = count_acid_recipe_window_hits(sentences)
    ph_adjustment_sentence_hits = sum(1 for s in sentences if PH_ADJUST_PATTERN.search(s))
    biochar_word_hits = 1 if BIOCHAR_PATTERN.search(text_norm) else 0

    unit_hits = len(UNIT_PATTERN.findall(text_norm))
    table_hits = len(TABLE_PATTERN.findall(text_norm))
    text_chars = len(text_norm)
    chars_per_page = (text_chars / max(total_pages, 1)) if total_pages else 0.0
    scanned_suspect = text_chars < 3000 or chars_per_page < 200

    topic_score = len(topic)
    method_score = len(method)
    data_score = len(data) + min(table_hits, 5)
    total_score = topic_score * 4 + method_score * 2 + data_score

    status, reason = decide_status(
        profile=profile,
        topic_score=topic_score,
        method_score=method_score,
        data_score=data_score,
        unit_hits=unit_hits,
        scanned_suspect=scanned_suspect,
        acid_reagent_hits=len(acid_reagent),
        acid_mod_hits=len(acid_mod),
        acid_context_hits=len(acid_context_rules),
        biochar_prep_hits=len(biochar_prep),
        acid_prep_sentence_hits=acid_prep_sentence_hits,
        acid_recipe_sentence_hits=acid_recipe_sentence_hits,
        acid_recipe_window_hits=acid_recipe_window_hits,
        acid_condition_hits=acid_condition_hits,
        ph_adjustment_sentence_hits=ph_adjustment_sentence_hits,
        biochar_word_hits=biochar_word_hits,
        heavy_metal_hits=len(heavy_metal),
        radionuclide_hits=len(radionuclide),
        non_heavy_pollutant_hits=len(non_heavy_pollutant),
        composite_hits=len(composite_kw),
        review_hits=len(review_kw),
        characterization_hits=len(characterization_kw),
        ads_condition_hits=len(ads_condition_kw),
        ads_performance_hits=len(ads_performance_kw),
    )

    return ScreenResult(
        profile=profile,
        path=str(pdf_path),
        status=status,
        score_total=total_score,
        score_topic=topic_score,
        score_method=method_score,
        score_data=data_score,
        pages=total_pages,
        text_chars=text_chars,
        chars_per_page=round(chars_per_page, 1),
        unit_hits=unit_hits,
        table_hits=table_hits,
        scanned_suspect=scanned_suspect,
        matched_topic_keywords=topic,
        matched_acid_reagent_keywords=acid_reagent,
        matched_acid_mod_keywords=acid_mod,
        matched_biochar_prep_keywords=biochar_prep,
        matched_acid_context_rules=acid_context_rules,
        acid_prep_sentence_hits=acid_prep_sentence_hits,
        acid_recipe_sentence_hits=acid_recipe_sentence_hits,
        acid_recipe_window_hits=acid_recipe_window_hits,
        acid_condition_hits=acid_condition_hits,
        ph_adjustment_sentence_hits=ph_adjustment_sentence_hits,
        matched_method_keywords=method,
        matched_data_keywords=data,
        matched_heavy_metal_keywords=heavy_metal,
        matched_radionuclide_keywords=radionuclide,
        matched_non_heavy_pollutant_keywords=non_heavy_pollutant,
        matched_composite_keywords=composite_kw,
        matched_review_keywords=review_kw,
        matched_characterization_keywords=characterization_kw,
        matched_ads_condition_keywords=ads_condition_kw,
        matched_ads_performance_keywords=ads_performance_kw,
        reason=reason,
    )


def find_pdf_files(input_path: Path, pdf_glob: str = "*.pdf") -> List[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"Input file is not a PDF: {input_path}")
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob(pdf_glob))
    raise FileNotFoundError(f"Input path not found: {input_path}")


def print_summary(results: List[ScreenResult]) -> None:
    print("=== PDF Screening Summary ===")
    if not results:
        print("No PDF files found.")
        return
    for r in results:
        print(
            f"[{r.status}] profile={r.profile} score={r.score_total:>3} "
            f"topic={r.score_topic} method={r.score_method} data={r.score_data} "
            f"units={r.unit_hits} pages={r.pages} :: {r.path}"
        )
        if r.profile in {
            "acid-biochar-strict",
            "acid-biochar-radionuclide",
            "acid-biochar-radionuclide-loose",
        }:
            print(
                "  acid_evidence: "
                f"prep_sent={r.acid_prep_sentence_hits} "
                f"recipe_sent={r.acid_recipe_sentence_hits} "
                f"recipe_window={r.acid_recipe_window_hits} "
                f"condition_sent={r.acid_condition_hits} "
                f"ph_adjust_sent={r.ph_adjustment_sentence_hits}"
            )
            print(
                "  target_evidence: "
                f"heavy_metal={len(r.matched_heavy_metal_keywords)} "
                f"radionuclide={len(r.matched_radionuclide_keywords)} "
                f"non_heavy={len(r.matched_non_heavy_pollutant_keywords)} "
                f"composite={len(r.matched_composite_keywords)} "
                f"review={len(r.matched_review_keywords)} "
                f"char={len(r.matched_characterization_keywords)} "
                f"ads_cond={len(r.matched_ads_condition_keywords)} "
                f"ads_perf={len(r.matched_ads_performance_keywords)}"
            )
        print(f"  reason: {r.reason}")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser()

    try:
        pdf_files = find_pdf_files(input_path, pdf_glob=args.pdf_glob)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    results: List[ScreenResult] = []
    for pdf in pdf_files:
        try:
            result = screen_one_pdf(pdf, max_pages=args.max_pages, profile=args.profile)
            results.append(result)
        except Exception as exc:
            results.append(
                ScreenResult(
                    profile=args.profile,
                    path=str(pdf),
                    status="FAIL",
                    score_total=0,
                    score_topic=0,
                    score_method=0,
                    score_data=0,
                    pages=0,
                    text_chars=0,
                    chars_per_page=0.0,
                    unit_hits=0,
                    table_hits=0,
                    scanned_suspect=True,
                    matched_topic_keywords=[],
                    matched_acid_reagent_keywords=[],
                    matched_acid_mod_keywords=[],
                    matched_biochar_prep_keywords=[],
                    matched_acid_context_rules=[],
                    acid_prep_sentence_hits=0,
                    acid_recipe_sentence_hits=0,
                    acid_recipe_window_hits=0,
                    acid_condition_hits=0,
                    ph_adjustment_sentence_hits=0,
                    matched_method_keywords=[],
                    matched_data_keywords=[],
                    matched_heavy_metal_keywords=[],
                    matched_radionuclide_keywords=[],
                    matched_non_heavy_pollutant_keywords=[],
                    matched_composite_keywords=[],
                    matched_review_keywords=[],
                    matched_characterization_keywords=[],
                    matched_ads_condition_keywords=[],
                    matched_ads_performance_keywords=[],
                    reason=f"Cannot parse PDF: {exc}",
                )
            )

    print_summary(results)

    if args.out_json:
        out = Path(args.out_json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)
        print(f"Saved JSON to: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
