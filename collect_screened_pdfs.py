#!/usr/bin/env python3
import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect screened PDF files into one directory by status."
    )
    parser.add_argument(
        "--screening-json",
        required=True,
        help="Path to screening JSON (list of rows with path/status).",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Destination folder for collected PDFs.",
    )
    parser.add_argument(
        "--status",
        default="PASS",
        help="Comma-separated statuses to collect (default: PASS).",
    )
    parser.add_argument(
        "--mode",
        choices=["copy", "symlink"],
        default="copy",
        help="How to collect files (default: copy).",
    )
    return parser.parse_args()


def load_rows(path: Path) -> List[Dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        arr = obj.get("results") or obj.get("items") or []
        return [x for x in arr if isinstance(x, dict)]
    return []


def unique_path(dst_dir: Path, name: str) -> Path:
    base = Path(name).stem
    suffix = Path(name).suffix or ".pdf"
    out = dst_dir / f"{base}{suffix}"
    i = 1
    while out.exists():
        out = dst_dir / f"{base}__{i}{suffix}"
        i += 1
    return out


def main() -> int:
    args = parse_args()
    src_json = Path(args.screening_json).expanduser()
    if not src_json.exists():
        print(f"[ERROR] Screening JSON not found: {src_json}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    target_status: Set[str] = {
        s.strip().upper() for s in str(args.status).split(",") if s.strip()
    }
    if not target_status:
        print("[ERROR] --status is empty.", file=sys.stderr)
        return 2

    rows = load_rows(src_json)
    selected = []
    for row in rows:
        status = str(row.get("status", "")).strip().upper()
        path = row.get("path")
        if status in target_status and isinstance(path, str) and path.strip():
            selected.append((status, Path(path)))

    copied = 0
    missing = 0
    manifest = []
    for status, src in selected:
        src = src.expanduser()
        if not src.exists():
            missing += 1
            manifest.append(
                {"status": status, "src": str(src), "dst": "", "result": "missing"}
            )
            continue
        dst = unique_path(out_dir, src.name)
        if args.mode == "copy":
            shutil.copy2(src, dst)
        else:
            dst.symlink_to(src)
        copied += 1
        manifest.append(
            {"status": status, "src": str(src), "dst": str(dst), "result": args.mode}
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_json": str(src_json),
                "status_filter": sorted(target_status),
                "mode": args.mode,
                "total_rows": len(rows),
                "selected_rows": len(selected),
                "copied": copied,
                "missing": missing,
                "items": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("=== Collect Summary ===")
    print(f"Source JSON: {src_json}")
    print(f"Status filter: {sorted(target_status)}")
    print(f"Selected rows: {len(selected)}")
    print(f"Collected files: {copied}")
    print(f"Missing source files: {missing}")
    print(f"Output folder: {out_dir}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
