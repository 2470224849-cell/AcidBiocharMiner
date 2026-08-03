#!/usr/bin/env bash
set -euo pipefail

# Frozen extraction settings (v1):
# - parser: docling (strict)
# - sample_filter: acid_pristine
# - no post-backfill; no batch-level merged Excel
# - skip-existing for resume
#
# Usage:
#   bash run_fixed_extract_batch.sh <LIMIT> <OUT_DIR> <INPUT_DIR>
#
# Example:
#   bash run_fixed_extract_batch.sh 20 output/frozen_v1 data/articles

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIMIT="${1:-}"
OUT_DIR="${2:-}"
INPUT_DIR="${3:-}"
WORKERS="${WORKERS:-3}"
PYTHON_EXEC="${PYTHON_EXEC:-${ROOT_DIR}/.venv/bin/python}"

if [[ -z "${LIMIT}" || -z "${OUT_DIR}" || -z "${INPUT_DIR}" ]]; then
  echo "Usage: bash run_fixed_extract_batch.sh <LIMIT> <OUT_DIR> <INPUT_DIR>"
  exit 1
fi

if ! [[ "${LIMIT}" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] LIMIT must be an integer."
  exit 1
fi

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "[ERROR] DEEPSEEK_API_KEY is empty. Export it first."
  exit 1
fi

if [[ ! -x "${PYTHON_EXEC}" ]]; then
  echo "[ERROR] Python executable not found: ${PYTHON_EXEC}"
  echo "Set PYTHON_EXEC or create .venv as described in README.md."
  exit 1
fi

cd "${ROOT_DIR}"
mkdir -p "${OUT_DIR}"

HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-0}" "${PYTHON_EXEC}" -u run_folder_main_si_extract.py \
  --input-dir "${INPUT_DIR}" \
  --si-dir "${INPUT_DIR}" \
  --main-glob "主文_*.pdf" \
  --recursive \
  --pdf-parser docling \
  --strict-docling \
  --sample-filter acid_pristine \
  --post-backfill none \
  --no-merge-excel \
  --skip-existing \
  --workers "${WORKERS}" \
  --limit "${LIMIT}" \
  --out-dir "${OUT_DIR}" \
  > "${OUT_DIR}/run_extract_limit_${LIMIT}.log" 2>&1

echo "[OK] Extraction batch finished."
echo "Log: ${OUT_DIR}/run_extract_limit_${LIMIT}.log"
