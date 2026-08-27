#!/usr/bin/env bash
# Batch-evaluate whatever run_batch.sh actually completed, group by group, against the
# real SWE-bench harness. Safe to run partway through a budget-limited batch — only
# evaluates instances that actually finished (derived from what's in each merged
# predictions file, not a hardcoded list).
#
#   scripts/evaluate_batch.sh experiments/exp5/results experiments/exp5/reports exp5
#
# Generalized 2026-08-26 from exp5_evaluate.sh, which had exp5's own paths and the
# `*-solo`/`*-paired` arm names baked in. A "group" is now just any immediate
# subdirectory of the results root holding at least one completed run — which is what
# run_batch.sh's ${label}-${arm} directories are.
#
# SWE-bench only, by nature: GAIA has no separate evaluation pass, its scoring is an
# inline exact match written into each run's own prediction.json
# (orchestrator/benchmarks/gaia_scorer.py).
set -uo pipefail

RESULTS_ROOT="${1:?usage: evaluate_batch.sh <results-root> [report-dir] [run-id-prefix]}"
REPORT_DIR="${2:-${RESULTS_ROOT%/results}/reports}"
RUN_PREFIX="${3:-batch}"
DATASET="${DATASET:-SWE-bench/SWE-bench_Lite}"
SPLIT="${SPLIT:-test}"
MAX_WORKERS="${MAX_WORKERS:-4}"

# Same venv default as run_batch.sh — see its comment.
PYTHON="${PYTHON:-$HOME/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -d orchestrator && -d experiments ]] || { echo "run from the repo root" >&2; exit 2; }
[[ -d "$RESULTS_ROOT" ]] || { echo "no such results root: $RESULTS_ROOT" >&2; exit 2; }
mkdir -p "$REPORT_DIR"

for GROUP_DIR in "$RESULTS_ROOT"/*/; do
  GROUP_DIR="${GROUP_DIR%/}"
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
  # Use the SWE-bench/ mirror — princeton-nlp/SWE-bench_Lite lacks the `image` field and
  # fails with KeyError: 'image'.
  "$PYTHON" -m swebench.harness.run_evaluation \
    --predictions_path "$PRED_FILE" \
    --dataset_name "$DATASET" --split "$SPLIT" \
    --instance_ids $INSTANCE_IDS --max_workers "$MAX_WORKERS" \
    --run_id "${RUN_PREFIX}_${GROUP}" --report_dir "$REPORT_DIR"
done

echo "=== evaluation pass complete | $(date -u +%FT%TZ)"
echo "reports in ${REPORT_DIR}/"
