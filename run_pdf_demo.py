#!/usr/bin/env python3
import argparse
import json
import re
import sys
import traceback
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from langchain_core._api.deprecation import LangChainDeprecationWarning
except Exception:
    LangChainDeprecationWarning = None

warnings.filterwarnings("ignore", message=r".*urllib3 v2 only supports OpenSSL.*")
warnings.filterwarnings("ignore", message=r".*To install langchain-community.*")
warnings.filterwarnings("ignore", message=r".*was deprecated in LangChain.*")
warnings.filterwarnings("ignore", message=r".*was deprecated in langchain.*")
if LangChainDeprecationWarning is not None:
    warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)

from pypdf import PdfReader

from llm_miner import LLMMiner
from llm_miner.parser.base import Metadata
from llm_miner.reader import JournalReader
from llm_miner.schema import Elements, Paragraph
from direct_sheet1_parser import extract_sheet1_rows_from_markdown_table
from direct_sheet2_parser import extract_sheet2_rows_from_markdown_table

TARGET_KEYS = [
    "biochar modification",
    "biochar_modification",
    "adsorption experiment",
    "adsorption_experiment",
]


def canonical_key(key: str) -> str:
    key = (key or "").strip().lower()
    key = re.sub(r"[\s\-]+", "_", key)
    key = re.sub(r"_+", "_", key)
    return key


def key_matches_target(key: str, target: str) -> bool:
    ck = canonical_key(key)
    ct = canonical_key(target)
    if ck == ct:
        return True
    return bool(re.fullmatch(rf"{re.escape(ct)}_\d+", ck))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one-pass extraction from a PDF by converting pages into text chunks."
    )
    parser.add_argument("--pdf", required=True, help="Absolute path to one PDF file.")
    parser.add_argument("--config", default="config/config.yaml", help="YAML config path.")
    parser.add_argument("--api-key", default=None, help="API key override.")
    parser.add_argument("--max-pages", type=int, default=20, help="Pages to read from PDF.")
    parser.add_argument(
        "--pdf-parser",
        choices=["pypdf", "docling"],
        default="pypdf",
        help="PDF parser backend. Use docling for stronger layout-aware extraction.",
    )
    parser.add_argument(
        "--strict-docling",
        action="store_true",
        help="When --pdf-parser=docling, fail immediately on docling parse errors (no pypdf fallback).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1800,
        help="Approximate max characters per text chunk.",
    )
    parser.add_argument("--output-json", default=None, help="Path to save jr.result JSON.")
    parser.add_argument(
        "--raw-target-json",
        default=None,
        help="Path to save raw target rows found directly in intermediate outputs.",
    )
    parser.add_argument("--reader-json", default=None, help="Path to save full JournalReader JSON.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only parse PDF/chunk text and print diagnostics, without LLM calls.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(pdf_path: Path, max_pages: int) -> Tuple[str, int]:
    reader = PdfReader(str(pdf_path))
    n_pages = min(max_pages, len(reader.pages))
    chunks = []
    for idx in range(n_pages):
        page_text = reader.pages[idx].extract_text() or ""
        chunks.append(page_text)
    return "\n\n".join(chunks), len(reader.pages)


def estimate_total_pages(pdf_path: Path) -> int:
    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return 0


def _docling_document_to_text(document) -> str:
    for method_name in ("export_to_markdown", "export_to_text", "to_markdown", "to_text"):
        method = getattr(document, method_name, None)
        if callable(method):
            try:
                out = method()
            except Exception:
                continue
            if isinstance(out, str) and out.strip():
                return out

    for attr_name in ("markdown", "text", "content"):
        out = getattr(document, attr_name, None)
        if isinstance(out, str) and out.strip():
            return out

    return ""


def extract_pdf_text_docling(
    pdf_path: Path,
    max_pages: int,
    total_pages: int,
) -> Tuple[str, int, bool]:
    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:
        raise RuntimeError(
            "docling is not available in this Python environment. "
            'Install it in the same venv, e.g. `pip install "docling[mac_intel]"`.'
        ) from exc

    converter = DocumentConverter()
    converted = converter.convert(str(pdf_path))
    document = getattr(converted, "document", converted)
    text = _docling_document_to_text(document)
    if not text:
        raise RuntimeError("docling conversion succeeded but no text/markdown was exported.")

    truncated = False
    pages_read = total_pages if total_pages > 0 else max_pages
    if total_pages > 0 and max_pages > 0 and max_pages < total_pages:
        # Docling conversion is whole-document by default. Keep the front proportion
        # to approximate max-pages behavior and bound prompt/token cost.
        ratio = max_pages / float(total_pages)
        cut = max(int(len(text) * ratio), 1000)
        text = text[:cut]
        pages_read = max_pages
        truncated = True
    return text, pages_read, truncated


def split_into_chunks(text: str, chunk_size: int) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []

    # sentence-aware chunking
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text)
    parts: List[str] = []
    current = []
    current_len = 0
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        sent_len = len(sent)
        if current and current_len + sent_len + 1 > chunk_size:
            parts.append(" ".join(current).strip())
            current = [sent]
            current_len = sent_len
        else:
            current.append(sent)
            current_len += sent_len + 1
    if current:
        parts.append(" ".join(current).strip())

    # drop tiny fragments
    # Keep shorter captions/notes because they often contain key numeric values.
    return [p for p in parts if len(p) >= 40]


def is_markdown_table_block(block: str) -> bool:
    lines = [ln.strip() for ln in (block or "").splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    if "|" not in lines[0]:
        return False
    sep_re = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$")
    return any(sep_re.match(ln) for ln in lines[1:3])


def split_docling_markdown_tables(markdown_text: str) -> Tuple[str, List[str]]:
    blocks = re.split(r"\n\s*\n", markdown_text or "")
    text_blocks: List[str] = []
    table_blocks: List[str] = []
    for block in blocks:
        b = block.strip()
        if not b:
            continue
        if is_markdown_table_block(b):
            table_blocks.append(b)
        else:
            text_blocks.append(b)
    return "\n\n".join(text_blocks), table_blocks


def guess_doi(text: str) -> str:
    m = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", text)
    return m.group(0).rstrip(").,;") if m else ""


def guess_title(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:80]:
        if len(line) < 25:
            continue
        if line.lower().startswith(("abstract", "keywords", "introduction")):
            continue
        words = line.split()
        if len(words) < 5:
            continue
        return line
    return lines[0] if lines else ""


def make_journal_reader_from_pdf(
    pdf_path: Path,
    max_pages: int,
    chunk_size: int,
    pdf_parser: str,
) -> Tuple[JournalReader, Dict]:
    total_pages = estimate_total_pages(pdf_path)
    docling_truncated = False
    table_blocks: List[str] = []
    if pdf_parser == "docling":
        text_raw, pages_read, docling_truncated = extract_pdf_text_docling(
            pdf_path=pdf_path,
            max_pages=max_pages,
            total_pages=total_pages,
        )
        text, table_blocks = split_docling_markdown_tables(text_raw)
        if total_pages <= 0:
            total_pages = pages_read
    else:
        text, total_pages = extract_pdf_text(pdf_path, max_pages=max_pages)
        pages_read = min(max_pages, total_pages)

    chunks = split_into_chunks(text, chunk_size=chunk_size)
    elements: List[Paragraph] = []
    idx = 1
    for tb in table_blocks:
        elements.append(
            Paragraph(
                idx=idx,
                type="table",
                content=tb,
                clean_text=tb,
            )
        )
        idx += 1
    for chunk in chunks:
        elements.append(
            Paragraph(
                idx=idx,
                type="text",
                content=chunk,
                clean_text=chunk,
            )
        )
        idx += 1

    metadata = Metadata(
        doi=guess_doi(text),
        title=guess_title(text),
    )

    jr = JournalReader(
        filepath=pdf_path,
        publisher="pdf",
        elements=Elements(elements=elements),
        metadata=metadata,
    )

    diag = {
        "parser_backend": pdf_parser,
        "total_pdf_pages": total_pages,
        "pages_read": pages_read,
        "text_chars": len(text),
        "chunks": len(chunks),
        "table_blocks": len(table_blocks),
        "avg_chunk_chars": round(sum(len(c) for c in chunks) / max(len(chunks), 1), 1),
        "docling_truncated": docling_truncated,
    }
    return jr, diag


def iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from iter_dicts(v)
    elif isinstance(value, list):
        for item in value:
            yield from iter_dicts(item)


def collect_target_rows_from_elements(jr: JournalReader) -> List[Dict]:
    rows: List[Dict] = []
    element_groups = [("elements", jr.elements)]
    if jr.cln_elements:
        element_groups.append(("cln_elements", jr.cln_elements))

    for group_name, elements in element_groups:
        for element in elements:
            if not element.data:
                continue
            for d in iter_dicts(element.data):
                for src_key, val in d.items():
                    matched_key = None
                    for target_key in TARGET_KEYS:
                        if key_matches_target(src_key, target_key):
                            matched_key = target_key
                            break
                    if not matched_key:
                        continue
                    if isinstance(val, list):
                        for row in val:
                            if isinstance(row, dict):
                                rows.append(
                                    {
                                        "source_group": group_name,
                                        "source_idx": str(element.idx),
                                        "key": src_key,
                                        "row": row,
                                    }
                                )
                    elif isinstance(val, dict):
                        rows.append(
                            {
                                "source_group": group_name,
                                "source_idx": str(element.idx),
                                "key": src_key,
                                "row": val,
                            }
                        )
    return rows


def collect_direct_sheet1_rows_from_tables(jr: JournalReader) -> List[Dict]:
    rows: List[Dict] = []
    for element in jr.elements:
        if str(getattr(element, "type", "")).lower() != "table":
            continue
        table_text = str(getattr(element, "clean_text", "") or getattr(element, "content", ""))
        parsed_rows = extract_sheet1_rows_from_markdown_table(table_text)
        for row in parsed_rows:
            rows.append(
                {
                    "source_group": "direct_table",
                    "source_idx": str(element.idx),
                    "key": "biochar_modification",
                    "row": row,
                }
            )
    return rows


def collect_direct_sheet2_rows_from_tables(jr: JournalReader) -> List[Dict]:
    rows: List[Dict] = []
    for element in jr.elements:
        if str(getattr(element, "type", "")).lower() != "table":
            continue
        table_text = str(getattr(element, "clean_text", "") or getattr(element, "content", ""))
        parsed_rows = extract_sheet2_rows_from_markdown_table(table_text)
        for row in parsed_rows:
            rows.append(
                {
                    "source_group": "direct_table",
                    "source_idx": str(element.idx),
                    "key": "adsorption_experiment",
                    "row": row,
                }
            )
    return rows


def summarize_classification(jr: JournalReader) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    for element in jr.elements:
        cls = element.classification
        if not cls:
            stats["(none)"] = stats.get("(none)", 0) + 1
            continue
        if isinstance(cls, str):
            cls = [cls]
        for item in cls:
            stats[str(item)] = stats.get(str(item), 0) + 1
    return stats


def _is_empty(v) -> bool:
    return str(v or "").strip() == ""


def _extract_scrh_temp_from_sid(sid: str) -> str:
    s = str(sid or "").strip().upper()
    m = re.fullmatch(r"SCRH-[A-Z]-[0-9]+(?:\.[0-9]+)?-([0-9]{2,4})", s)
    if not m:
        return ""
    return m.group(1)


def _looks_multi_numeric_value(v) -> bool:
    t = str(v or "").strip()
    if not t:
        return False
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", t)
    if len(nums) <= 1:
        return False
    return any(x in t for x in [",", ";", "/", " to ", " and ", "~", "—", "–", "("])


def enforce_scrh_single_pyrolysis_on_raw_rows(rows: List[Dict]) -> Dict[str, int]:
    stats = {"rows_touched": 0, "rows_filled": 0, "rows_overwritten": 0}
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "") or "")
        is_bio = key_matches_target(key, "biochar_modification") or key_matches_target(
            key, "biochar modification"
        )
        if not is_bio:
            continue
        row = item.get("row")
        if not isinstance(row, dict):
            continue
        sid = str(row.get("sample_id", "") or "").strip()
        target = _extract_scrh_temp_from_sid(sid)
        if not target:
            continue
        stats["rows_touched"] += 1
        cur = row.get("pyrolysis_temp_C", "")
        if _is_empty(cur):
            row["pyrolysis_temp_C"] = target
            stats["rows_filled"] += 1
            continue
        if _looks_multi_numeric_value(cur) and str(cur).strip() != target:
            row["pyrolysis_temp_C"] = target
            stats["rows_overwritten"] += 1
    return stats


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.exists():
        print(f"[ERROR] PDF not found: {pdf_path}", file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(f"[ERROR] Input is not a PDF: {pdf_path}", file=sys.stderr)
        return 2

    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
        return 2

    used_parser = args.pdf_parser
    fallback_note = ""
    try:
        jr, diag = make_journal_reader_from_pdf(
            pdf_path=pdf_path,
            max_pages=args.max_pages,
            chunk_size=args.chunk_size,
            pdf_parser=used_parser,
        )
    except Exception as exc:
        if used_parser == "docling" and args.strict_docling:
            print(
                f"[ERROR] Failed to parse PDF with parser=docling (strict mode): {exc}",
                file=sys.stderr,
            )
            return 1
        if used_parser == "docling":
            print(
                f"[WARN] Failed to parse PDF with parser=docling: {exc}",
                file=sys.stderr,
            )
            print("[WARN] Falling back to parser=pypdf.", file=sys.stderr)
            used_parser = "pypdf"
            fallback_note = f"docling_failed: {exc}"
            try:
                jr, diag = make_journal_reader_from_pdf(
                    pdf_path=pdf_path,
                    max_pages=args.max_pages,
                    chunk_size=args.chunk_size,
                    pdf_parser=used_parser,
                )
            except Exception as exc2:
                print(
                    f"[ERROR] Failed to parse PDF with parser={used_parser}: {exc2}",
                    file=sys.stderr,
                )
                return 1
        else:
            print(
                f"[ERROR] Failed to parse PDF with parser={used_parser}: {exc}",
                file=sys.stderr,
            )
            return 1

    print("=== PDF Preprocess Summary ===")
    print(f"PDF: {pdf_path}")
    print(f"Parser backend: {diag['parser_backend']}")
    print(f"DOI guess: {jr.doi}")
    print(f"Title guess: {jr.title}")
    print(
        f"Pages(total/read): {diag['total_pdf_pages']}/{diag['pages_read']} | "
        f"Chars: {diag['text_chars']} | Table blocks: {diag['table_blocks']} | Chunks: {diag['chunks']} | "
        f"Avg chunk chars: {diag['avg_chunk_chars']}"
    )
    if fallback_note:
        print(f"Fallback parser note: {fallback_note}")
    if diag.get("docling_truncated"):
        print(
            f"Note: docling returned whole-document text; truncated to ~first {args.max_pages} pages by length ratio."
        )

    if args.dry_run:
        return 0

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            agent = LLMMiner.from_yaml(str(config_path), openai_api_key=args.api_key)
            agent.invoke({agent.input_key: jr})
    except Exception as exc:
        print(f"[ERROR] Agent run failed: {exc}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)
        return 1

    result_dict = jr.result.to_dict()
    extracted_materials = len(result_dict.get("results", []))
    raw_target_rows = collect_target_rows_from_elements(jr)
    direct_sheet1_rows = collect_direct_sheet1_rows_from_tables(jr)
    direct_sheet2_rows = collect_direct_sheet2_rows_from_tables(jr)
    if direct_sheet1_rows:
        raw_target_rows.extend(direct_sheet1_rows)
    if direct_sheet2_rows:
        raw_target_rows.extend(direct_sheet2_rows)
    scrh_fix_stats = enforce_scrh_single_pyrolysis_on_raw_rows(raw_target_rows)
    cls_stats = summarize_classification(jr)
    elements_with_data = sum(1 for e in jr.elements if bool(e.data))
    cln_elements_with_data = (
        sum(1 for e in jr.cln_elements if bool(e.data)) if jr.cln_elements else 0
    )
    cln_total = len(jr.cln_elements) if jr.cln_elements else 0

    print("=== Extraction Summary ===")
    print(f"Materials extracted: {extracted_materials}")
    print(f"Elements with non-empty data: {elements_with_data}/{len(jr.elements)}")
    print(f"Cln-elements with non-empty data: {cln_elements_with_data}/{cln_total}")
    print(f"Classification stats: {cls_stats}")
    print(f"Raw target rows (before MetaCollector): {len(raw_target_rows)}")
    print(f"Direct sheet1 rows from table parser: {len(direct_sheet1_rows)}")
    print(f"Direct sheet2 rows from table parser: {len(direct_sheet2_rows)}")
    print(
        "SCRH single-pyrolysis enforcement: "
        f"touched {scrh_fix_stats.get('rows_touched', 0)}, "
        f"filled +{scrh_fix_stats.get('rows_filled', 0)}, "
        f"overwritten +{scrh_fix_stats.get('rows_overwritten', 0)}"
    )

    if args.output_json:
        out = Path(args.output_json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, ensure_ascii=False, indent=2)
        print(f"Saved result JSON: {out}")

    if args.raw_target_json:
        out = Path(args.raw_target_json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(raw_target_rows, f, ensure_ascii=False, indent=2)
        print(f"Saved raw target rows: {out}")

    if args.reader_json:
        out = Path(args.reader_json).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        jr.to_json(str(out))
        print(f"Saved JournalReader JSON: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
