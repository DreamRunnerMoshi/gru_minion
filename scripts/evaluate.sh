#!/usr/bin/env bash
# Evaluate exp3 arm B AND re-verify exp2 in one pass, then build the results table.
# Runs on a Docker-capable machine (the harness VM, or a fresh GPU-less VM).
#
#   scripts/evaluate.sh B ollama_chat/qwen3.8:27b
#
# exp2 is bundled deliberately: it grades the same five astropy instances, so the
# expensive part (pulling per-instance images) is paid once and serves both, and both
# verdicts then come from the same harness version — which matters because exp3's
# headline gate is a comparison against exp2. exp2's own verdict is currently
# transcribed for 4 of 5 instances (review.md R3).
set -uo pipefail

ARM="${1:?usage: evaluate.sh <results-label> <model-string>}"
MODEL="${2:?}"
INSTANCES="astropy__astropy-12907 astropy__astropy-14182 astropy__astropy-14365 astropy__astropy-14995 astropy__astropy-6938"
PYTHON="${PYTHON:-$(command -v python3)}"
[[ -d orchestrator && -d experiments ]] || { echo "run from the repo root" >&2; exit 2; }

RESULTS="experiments/exp3/results/${ARM}"
REPORT_DIR="experiments/exp3/reports"
mkdir -p "$REPORT_DIR"
# swebench names the report {model_name_or_path with / -> __}.{run_id}.json — exp2 lost
# its report by not knowing where it landed, so pin the directory and derive the name.
SAFE_MODEL="${MODEL//\//__}"

echo "=== 1/4  merge exp3 arm ${ARM} predictions"
"$PYTHON" -m orchestrator.analyze_run --results-dir "$RESULTS" || exit 1

echo "=== 2/4  evaluate exp3 arm ${ARM}"
"$PYTHON" -m swebench.harness.run_evaluation \
  --predictions_path "${RESULTS}/predictions_${ARM}.json" \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --instance_ids $INSTANCES --max_workers 4 \
  --run_id "exp3_${ARM}" --report_dir "$REPORT_DIR"
EXP3_REPORT="${REPORT_DIR}/${SAFE_MODEL}.exp3_${ARM}.json"

echo "=== 3/4  re-verify exp2 (closes review.md R3)"
"$PYTHON" -m swebench.harness.run_evaluation \
  --predictions_path experiments/exp2/results/predictions_all5.json \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --instance_ids $INSTANCES --max_workers 4 \
  --run_id exp2_reverify --report_dir "$REPORT_DIR"
EXP2_REPORT="${REPORT_DIR}/${SAFE_MODEL}.exp2_reverify.json"

echo "=== 4/4  build the exp3 results table"
if [[ -f "$EXP3_REPORT" ]]; then
  "$PYTHON" -m orchestrator.analyze_run --results-dir "$RESULTS" --eval-report "$EXP3_REPORT"
else
  echo "WARNING: expected report not at ${EXP3_REPORT} — check ${REPORT_DIR}/ and rerun analyze_run with the right path" >&2
  ls -la "$REPORT_DIR" >&2
fi

echo
echo "=== verdicts"
for R in "$EXP3_REPORT" "$EXP2_REPORT"; do
  [[ -f "$R" ]] && "$PYTHON" - "$R" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
print(f"  {sys.argv[1]}")
print(f"    resolved {r['resolved_instances']}/{r['total_instances']}  -> {sorted(r.get('resolved_ids', []))}")
PY
done
echo
echo "Next: paste ${RESULTS}/results_table.md into experiments/exp3/LOG.md."
echo "If exp2_reverify disagrees with the transcribed 3/5, update exp2/LOG.md and review.md R3."
