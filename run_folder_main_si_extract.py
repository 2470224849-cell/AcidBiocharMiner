#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import os
import shlex
import subprocess
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Batch run main+SI extraction for all main PDFs in a folder, "
            "then optionally merge all outputs into one Excel."
        )
    )
    p.add_argument("--input-dir", required=True, help="Folder containing article PDFs.")
    p.add_argument(
        "--si-dir",
        default="",
        help="Folder used to auto-discover SI files (default: same as input-dir).",
    )
    p.add_argument(
        "--main-glob",
        default="*-main.pdf",
        help="Glob pattern used to find main PDFs (default: *-main.pdf).",
    )
    p.add_argument(
        "--recursive",
        action="store_true",
        help="Search main PDFs recursively.",
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
        help="PDF parser backend.",
    )
    p.add_argument(
        "--strict-docling",
        action="store_true",
        help="Pass through to run_main_si_extract.py: fail on docling parse errors (no fallback).",
    )
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--chunk-size", type=int, default=1800)
    p.add_argument(
        "--sample-filter",
        choices=["none", "acid_pristine"],
        default="acid_pristine",
        help="Filter extracted sample rows before Excel export.",
    )
    p.add_argument(
        "--out-dir",
        default="output/folder_main_si_extract",
        help="Batch output directory.",
    )
    p.add_argument("--limit", type=int, default=0, help="Optional max number of main PDFs.")
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of papers to process concurrently (default: 1).",
    )
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--no-merge-excel",
        action="store_true",
        help="Do not build a merged Excel across papers.",
    )
    p.add_argument(
        "--si-keywords",
        default="supplement,supplementary,supporting,suppinfo,si,mmc,appendix,moesm,esm,sm",
        help="Comma-separated SI keywords used to avoid selecting supplementary files as main PDFs.",
    )
    p.add_argument(
        "--si-include-all",
        dest="si_include_all",
        action="store_true",
        default=False,
        help="Pass through to run_main_si_extract: include all supplement-like files in si-dir for each paper (default: disabled).",
    )
    p.add_argument(
        "--si-root-match-only",
        dest="si_include_all",
        action="store_false",
        help="Pass through strict SI matching (require main-root match).",
    )
    p.add_argument(
        "--post-backfill",
        choices=["none", "table", "table_method"],
        default="table_method",
        help=(
            "Post-process merged Excel: "
            "none=disable, table=table-only backfill, table_method=table then method-text backfill (default)."
        ),
    )
    p.add_argument(
        "--method-backfill-allow-global",
        action="store_true",
        help="Pass --allow-global to method-text backfill (higher recall, lower precision).",
    )
    p.add_argument(
        "--sheet2-method-backfill",
        dest="sheet2_method_backfill",
        action="store_true",
        default=True,
        help="Run sheet2 method-text backfill after sheet1 method backfill (default: enabled).",
    )
    p.add_argument(
        "--no-sheet2-method-backfill",
        dest="sheet2_method_backfill",
        action="store_false",
        help="Disable sheet2 method-text backfill.",
    )
    p.add_argument(
        "--sheet2-room-temp-as-k",
        dest="sheet2_room_temp_as_k",
        action="store_true",
        default=True,
        help="Map 'room/ambient temperature' to 298.15 K in sheet2 method backfill (default: enabled).",
    )
    p.add_argument(
        "--sheet2-backfill-allow-global",
        dest="sheet2_backfill_allow_global",
        action="store_true",
        default=True,
        help="Allow global method-sentence inference in sheet2 backfill (default: enabled).",
    )
    p.add_argument(
        "--no-sheet2-backfill-allow-global",
        dest="sheet2_backfill_allow_global",
        action="store_false",
        help="Disable global method-sentence inference in sheet2 backfill.",
    )
    p.add_argument(
        "--no-sheet2-room-temp-as-k",
        dest="sheet2_room_temp_as_k",
        action="store_false",
        help="Disable room-temperature-to-K mapping in sheet2 method backfill.",
    )
    return p.parse_args()


def choose_python_exec(user_py: str) -> str:
    if user_py:
        py = Path(user_py).expanduser()
        return str(py)
    venv_py = Path.cwd() / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return str(Path(sys.executable))


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


def find_main_pdfs(input_dir: Path, pattern: str, recursive: bool, si_keywords: List[str]) -> List[Path]:
    if recursive:
        candidates = sorted([p.resolve() for p in input_dir.rglob(pattern) if p.is_file()])
    else:
        candidates = sorted([p.resolve() for p in input_dir.glob(pattern) if p.is_file()])
    mains = [p for p in candidates if not is_supplement_candidate(p.name, si_keywords)]
    return mains


def load_json_list(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    return []


def run_one(
    py_exec: str,
    main_pdf: Path,
    si_dir: Path,
    args: argparse.Namespace,
    out_dir: Path,
    api_key: str,
) -> Dict:
    paper_tag = main_pdf.stem
    paper_out_dir = out_dir / paper_tag
    paper_out_dir.mkdir(parents=True, exist_ok=True)
    log_path = paper_out_dir / "batch_wrapper.log"
    paper_si_dir = main_pdf.parent if args.recursive else si_dir

    cmd = [
        py_exec,
        "run_main_si_extract.py",
        "--main-pdf",
        str(main_pdf),
        "--auto-discover-si",
        "--si-dir",
        str(paper_si_dir),
        "--si-keywords",
        args.si_keywords,
        "--config",
        str(Path(args.config).expanduser()),
        "--python-exec",
        py_exec,
        "--pdf-parser",
        args.pdf_parser,
        "--max-pages",
        str(args.max_pages),
        "--chunk-size",
        str(args.chunk_size),
        "--sample-filter",
        args.sample_filter,
        "--out-dir",
        str(paper_out_dir),
        "--tag",
        paper_tag,
    ]
    if args.skip_existing:
        cmd.append("--skip-existing")
    if args.si_include_all:
        cmd.append("--si-include-all")
    if args.strict_docling:
        cmd.append("--strict-docling")
    if args.dry_run:
        cmd.append("--dry-run")
    else:
        cmd.extend(["--api-key", api_key])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    redacted = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "--api-key" and i + 1 < len(cmd):
            redacted.extend(["--api-key", "***REDACTED***"])
            i += 2
            continue
        redacted.append(cmd[i])
        i += 1
    log_path.write_text(
        "\n".join(
            [
                "$ " + " ".join(shlex.quote(x) for x in redacted),
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

    # run_main_si_extract.py sanitizes tag internally, so filenames may differ from raw stem.
    summary_candidates = sorted(paper_out_dir.glob("*_main_si_summary.json"))
    summary_path = summary_candidates[0] if summary_candidates else None
    merged_raw_path = None
    if summary_path and summary_path.exists():
        try:
            summary_obj = json.loads(summary_path.read_text(encoding="utf-8"))
            mr = summary_obj.get("merged_raw_json")
            if isinstance(mr, str) and mr.strip():
                merged_raw_path = Path(mr)
        except Exception:
            merged_raw_path = None
    if merged_raw_path is None:
        merged_candidates = sorted(paper_out_dir.glob("*_merged_raw_target_rows.json"))
        merged_raw_path = merged_candidates[0] if merged_candidates else None

    return {
        "main_pdf": str(main_pdf),
        "out_dir": str(paper_out_dir),
        "return_code": proc.returncode,
        "status": "OK" if proc.returncode == 0 else "FAIL",
        "wrapper_log": str(log_path),
        "main_si_summary_json": str(summary_path) if summary_path else "",
        "merged_raw_json": str(merged_raw_path) if merged_raw_path else "",
    }


def run_merge_excel(
    py_exec: str,
    merged_raw_json: Path,
    out_xlsx: Path,
    sample_filter: str,
    out_log: Path,
) -> int:
    cmd = [
        py_exec,
        "export_target_excel.py",
        "--raw-json",
        str(merged_raw_json),
        "--result-json",
        str(merged_raw_json),  # fallback not used if raw-json is valid list
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


def run_backfill_table(
    py_exec: str,
    in_xlsx: Path,
    reader_root: Path,
    out_xlsx: Path,
    out_log: Path,
) -> int:
    cmd = [
        py_exec,
        "backfill_sheet1_from_reader_tables.py",
        "--xlsx",
        str(in_xlsx),
        "--reader-root",
        str(reader_root),
        "--out-xlsx",
        str(out_xlsx),
        "--log",
        str(out_log.with_suffix(".details.log")),
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


def run_backfill_method(
    py_exec: str,
    in_xlsx: Path,
    reader_root: Path,
    out_xlsx: Path,
    out_log: Path,
    sample_filter: str,
    allow_global: bool,
) -> int:
    cmd = [
        py_exec,
        "backfill_sheet1_from_method_text.py",
        "--xlsx",
        str(in_xlsx),
        "--reader-root",
        str(reader_root),
        "--sample-filter",
        sample_filter,
        "--out-xlsx",
        str(out_xlsx),
        "--log",
        str(out_log.with_suffix(".details.log")),
    ]
    if allow_global:
        cmd.append("--allow-global")
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


def run_backfill_method_sheet2(
    py_exec: str,
    in_xlsx: Path,
    reader_root: Path,
    out_xlsx: Path,
    out_log: Path,
    sample_filter: str,
    allow_global: bool,
    room_temp_as_k: bool,
) -> int:
    cmd = [
        py_exec,
        "backfill_sheet2_from_method_text.py",
        "--xlsx",
        str(in_xlsx),
        "--reader-root",
        str(reader_root),
        "--sample-filter",
        sample_filter,
        "--out-xlsx",
        str(out_xlsx),
        "--log",
        str(out_log.with_suffix(".details.log")),
    ]
    if allow_global:
        cmd.append("--allow-global")
    if room_temp_as_k:
        cmd.append("--room-temp-as-k")
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
    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[ERROR] input-dir not found: {input_dir}", file=sys.stderr)
        return 2
    si_dir = Path(args.si_dir).expanduser().resolve() if args.si_dir else input_dir
    if not si_dir.exists() or not si_dir.is_dir():
        print(f"[ERROR] si-dir not found: {si_dir}", file=sys.stderr)
        return 2

    config_path = Path(args.config).expanduser()
    if not config_path.exists():
        print(f"[ERROR] config not found: {config_path}", file=sys.stderr)
        return 2

    py_exec = choose_python_exec(args.python_exec)
    if not Path(py_exec).exists():
        print(f"[ERROR] python executable not found: {py_exec}", file=sys.stderr)
        return 2

    api_key = args.api_key or os.getenv(args.api_key_env, "")
    if not args.dry_run and not api_key:
        print(
            f"[ERROR] Missing API key. Provide --api-key or set {args.api_key_env}.",
            file=sys.stderr,
        )
        return 2

    si_keywords = [x.strip().lower() for x in args.si_keywords.split(",") if x.strip()]
    mains = find_main_pdfs(
        input_dir=input_dir,
        pattern=args.main_glob,
        recursive=args.recursive,
        si_keywords=si_keywords,
    )
    if args.limit > 0:
        mains = mains[: args.limit]
    if not mains:
        print(
            f"[ERROR] No main PDFs found under {input_dir} with pattern: {args.main_glob}",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== Folder Main+SI Plan ===")
    print(f"Input dir: {input_dir}")
    print(f"SI dir: {si_dir}")
    print(f"Main glob: {args.main_glob} | recursive={args.recursive}")
    print(f"Main PDFs found: {len(mains)}")
    print(f"SI include all: {args.si_include_all}")
    print(f"Parser: {args.pdf_parser}")
    print(f"Strict docling: {args.strict_docling}")
    print(f"Sample filter: {args.sample_filter}")
    print(f"Post-backfill: {args.post_backfill}")
    print(f"Method backfill allow-global: {args.method_backfill_allow_global}")
    print(f"Sheet2 method backfill: {args.sheet2_method_backfill}")
    print(f"Sheet2 backfill allow-global: {args.sheet2_backfill_allow_global}")
    print(f"Sheet2 room-temp-as-k: {args.sheet2_room_temp_as_k}")
    print(f"Child Python: {py_exec}")
    print(f"Output dir: {out_dir}")
    print(f"Dry run: {args.dry_run}")
    print(f"Workers: {max(1, args.workers)}")

    run_items: List[Dict] = []
    total = len(mains)
    workers = max(1, int(args.workers or 1))
    if workers == 1:
        for i, main_pdf in enumerate(mains, 1):
            print(f"[{i}/{total}] RUN  {main_pdf}")
            item = run_one(
                py_exec=py_exec,
                main_pdf=main_pdf,
                si_dir=si_dir,
                args=args,
                out_dir=out_dir,
                api_key=api_key,
            )
            run_items.append(item)
            if item["status"] == "OK":
                print(f"[{i}/{total}] DONE status=OK")
            else:
                print(f"[{i}/{total}] FAIL rc={item['return_code']} log={item['wrapper_log']}")
    else:
        indexed_items: List[Optional[Dict]] = [None] * total
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {}
            for i, main_pdf in enumerate(mains, 1):
                print(f"[{i}/{total}] QUEUED  {main_pdf}")
                fut = executor.submit(
                    run_one,
                    py_exec=py_exec,
                    main_pdf=main_pdf,
                    si_dir=si_dir,
                    args=args,
                    out_dir=out_dir,
                    api_key=api_key,
                )
                future_to_idx[fut] = (i, main_pdf)
            for fut in concurrent.futures.as_completed(future_to_idx):
                i, main_pdf = future_to_idx[fut]
                try:
                    item = fut.result()
                except Exception as exc:
                    item = {
                        "main_pdf": str(main_pdf),
                        "out_dir": "",
                        "return_code": 1,
                        "status": "FAIL",
                        "wrapper_log": "",
                        "main_si_summary_json": "",
                        "merged_raw_json": "",
                        "exception": repr(exc),
                    }
                indexed_items[i - 1] = item
                if item["status"] == "OK":
                    print(f"[{i}/{total}] DONE status=OK")
                else:
                    print(f"[{i}/{total}] FAIL rc={item['return_code']} log={item.get('wrapper_log', '')}")
        run_items = [x for x in indexed_items if x is not None]

    merged_rows: List[Dict] = []
    for item in run_items:
        if item.get("status") != "OK":
            continue
        raw_path = Path(item["merged_raw_json"])
        rows = load_json_list(raw_path)
        merged_rows.extend(rows)

    batch_raw_json = out_dir / "batch_merged_raw_target_rows.json"
    batch_raw_json.write_text(json.dumps(merged_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "input_dir": str(input_dir),
        "si_dir": str(si_dir),
        "main_glob": args.main_glob,
        "recursive": bool(args.recursive),
        "pdf_parser": args.pdf_parser,
        "sample_filter": args.sample_filter,
        "dry_run": bool(args.dry_run),
        "total_main_pdfs": len(mains),
        "ok": sum(1 for x in run_items if x.get("status") == "OK"),
        "fail": sum(1 for x in run_items if x.get("status") == "FAIL"),
        "runs": run_items,
        "batch_merged_raw_json": str(batch_raw_json),
        "batch_merged_rows": len(merged_rows),
    }
    summary_json = out_dir / "batch_main_si_summary.json"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        print("=== Folder Main+SI Summary ===")
        print(f"Total mains: {len(mains)}")
        print(f"OK: {summary['ok']} | FAIL: {summary['fail']}")
        print("Dry-run mode: skip merged Excel.")
        print(f"Saved summary: {summary_json}")
        return 0 if summary["fail"] == 0 else 1

    if args.no_merge_excel:
        print("=== Folder Main+SI Summary ===")
        print(f"Total mains: {len(mains)}")
        print(f"OK: {summary['ok']} | FAIL: {summary['fail']}")
        print(f"Saved summary: {summary_json}")
        print("Skip merged Excel (--no-merge-excel).")
        return 0 if summary["fail"] == 0 else 1

    batch_xlsx = out_dir / "batch_main_plus_si_tables.xlsx"
    merge_log = out_dir / "batch_merge_excel.log"
    merge_rc = run_merge_excel(
        py_exec=py_exec,
        merged_raw_json=batch_raw_json,
        out_xlsx=batch_xlsx,
        sample_filter=args.sample_filter,
        out_log=merge_log,
    )

    final_xlsx = batch_xlsx
    backfill_table_rc: Optional[int] = 0
    backfill_method_rc: Optional[int] = None
    backfill_sheet2_rc: Optional[int] = None
    if merge_rc == 0 and args.post_backfill != "none":
        step1_xlsx = out_dir / "batch_main_plus_si_tables_step1_table.xlsx"
        step1_log = out_dir / "batch_backfill_table.log"
        backfill_table_rc = run_backfill_table(
            py_exec=py_exec,
            in_xlsx=batch_xlsx,
            reader_root=out_dir,
            out_xlsx=step1_xlsx,
            out_log=step1_log,
        )
        if backfill_table_rc == 0:
            final_xlsx = step1_xlsx
        if args.post_backfill == "table_method" and backfill_table_rc == 0:
            step2_xlsx = out_dir / "batch_main_plus_si_tables_step2_table_method.xlsx"
            step2_log = out_dir / "batch_backfill_method.log"
            backfill_method_rc = run_backfill_method(
                py_exec=py_exec,
                in_xlsx=step1_xlsx,
                reader_root=out_dir,
                out_xlsx=step2_xlsx,
                out_log=step2_log,
                sample_filter=args.sample_filter,
                allow_global=bool(args.method_backfill_allow_global),
            )
            if backfill_method_rc == 0:
                final_xlsx = step2_xlsx
            if (
                backfill_method_rc == 0
                and args.sheet2_method_backfill
            ):
                step3_xlsx = out_dir / "batch_main_plus_si_tables_step3_table_method_sheet2.xlsx"
                step3_log = out_dir / "batch_backfill_sheet2_method.log"
                backfill_sheet2_rc = run_backfill_method_sheet2(
                    py_exec=py_exec,
                    in_xlsx=step2_xlsx,
                    reader_root=out_dir,
                    out_xlsx=step3_xlsx,
                    out_log=step3_log,
                    sample_filter=args.sample_filter,
                    allow_global=bool(args.sheet2_backfill_allow_global),
                    room_temp_as_k=bool(args.sheet2_room_temp_as_k),
                )
                if backfill_sheet2_rc == 0:
                    final_xlsx = step3_xlsx

    print("=== Folder Main+SI Summary ===")
    print(f"Total mains: {len(mains)}")
    print(f"OK: {summary['ok']} | FAIL: {summary['fail']}")
    print(f"Merged rows: {len(merged_rows)}")
    print(f"Saved summary: {summary_json}")
    if merge_rc == 0:
        print(f"Saved merged Excel: {batch_xlsx}")
        if args.post_backfill != "none":
            if backfill_table_rc == 0:
                print(f"Saved step1 table-backfill Excel: {out_dir / 'batch_main_plus_si_tables_step1_table.xlsx'}")
            else:
                print(f"[WARN] Table backfill failed rc={backfill_table_rc}, see: {out_dir / 'batch_backfill_table.log'}")
            if args.post_backfill == "table_method":
                if backfill_method_rc == 0:
                    print(f"Saved step2 method-backfill Excel: {out_dir / 'batch_main_plus_si_tables_step2_table_method.xlsx'}")
                elif backfill_method_rc is not None:
                    print(f"[WARN] Method backfill failed rc={backfill_method_rc}, see: {out_dir / 'batch_backfill_method.log'}")
                elif backfill_table_rc != 0:
                    print("[WARN] Method backfill skipped because table backfill did not succeed.")
                if args.sheet2_method_backfill:
                    if backfill_sheet2_rc == 0:
                        print(f"Saved step3 sheet2-method-backfill Excel: {out_dir / 'batch_main_plus_si_tables_step3_table_method_sheet2.xlsx'}")
                    elif backfill_sheet2_rc is not None:
                        print(f"[WARN] Sheet2 method backfill failed rc={backfill_sheet2_rc}, see: {out_dir / 'batch_backfill_sheet2_method.log'}")
                    elif backfill_method_rc not in (0,):
                        print("[WARN] Sheet2 method backfill skipped because method backfill did not succeed.")
        print(f"Final output Excel: {final_xlsx}")
    else:
        print(f"[WARN] Merged Excel failed rc={merge_rc}, see: {merge_log}")

    ok = summary["fail"] == 0 and merge_rc == 0
    if args.post_backfill == "none":
        ok = summary["fail"] == 0 and merge_rc == 0
    elif args.post_backfill == "table":
        ok = summary["fail"] == 0 and merge_rc == 0 and backfill_table_rc == 0
    elif args.post_backfill == "table_method" and not args.sheet2_method_backfill:
        ok = summary["fail"] == 0 and merge_rc == 0 and backfill_table_rc == 0 and backfill_method_rc == 0
    elif args.post_backfill == "table_method" and args.sheet2_method_backfill:
        ok = (
            summary["fail"] == 0
            and merge_rc == 0
            and backfill_table_rc == 0
            and backfill_method_rc == 0
            and backfill_sheet2_rc == 0
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
