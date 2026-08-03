#!/usr/bin/env bash
set -euo pipefail

# Frozen postprocess settings (v1):
# 1) export_target_excel (acid_pristine)
# 2) backfill_sheet1_from_reader_tables
# 3) backfill_sheet1_from_method_text (allow_global = false)
# 4) backfill_sheet2_from_method_text (allow_global = true, room_temp_as_k = true)
#
# Usage:
#   bash run_fixed_postprocess.sh <OUT_DIR>
#
# Example:
#   bash run_fixed_postprocess.sh output/frozen_v1

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${1:-}"
PYTHON_EXEC="${PYTHON_EXEC:-${ROOT_DIR}/.venv/bin/python}"

if [[ -z "${OUT_DIR}" ]]; then
  echo "Usage: bash run_fixed_postprocess.sh <OUT_DIR>"
  exit 1
fi

RAW_JSON="${OUT_DIR}/batch_merged_raw_target_rows.json"
BASE_XLSX="${OUT_DIR}/batch_main_plus_si_tables.xlsx"
STEP1_XLSX="${OUT_DIR}/batch_main_plus_si_tables_step1_table.xlsx"
STEP2_XLSX="${OUT_DIR}/batch_main_plus_si_tables_step2_table_method.xlsx"
STEP3_XLSX="${OUT_DIR}/batch_main_plus_si_tables_step3_table_method_sheet2.xlsx"
FINAL_XLSX="${OUT_DIR}/batch_main_plus_si_tables_FINAL.xlsx"

if [[ ! -f "${RAW_JSON}" ]]; then
  echo "[ERROR] Missing raw json: ${RAW_JSON}"
  exit 1
fi

if [[ ! -x "${PYTHON_EXEC}" ]]; then
  echo "[ERROR] Python executable not found: ${PYTHON_EXEC}"
  echo "Set PYTHON_EXEC or create .venv as described in README.md."
  exit 1
fi

cd "${ROOT_DIR}"

# Step 0: merge/export
"${PYTHON_EXEC}" export_target_excel.py \
  --raw-json "${RAW_JSON}" \
  --xlsx "${BASE_XLSX}" \
  --sample-filter acid_pristine \
  --no-fill-unresolved-sample-id \
  > "${OUT_DIR}/post_step0_export.log" 2>&1

# Step 1: table backfill
"${PYTHON_EXEC}" backfill_sheet1_from_reader_tables.py \
  --xlsx "${BASE_XLSX}" \
  --reader-root "${OUT_DIR}" \
  --out-xlsx "${STEP1_XLSX}" \
  --log "${OUT_DIR}/post_step1_table.details.json" \
  > "${OUT_DIR}/post_step1_table.log" 2>&1

# Step 2: method backfill (sheet1)
"${PYTHON_EXEC}" backfill_sheet1_from_method_text.py \
  --xlsx "${STEP1_XLSX}" \
  --reader-root "${OUT_DIR}" \
  --sample-filter acid_pristine \
  --out-xlsx "${STEP2_XLSX}" \
  --log "${OUT_DIR}/post_step2_method.details.json" \
  > "${OUT_DIR}/post_step2_method.log" 2>&1

# Step 3: method backfill (sheet2)
"${PYTHON_EXEC}" backfill_sheet2_from_method_text.py \
  --xlsx "${STEP2_XLSX}" \
  --reader-root "${OUT_DIR}" \
  --sample-filter acid_pristine \
  --allow-global \
  --room-temp-as-k \
  --out-xlsx "${STEP3_XLSX}" \
  --log "${OUT_DIR}/post_step3_sheet2.details.json" \
  > "${OUT_DIR}/post_step3_sheet2.log" 2>&1

cp -f "${STEP3_XLSX}" "${FINAL_XLSX}"

echo "[OK] Postprocess finished."
echo "Final: ${FINAL_XLSX}"
