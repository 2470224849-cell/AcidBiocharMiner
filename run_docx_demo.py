#!/usr/bin/env python3
import argparse
import json
import re
import sys
import warnings
import xml.etree.ElementTree as ET
import zipfile
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

from llm_miner import LLMMiner
from llm_miner.parser.base import Metadata
from llm_miner.reader import JournalReader
from llm_miner.schema import Elements, Paragraph

TARGET_KEYS = [
    "biochar modification",
    "biochar_modification",
    "adsorption experiment",
    "adsorption_experiment",
]

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


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
        description="Run one-pass extraction from a DOCX by parsing paragraphs and tables."
    )
    parser.add_argument("--docx", required=True, help="Absolute path to one DOCX file.")
    parser.add_argument("--config", default="config/config.yaml", help="YAML config path.")
    parser.add_argument("--api-key", default=None, help="API key override.")
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
        help="Only parse DOCX/chunk text and print diagnostics, without LLM calls.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_chunks(text: str, chunk_size: int) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text)
    parts: List[str] = []
    current: List[str] = []
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
    # Keep shorter captions/notes because they often contain key numeric values.
    return [p for p in parts if len(p) >= 40]


def extract_para_text(p_el: ET.Element) -> str:
    texts: List[str] = []
    for node in p_el.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t":
            texts.append(node.text or "")
        elif tag == "tab":
            texts.append("\t")
        elif tag in {"br", "cr"}:
            texts.append("\n")
    text = "".join(texts)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def escape_md_cell(text: str) -> str:
    s = str(text or "").replace("\n", " ").strip()
    return s.replace("|", "\\|")


def table_to_markdown(tbl_el: ET.Element) -> str:
    rows: List[List[str]] = []
    for tr in tbl_el.findall("./w:tr", NS):
        cells: List[str] = []
        for tc in tr.findall("./w:tc", NS):
            paras = tc.findall(".//w:p", NS)
            c_text_parts = [extract_para_text(p) for p in paras]
            c_text = " ".join(x for x in c_text_parts if x).strip()
            cells.append(escape_md_cell(c_text))
        if cells and any(x.strip() for x in cells):
            rows.append(cells)

    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    header = rows[0]
    sep = ["---"] * ncol
    md_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for r in rows[1:]:
        md_lines.append("| " + " | ".join(r) + " |")
    return "\n".join(md_lines)


def parse_docx_blocks(docx_path: Path) -> Tuple[List[str], List[str]]:
    with zipfile.ZipFile(docx_path, "r") as zf:
        with zf.open("word/document.xml") as f:
            xml_bytes = f.read()

    root = ET.fromstring(xml_bytes)
    body = root.find(".//w:body", NS)
    if body is None:
        return [], []

    text_blocks: List[str] = []
    table_blocks: List[str] = []
    for child in list(body):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            txt = extract_para_text(child)
            if txt:
                text_blocks.append(txt)
        elif tag == "tbl":
            md = table_to_markdown(child)
            if md.strip():
                table_blocks.append(md)
    return text_blocks, table_blocks


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


def make_journal_reader_from_docx(
    docx_path: Path,
    chunk_size: int,
) -> Tuple[JournalReader, Dict]:
    text_blocks, table_blocks = parse_docx_blocks(docx_path)
    text = "\n\n".join(text_blocks)
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
        filepath=docx_path,
        publisher="docx",
        elements=Elements(elements=elements),
        metadata=metadata,
    )
    diag = {
        "parser_backend": "docx",
        "blocks_text": len(text_blocks),
        "table_blocks": len(table_blocks),
        "text_chars": len(text),
        "chunks": len(chunks),
        "avg_chunk_chars": round(sum(len(c) for c in chunks) / max(len(chunks), 1), 1),
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


def main() -> int:
    args = parse_args()
    docx_path = Path(args.docx).expanduser()
    if not docx_path.exists():
        print(f"[ERROR] DOCX not found: {docx_path}", file=sys.stderr)
        return 2
    if docx_path.suffix.lower() != ".docx":
        print(f"[ERROR] Input is not a DOCX: {docx_path}", file=sys.stderr)
        return 2

    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}", file=sys.stderr)
        return 2

    try:
        jr, diag = make_journal_reader_from_docx(
            docx_path=docx_path,
            chunk_size=args.chunk_size,
        )
    except Exception as exc:
        print(f"[ERROR] Failed to parse DOCX: {exc}", file=sys.stderr)
        return 1

    print("=== DOCX Preprocess Summary ===")
    print(f"DOCX: {docx_path}")
    print(f"Parser backend: {diag['parser_backend']}")
    print(f"DOI guess: {jr.doi}")
    print(f"Title guess: {jr.title}")
    print(
        f"Text blocks: {diag['blocks_text']} | Chars: {diag['text_chars']} | "
        f"Table blocks: {diag['table_blocks']} | Chunks: {diag['chunks']} | "
        f"Avg chunk chars: {diag['avg_chunk_chars']}"
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
        return 1

    result_dict = jr.result.to_dict()
    extracted_materials = len(result_dict.get("results", []))
    raw_target_rows = collect_target_rows_from_elements(jr)
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
