#!/usr/bin/env bash
# Batch-evaluate whatever exp5_batch.sh actually completed. Safe to run partway
# through a budget-limited batch — only evaluates instances that actually finished
# (derived from what's in each merged predictions file, not a hardcoded list).
#
#   scripts/exp5_evaluate.sh
set -uo pipefail

# Same venv default as exp5_batch.sh — see its comment.
PYTHON="${PYTHON:-$HOME/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -d orchestrator && -d experiments ]] || { echo "run from the repo root" >&2; exit 2; }

RESULTS_ROOT="experiments/exp5/results"
REPORT_DIR="experiments/exp5/reports"
mkdir -p "$REPORT_DIR"

for GROUP_DIR in "$RESULTS_ROOT"/*-solo "$RESULTS_ROOT"/*-paired; do
  [[ -d "$GROUP_DIR" ]] || continue
  GROUP="$(basename "$GROUP_DIR")"

  # Needs at least one completed instance dir to merge anything.
  if ! ls "$GROUP_DIR"/*/cost_summary.json >/dev/null 2>&1; then
    echo "--- ${GROUP}: no completed runs yet, skipping"
    continue
  fi

  echo "=== merging predictions for ${GROUP}"
  "$PYTHON" -m orchestrator.analyze_run --results-dir "$GROUP_DIR" || { echo "  merge failed for ${GROUP}" >&2; continue; }

  PRED_FILE="${GROUP_DIR}/predictions_${GROUP}.json"
  [[ -f "$PRED_FILE" ]] || { echo "  no predictions file produced for ${GROUP}" >&2; continue; }

  INSTANCE_IDS=$("$PYTHON" -c "import json; print(' '.join(json.load(open('${PRED_FILE}')).keys()))")
  [[ -n "$INSTANCE_IDS" ]] || { echo "  ${GROUP}: predictions file is empty" >&2; continue; }

  echo "=== evaluating ${GROUP} on: ${INSTANCE_IDS}"
  "$PYTHON" -m swebench.harness.run_evaluation \
    --predictions_path "$PRED_FILE" \
    --dataset_name SWE-bench/SWE-bench_Lite --split test \
    --instance_ids $INSTANCE_IDS --max_workers 4 \
    --run_id "exp5_${GROUP}" --report_dir "$REPORT_DIR"
done

echo "=== exp5 evaluation pass complete | $(date -u +%FT%TZ)"
echo "reports in ${REPORT_DIR}/"
