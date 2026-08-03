#!/usr/bin/env bash
set -euo pipefail

# Run frozen postprocess on all batch output directories under a root.
# A valid batch output directory contains: batch_merged_raw_target_rows.json
#
# Usage:
#   bash run_fixed_postprocess_all.sh <OUTPUT_ROOT>
#
# Example:
#   bash run_fixed_postprocess_all.sh output

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_ROOT="${1:-}"

if [[ -z "${OUTPUT_ROOT}" ]]; then
  echo "Usage: bash run_fixed_postprocess_all.sh <OUTPUT_ROOT>"
  exit 1
fi

if [[ ! -d "${OUTPUT_ROOT}" ]]; then
  echo "[ERROR] Directory not found: ${OUTPUT_ROOT}"
  exit 1
fi

cd "${ROOT_DIR}"

TARGET_DIRS=()
while IFS= read -r line; do
  TARGET_DIRS+=("${line}")
done < <(
  find "${OUTPUT_ROOT}" -type f -name "batch_merged_raw_target_rows.json" -print \
    | sed 's#/batch_merged_raw_target_rows.json$##' \
    | sort
)

if [[ ${#TARGET_DIRS[@]} -eq 0 ]]; then
  echo "[WARN] No batch directories found under: ${OUTPUT_ROOT}"
  exit 0
fi

echo "Found ${#TARGET_DIRS[@]} batch directories."

ok=0
fail=0
for d in "${TARGET_DIRS[@]}"; do
  echo
  echo "[RUN] ${d}"
  if bash "${ROOT_DIR}/run_fixed_postprocess.sh" "${d}"; then
    echo "[OK]  ${d}"
    ok=$((ok + 1))
  else
    echo "[FAIL] ${d}"
    fail=$((fail + 1))
  fi
done

echo
echo "=== Postprocess-All Summary ==="
echo "Total: ${#TARGET_DIRS[@]} | OK: ${ok} | FAIL: ${fail}"
exit 0
