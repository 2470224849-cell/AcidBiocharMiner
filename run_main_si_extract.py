#!/usr/bin/env python3
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def safe_stem(text: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "")
    return out.strip("._-") or "file"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run extraction on main PDF + supplementary PDFs (SI), "
            "then merge raw rows and export one Excel (sheet1/sheet2)."
        )
    )
    p.add_argument("--main-pdf", required=True, help="Main article PDF path.")
    p.add_argument(
        "--si-pdf",
        action="append",
        default=[],
        help="Supplementary PDF path. Can repeat.",
    )
    p.add_argument(
        "--si-docx",
        action="append",
        default=[],
        help="Supplementary DOCX path. Can repeat.",
    )
    p.add_argument(
        "--auto-discover-si",
        action="store_true",
        help="Auto-discover SI files (.pdf/.docx) in --si-dir based on filename keywords/root.",
    )
    p.add_argument(
        "--si-dir",
        default="",
        help="Directory for SI auto-discovery (default: main PDF directory).",
    )
    p.add_argument(
        "--si-keywords",
        default="supplement,supplementary,supporting,suppinfo,si,mmc,appendix,moesm,esm,sm",
        help="Comma-separated keywords for SI auto-discovery.",
    )
    p.add_argument(
        "--si-include-all",
        dest="si_include_all",
        action="store_true",
        default=False,
        help="Include all supplement-like files in si-dir (default: disabled).",
    )
    p.add_argument(
        "--si-root-match-only",
        dest="si_include_all",
        action="store_false",
        help="Only include SI files that also match main filename root.",
    )
    p.add_argument("--config", default="config/config.yaml", help="Config YAML path.")
    p.add_argument(
        "--python-exec",
        default="",
        help="Python executable used to run child scripts (default: .venv/bin/python if exists).",
    )
    p.add_argument("--api-key", default=None, help="API key override.")
    p.add_argument(
        "--api-key-env",
        default="DEEPSEEK_API_KEY",
        help="Env var for API key when --api-key is omitted.",
    )
    p.add_argument(
        "--pdf-parser",
        choices=["pypdf", "docling"],
        default="docling",
        help="PDF parser backend passed to run_pdf_demo.py.",
    )
    p.add_argument(
        "--strict-docling",
        action="store_true",
        help="Pass through to run_pdf_demo.py: fail on docling parse errors instead of fallback to pypdf.",
    )
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--chunk-size", type=int, default=1800)
    p.add_argument(
        "--out-dir",
        default="output/main_si_extract",
        help="Output directory.",
    )
    p.add_argument(
        "--sample-filter",
        choices=["none", "acid_pristine"],
        default="acid_pristine",
        help="Filter extracted sample rows before Excel export (default: acid_pristine).",
    )
    p.add_argument(
        "--tag",
        default="",
        help="Optional output tag; default uses main PDF stem.",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip a file if per-file outputs already exist.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to run_pdf_demo.py (no LLM calls).",
    )
    return p.parse_args()


def resolve_pdf(path_text: str) -> Path:
    p = Path(path_text).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {p}")
    if p.suffix.lower() != ".pdf":
        raise ValueError(f"Not a PDF: {p}")
    return p


def resolve_docx(path_text: str) -> Path:
    p = Path(path_text).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"DOCX not found: {p}")
    if p.suffix.lower() not in {".docx", ".doc"}:
        raise ValueError(f"Not a DOC/DOCX: {p}")
    return p


def dedupe_keep_order(paths: List[Path]) -> List[Path]:
    seen = set()
    out: List[Path] = []
    for p in paths:
        k = str(p.resolve())
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def dedupe_doc_variants(paths: List[Path]) -> List[Path]:
    """For same stem, prefer .docx over .doc to avoid duplicate SI processing."""
    best: Dict[str, Path] = {}
    order: List[str] = []
    for p in paths:
        key = str(p.with_suffix("").resolve())
        if key not in best:
            best[key] = p
            order.append(key)
            continue
        cur = best[key]
        if cur.suffix.lower() == ".doc" and p.suffix.lower() == ".docx":
            best[key] = p
    return [best[k] for k in order]


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def is_supplement_candidate(filename: str, keywords: List[str]) -> bool:
    name = (filename or "").lower()
    stem = Path(name).stem
    for kw in keywords:
        kw = (kw or "").strip().lower()
        if not kw:
            continue
        # Match keyword as a standalone token, optionally followed by digits
        # (e.g., mmc1, si2), to avoid false positives like "situ"/"mechanisms".
        if re.search(rf"(?:^|[^a-z0-9]){re.escape(kw)}\d*(?:[^a-z0-9]|$)", stem):
            return True
    if re.search(r"(?:^|[_-])mmc\d+(?:$|[_-])", stem):
        return True
    if re.search(r"(?:^|[_-])sm\d+(?:$|[_-])", stem):
        return True
    if re.search(r"(?:^|[^a-z0-9])(?:moesm|esm)\d*(?:[^a-z0-9]|$)", stem):
        return True
    return False


def detect_main_root(stem: str) -> str:
    # Common publisher naming pattern: xxx-main / xxx-supp / xxx-mmc1
    s = stem
    s = re.sub(r"[-_](main|supp|si|appendix)\d*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"[-_]mmc\d+$", "", s, flags=re.IGNORECASE)
    return s


def discover_si_files(
    main_pdf: Path,
    si_dir: Path,
    keywords: List[str],
    include_all: bool = False,
    allow_single_main_context: bool = True,
) -> List[Path]:
    files = sorted(
        [
            p
            for p in si_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".pdf", ".docx", ".doc"}
        ]
    )
    main_root = detect_main_root(main_pdf.stem).lower()
    main_root_norm = norm_name(main_root)
    main_name = main_pdf.name.lower()
    # If this folder appears to contain only this main article (no other main-like PDFs),
    # allow generic supplementary filenames (e.g., "Supplementary Information.pdf").
    other_non_si_pdfs = [
        p
        for p in files
        if p.suffix.lower() == ".pdf"
        and p.name.lower() != main_name
        and not is_supplement_candidate(p.name, keywords)
    ]
    single_main_context = len(other_non_si_pdfs) == 0
    out: List[Path] = []
    for p in files:
        name = p.name.lower()
        if name == main_name:
            continue
        stem = p.stem.lower()
        hit_kw = is_supplement_candidate(name, keywords)
        hit_root = bool(main_root) and main_root in stem
        hit_root_norm = bool(main_root_norm) and main_root_norm in norm_name(stem)
        if include_all:
            if hit_kw:
                out.append(p.resolve())
            continue
        if allow_single_main_context and hit_kw and single_main_context:
            out.append(p.resolve())
            continue
        if hit_kw and (hit_root or hit_root_norm):
            out.append(p.resolve())
            continue
        # Also allow strict root-match even without explicit SI keyword.
        if hit_root or hit_root_norm:
            out.append(p.resolve())
    return out


def run_one_doc(
    py_exec: str,
    doc_path: Path,
    role: str,
    args: argparse.Namespace,
    out_dir: Path,
    api_key: str,
) -> Dict:
    stem = safe_stem(f"{role}__{doc_path.stem}")
    result_json = out_dir / f"{stem}_result.json"
    raw_json = out_dir / f"{stem}_raw_target_rows.json"
    reader_json = out_dir / f"{stem}_reader.json"
    log_path = out_dir / f"{stem}.log"

    if args.skip_existing and result_json.exists() and raw_json.exists() and reader_json.exists():
        return {
            "pdf": str(doc_path),
            "role": role,
            "status": "SKIP",
            "return_code": 0,
            "result_json": str(result_json),
            "raw_target_json": str(raw_json),
            "reader_json": str(reader_json),
            "log": str(log_path),
        }

    cmd = [py_exec]
    effective_doc_path = doc_path
    if doc_path.suffix.lower() == ".doc":
        converted_dir = out_dir / "converted_si_docx"
        converted_dir.mkdir(parents=True, exist_ok=True)
        converted_docx = converted_dir / f"{doc_path.stem}.docx"
        convert_cmd = [
            "textutil",
            "-convert",
            "docx",
            str(doc_path),
            "-output",
            str(converted_docx),
        ]
        conv = subprocess.run(convert_cmd, capture_output=True, text=True)
        if conv.returncode != 0 or not converted_docx.exists():
            convert_log = "\n".join(
                [
                    "$ " + " ".join(shlex.quote(x) for x in convert_cmd),
                    "",
                    "=== STDOUT ===",
                    conv.stdout or "",
                    "",
                    "=== STDERR ===",
                    conv.stderr or "",
                ]
            )
            log_path.write_text(convert_log, encoding="utf-8")
            return {
                "pdf": str(doc_path),
                "role": role,
                "status": "FAIL",
                "return_code": conv.returncode or 1,
                "result_json": str(result_json),
                "raw_target_json": str(raw_json),
                "reader_json": str(reader_json),
                "log": str(log_path),
            }
        effective_doc_path = converted_docx

    if effective_doc_path.suffix.lower() == ".docx":
        cmd.extend(
            [
                "run_docx_demo.py",
                "--docx",
                str(effective_doc_path),
                "--config",
                str(Path(args.config).expanduser()),
                "--chunk-size",
                str(args.chunk_size),
                "--output-json",
                str(result_json),
                "--raw-target-json",
                str(raw_json),
                "--reader-json",
                str(reader_json),
            ]
        )
    else:
        cmd.extend(
            [
                "run_pdf_demo.py",
                "--pdf",
                str(effective_doc_path),
                "--config",
                str(Path(args.config).expanduser()),
                "--pdf-parser",
                args.pdf_parser,
                "--max-pages",
                str(args.max_pages),
                "--chunk-size",
                str(args.chunk_size),
                "--output-json",
                str(result_json),
                "--raw-target-json",
                str(raw_json),
                "--reader-json",
                str(reader_json),
            ]
        )
        if args.strict_docling:
            cmd.append("--strict-docling")
    if args.dry_run:
        cmd.append("--dry-run")
    else:
        cmd.extend(["--api-key", api_key])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    redacted_cmd: List[str] = []
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == "--api-key" and i + 1 < len(cmd):
            redacted_cmd.extend([tok, "***REDACTED***"])
            i += 2
            continue
        redacted_cmd.append(tok)
        i += 1
    full_log = "\n".join(
        [
            "$ " + " ".join(shlex.quote(x) for x in redacted_cmd),
            "",
            "=== STDOUT ===",
            proc.stdout or "",
            "",
            "=== STDERR ===",
            proc.stderr or "",
        ]
    )
    log_path.write_text(full_log, encoding="utf-8")

    status = "OK" if proc.returncode == 0 else "FAIL"
    return {
        "pdf": str(doc_path),
        "effective_input": str(effective_doc_path),
        "role": role,
        "status": status,
        "return_code": proc.returncode,
        "result_json": str(result_json),
        "raw_target_json": str(raw_json),
        "reader_json": str(reader_json),
        "log": str(log_path),
    }


def load_raw_rows(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def merge_raw_rows(run_items: List[Dict]) -> List[Dict]:
    merged: List[Dict] = []
    for item in run_items:
        if item.get("status") not in {"OK", "SKIP"}:
            continue
        pdf_name = Path(str(item.get("pdf", ""))).name
        role = str(item.get("role", ""))
        raw_path = Path(str(item.get("raw_target_json", "")))
        for row_item in load_raw_rows(raw_path):
            row = row_item.get("row")
            if isinstance(row, dict) and not str(row.get("filename", "")).strip():
                row["filename"] = pdf_name
            row_item["from_role"] = role
            row_item["from_pdf"] = str(item.get("pdf", ""))
            merged.append(row_item)
    return merged


def run_export_excel(
    py_exec: str,
    merged_raw_json: Path,
    fallback_result_json: Path,
    out_xlsx: Path,
    out_log: Path,
    sample_filter: str,
) -> int:
    cmd = [
        py_exec,
        "export_target_excel.py",
        "--raw-json",
        str(merged_raw_json),
        "--result-json",
        str(fallback_result_json),
        "--xlsx",
        str(out_xlsx),
        "--sample-filter",
        sample_filter,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out_log.write_text(
        "\n".join(
            [
                "$ " + " ".join(shlex.quote(x) for x in cmd),
                "",
                "=== STDOUT ===",
                proc.stdout or "",
                "",
                "=== STDERR ===",
                proc.stderr or "",
            ]
        ),
        encoding="utf-8",
    )
    return proc.returncode


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    main_pdf = resolve_pdf(args.main_pdf)
    si_pdfs = [resolve_pdf(p) for p in (args.si_pdf or [])]
    si_docx = [resolve_docx(p) for p in (args.si_docx or [])]

    if args.auto_discover_si:
        si_dir = Path(args.si_dir).expanduser().resolve() if args.si_dir else main_pdf.parent
        if not si_dir.exists():
            print(f"[ERROR] SI directory not found: {si_dir}", file=sys.stderr)
            return 2
        keywords = [x.strip().lower() for x in args.si_keywords.split(",") if x.strip()]
        auto_sis = discover_si_files(
            main_pdf=main_pdf,
            si_dir=si_dir,
            keywords=keywords,
            include_all=args.si_include_all,
            allow_single_main_context=(si_dir.resolve() == main_pdf.parent.resolve()),
        )
        for f in auto_sis:
            if f.suffix.lower() in {".docx", ".doc"}:
                si_docx.append(f)
            else:
                si_pdfs.append(f)

    si_pdfs = [p for p in dedupe_keep_order(si_pdfs) if p.resolve() != main_pdf.resolve()]
    si_docx = dedupe_doc_variants(dedupe_keep_order(si_docx))
    run_list: List[Tuple[str, Path]] = (
        [("main", main_pdf)]
        + [("si_pdf", p) for p in si_pdfs]
        + [("si_docx", p) for p in si_docx]
    )

    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}", file=sys.stderr)
        return 2

    resolved_api_key = args.api_key or os.getenv(args.api_key_env, "")
    if not args.dry_run and not resolved_api_key:
        print(
            f"[ERROR] Missing API key. Provide --api-key or set {args.api_key_env}.",
            file=sys.stderr,
        )
        return 2

    if args.python_exec:
        py_exec = str(Path(args.python_exec).expanduser())
    else:
        venv_py = Path.cwd() / ".venv" / "bin" / "python"
        py_exec = str(venv_py if venv_py.exists() else Path(sys.executable))
    if not Path(py_exec).exists():
        print(f"[ERROR] Python executable not found: {py_exec}", file=sys.stderr)
        return 2
    tag = safe_stem(args.tag) if args.tag else safe_stem(main_pdf.stem)

    print("=== Main+SI Extraction Plan ===")
    print(f"Main PDF: {main_pdf}")
    print(f"SI PDFs: {len(si_pdfs)}")
    for p in si_pdfs:
        print(f"  - {p}")
    print(f"SI DOCX: {len(si_docx)}")
    for p in si_docx:
        print(f"  - {p}")
    print(f"Parser: {args.pdf_parser}")
    print(f"Strict docling: {args.strict_docling}")
    print(f"SI include all: {args.si_include_all}")
    print(f"Sample filter: {args.sample_filter}")
    print(f"Child Python: {py_exec}")
    print(f"Output dir: {out_dir}")
    print(f"Dry run: {args.dry_run}")

    run_items: List[Dict] = []
    total = len(run_list)
    for i, (role, doc_path) in enumerate(run_list, 1):
        print(f"[{i}/{total}] RUN  ({role}) {doc_path}")
        item = run_one_doc(
            py_exec=py_exec,
            doc_path=doc_path,
            role=role,
            args=args,
            out_dir=out_dir,
            api_key=resolved_api_key,
        )
        run_items.append(item)
        if item["status"] in {"OK", "SKIP"}:
            print(f"[{i}/{total}] DONE ({role}) status={item['status']}")
        else:
            print(f"[{i}/{total}] FAIL ({role}) rc={item['return_code']} log={item['log']}")

    merged_rows = merge_raw_rows(run_items)
    merged_raw_json = out_dir / f"{tag}_merged_raw_target_rows.json"
    merged_raw_json.write_text(json.dumps(merged_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_json = out_dir / f"{tag}_main_si_summary.json"
    summary_payload = {
        "main_pdf": str(main_pdf),
        "si_pdfs": [str(p) for p in si_pdfs],
        "si_docx": [str(p) for p in si_docx],
        "pdf_parser": args.pdf_parser,
        "dry_run": bool(args.dry_run),
        "runs": run_items,
        "merged_raw_rows": len(merged_rows),
        "merged_raw_json": str(merged_raw_json),
    }
    summary_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        fail_count = sum(1 for x in run_items if x.get("status") == "FAIL")
        print("=== Main+SI Summary ===")
        print(f"Total docs (main+si): {len(run_list)}")
        print(f"OK/SKIP: {len(run_list) - fail_count} | FAIL: {fail_count}")
        print("Dry-run mode: skip Excel export.")
        print(f"Saved run summary: {summary_json}")
        return 0 if fail_count == 0 else 1

    ok_items = [x for x in run_items if x.get("status") in {"OK", "SKIP"}]
    if not ok_items:
        print("[ERROR] No successful runs; skip export.", file=sys.stderr)
        print(f"Saved summary: {summary_json}")
        return 1

    fail_count = sum(1 for x in run_items if x.get("status") == "FAIL")
    if len(merged_rows) == 0:
        print("=== Main+SI Summary ===")
        print(f"Total docs (main+si): {len(run_list)}")
        print(f"OK/SKIP: {len(run_list) - fail_count} | FAIL: {fail_count}")
        print(f"Merged raw rows: {len(merged_rows)}")
        print(f"Saved merged raw rows: {merged_raw_json}")
        print(f"Saved run summary: {summary_json}")
        print("[WARN] No extracted target rows after filtering; skip per-paper Excel export.")
        return 0 if fail_count == 0 else 1

    out_xlsx = out_dir / f"{tag}_main_plus_si_tables.xlsx"
    export_log = out_dir / f"{tag}_export_excel.log"
    fallback_result = Path(str(ok_items[0]["result_json"]))
    export_rc = run_export_excel(
        py_exec=py_exec,
        merged_raw_json=merged_raw_json,
        fallback_result_json=fallback_result,
        out_xlsx=out_xlsx,
        out_log=export_log,
        sample_filter=args.sample_filter,
    )

    print("=== Main+SI Summary ===")
    print(f"Total docs (main+si): {len(run_list)}")
    print(f"OK/SKIP: {len(run_list) - fail_count} | FAIL: {fail_count}")
    print(f"Merged raw rows: {len(merged_rows)}")
    print(f"Saved merged raw rows: {merged_raw_json}")
    print(f"Saved run summary: {summary_json}")
    if export_rc == 0:
        print(f"Saved merged Excel: {out_xlsx}")
    else:
        print(f"[WARN] Excel export failed (rc={export_rc}), see: {export_log}")

    return 0 if fail_count == 0 and export_rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
