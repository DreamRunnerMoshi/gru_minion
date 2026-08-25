#!/usr/bin/env bash
# exp5 cross-vendor batch: 3 model pairs x {solo, paired} x the 5-instance set.
# Runs ON the harness VM. Budget-aware: checks OpenRouter's real /credits balance
# before every run and stops launching new ones once the remaining balance drops
# below RESERVE, rather than trusting a self-tracked total (see NOTES.md — the
# credits endpoint is the authoritative source, self-tracking can drift).
#
# Order is deliberate: for each pair, for each instance, solo then paired — so a
# budget cutoff mid-batch always leaves complete (solo, paired) comparison pairs
# behind, never a dangling half-pair. Idempotent: skips any run whose
# cost_summary.json already exists, so it's safe to re-launch after an interrupt.
#
#   nohup scripts/exp5_batch.sh > exp5_batch.log 2>&1 &
set -uo pipefail

# nohup'd jobs don't inherit an activated venv — run_arm.sh got bitten by this
# before (see its own comment) and this batch just repeated the mistake once:
# a plain `command -v python3` fallback resolved to the system interpreter with
# none of the project's dependencies installed, and every run failed instantly
# on `ModuleNotFoundError: No module named 'datasets'`. Default explicitly to
# the venv this project's harness VMs actually use.
PYTHON="${PYTHON:-$HOME/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -d orchestrator && -d experiments ]] || { echo "run from the repo root" >&2; exit 2; }
[[ -f .env ]] && export "$(grep -v '^#' .env | xargs)"
[[ -n "${OPENROUTER_API_KEY:-}" ]] || { echo "OPENROUTER_API_KEY not set" >&2; exit 2; }

RESERVE="${RESERVE:-0.50}"          # stop launching once remaining balance < this
GRU_COST_LIMIT="${GRU_COST_LIMIT:-0.30}"
MINION_COST_LIMIT="${MINION_COST_LIMIT:-0.15}"

INSTANCES=(astropy__astropy-12907 astropy__astropy-14182 astropy__astropy-14365 astropy__astropy-14995 astropy__astropy-6938)

# label, gru_model, minion_model
PAIRS=(
  "qwen|openrouter/qwen/qwen3-max|openrouter/qwen/qwen3-coder-flash"
  "glm|openrouter/z-ai/glm-4.6|openrouter/z-ai/glm-4.5-air"
  "gpt|openrouter/openai/gpt-5-mini|openrouter/openai/gpt-4.1-nano"
)

OUT_ROOT="experiments/exp5/results"
mkdir -p "$OUT_ROOT"

remaining_balance() {
  curl -s https://openrouter.ai/api/v1/credits -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['total_credits']-d['total_usage'])"
}

check_budget() {
  local bal
  bal=$(remaining_balance) || { echo "  balance check failed, stopping to be safe" >&2; return 1; }
  echo "  remaining OpenRouter balance: \$${bal}"
  python3 -c "exit(0 if float('$bal') > float('$RESERVE') else 1)"
}

run_one() {
  local label="$1" gru_model="$2" minion_model="$3" mode="$4" inst="$5"
  local short="${inst#astropy__}"
  local gru_config="gru.yaml"
  [[ "$mode" == "solo" ]] && gru_config="gru-solo.yaml"
  local dir="${OUT_ROOT}/${label}-${mode}/${short}"

  if [[ -f "${dir}/cost_summary.json" ]]; then
    echo "--- ${label}/${mode}/${short}: already complete, skipping"
    return 0
  fi

  if ! check_budget; then
    echo "--- BUDGET EXHAUSTED (below \$${RESERVE} reserve) — stopping before ${label}/${mode}/${short}"
    return 1
  fi

  mkdir -p "$dir"
  echo "=== ${label}/${mode}/${short} | gru=${gru_model} minion=${minion_model} | $(date -u +%FT%TZ)"
  "$PYTHON" -m orchestrator.run_gru_session \
    --instance "$inst" \
    --gru-model "$gru_model" \
    --minion-model "$minion_model" \
    --gru-config "$gru_config" \
    --cost-limit "$GRU_COST_LIMIT" \
    --minion-cost-limit "$MINION_COST_LIMIT" \
    --output-dir "$dir" \
    > "${dir}/run.console.log" 2>&1
  local rc=$?
  echo "--- ${label}/${mode}/${short}: exit code $rc"
  return 0
}

echo "=== exp5 batch start | $(date -u +%FT%TZ) | reserve=\$${RESERVE} gru_cap=\$${GRU_COST_LIMIT} minion_cap=\$${MINION_COST_LIMIT}"
check_budget || { echo "already below reserve before starting — nothing to do"; exit 0; }

for pair in "${PAIRS[@]}"; do
  IFS='|' read -r LABEL GRU_MODEL MINION_MODEL <<< "$pair"
  for INST in "${INSTANCES[@]}"; do
    run_one "$LABEL" "$GRU_MODEL" "$MINION_MODEL" "solo" "$INST" || { echo "=== STOPPING BATCH (budget)"; exit 0; }
    run_one "$LABEL" "$GRU_MODEL" "$MINION_MODEL" "paired" "$INST" || { echo "=== STOPPING BATCH (budget)"; exit 0; }
  done
done

echo "=== exp5 batch complete | $(date -u +%FT%TZ) | final balance: \$$(remaining_balance)"
