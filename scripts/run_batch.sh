#!/usr/bin/env bash
# Run a batch of Gru sessions: every (model pair x arm x instance) combination in a
# batch spec. Runs ON the harness VM.
#
#   nohup scripts/run_batch.sh scripts/batches/exp5-cross-vendor.sh > exp5_batch.log 2>&1 &
#
# Generalized 2026-08-26 from exp5_batch.sh, which was this machinery with exp5's own
# three model pairs, five instances and solo/paired arms hardcoded in it — so exp3's
# sweep needed a second script (run_arm.sh, now folded in here) and exp6's GAIA runs had
# no script at all. What varies per experiment now lives in a spec file under
# scripts/batches/; what varies per benchmark lives in orchestrator/config/<benchmark>/.
#
# The spec is a sourced bash file setting:
#   OUT_ROOT           where results go, e.g. experiments/exp5/results   (required)
#   INSTANCES=(...)    instance ids to run                               (required)
#   PAIRS=(...)        "label|gru-model|minion-model" per model pair     (required)
#   ARMS=(...)         "label|benchmark-spec" per arm, where benchmark-spec is what
#                      --benchmark takes ("gaia", "gaia/solo"). An empty arm label
#                      drops the suffix from the output path. Default: ("|swe_bench")
#   API_BASE           for self-hosted serving; omitted for hosted APIs   (optional)
#   RESERVE            stop launching once the OpenRouter balance drops below this;
#                      empty or unset disables the budget check entirely  (optional)
#   GRU_COST_LIMIT / MINION_COST_LIMIT   per-session dollar caps, 0 = use the config's
#
# Budget-aware when RESERVE is set: checks OpenRouter's real /credits balance before
# every run rather than trusting a self-tracked total (see exp5/NOTES.md — the credits
# endpoint is the authoritative source, self-tracking can drift).
#
# Arm order within an instance is deliberate and spec-controlled: exp5 lists solo before
# paired so a budget cutoff mid-batch always leaves complete comparison groups behind,
# never a dangling half. Idempotent: skips any run whose cost_summary.json already
# exists, so it's safe to re-launch after an interrupt.
set -uo pipefail

SPEC="${1:?usage: run_batch.sh <spec-file>   (see scripts/batches/)}"
[[ -f "$SPEC" ]] || { echo "no such spec: $SPEC" >&2; exit 2; }

# nohup'd jobs don't inherit an activated venv — this bit the project twice: a plain
# `command -v python3` fallback resolved to the system interpreter with none of the
# project's dependencies installed, and every run failed instantly on
# `ModuleNotFoundError: No module named 'datasets'`. Default explicitly to the venv this
# project's harness VMs actually use.
PYTHON="${PYTHON:-$HOME/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
[[ -d orchestrator && -d experiments ]] || { echo "run from the repo root" >&2; exit 2; }
[[ -f .env ]] && export "$(grep -v '^#' .env | xargs)"

ARMS=("|swe_bench")
API_BASE=""
RESERVE="${RESERVE:-}"
GRU_COST_LIMIT="${GRU_COST_LIMIT:-0}"
MINION_COST_LIMIT="${MINION_COST_LIMIT:-0}"
# shellcheck disable=SC1090
source "$SPEC"

: "${OUT_ROOT:?spec must set OUT_ROOT}"
[[ ${#INSTANCES[@]} -gt 0 ]] || { echo "spec must set INSTANCES" >&2; exit 2; }
[[ ${#PAIRS[@]} -gt 0 ]] || { echo "spec must set PAIRS" >&2; exit 2; }
[[ -z "$RESERVE" || -n "${OPENROUTER_API_KEY:-}" ]] || { echo "RESERVE set but OPENROUTER_API_KEY isn't" >&2; exit 2; }

mkdir -p "$OUT_ROOT"
export MSWEA_COST_TRACKING=ignore_errors

remaining_balance() {
  curl -s https://openrouter.ai/api/v1/credits -H "Authorization: Bearer ${OPENROUTER_API_KEY}" \
    | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['total_credits']-d['total_usage'])"
}

check_budget() {
  [[ -n "$RESERVE" ]] || return 0
  local bal
  bal=$(remaining_balance) || { echo "  balance check failed, stopping to be safe" >&2; return 1; }
  echo "  remaining OpenRouter balance: \$${bal}"
  python3 -c "exit(0 if float('$bal') > float('$RESERVE') else 1)"
}

run_one() {
  local label="$1" gru_model="$2" minion_model="$3" arm="$4" benchmark="$5" inst="$6"
  local short="${inst##*__}"
  local dir="${OUT_ROOT}/${label}${arm:+-$arm}/${short}"

  if [[ -f "${dir}/cost_summary.json" ]]; then
    echo "--- ${label}/${arm:-run}/${short}: already complete, skipping"
    return 0
  fi

  if ! check_budget; then
    echo "--- BUDGET EXHAUSTED (below \$${RESERVE} reserve) — stopping before ${label}/${arm:-run}/${short}"
    return 1
  fi

  mkdir -p "$dir"
  echo "=== ${label}/${arm:-run}/${short} | ${benchmark} | gru=${gru_model} minion=${minion_model} | $(date -u +%FT%TZ)"
  # Each instance is independent: one crash must not take the batch with it.
  "$PYTHON" -m orchestrator.run_session \
    --benchmark "$benchmark" \
    --instance "$inst" \
    --gru-model "$gru_model" \
    --minion-model "$minion_model" \
    ${API_BASE:+--api-base "$API_BASE"} \
    --cost-limit "$GRU_COST_LIMIT" \
    --minion-cost-limit "$MINION_COST_LIMIT" \
    --output-dir "$dir" \
    > "${dir}/run.console.log" 2>&1
  local rc=$?
  echo "--- ${label}/${arm:-run}/${short}: exit code $rc"
  return 0
}

echo "=== batch start | $(basename "$SPEC") | $(date -u +%FT%TZ) | reserve=${RESERVE:-off} gru_cap=\$${GRU_COST_LIMIT} minion_cap=\$${MINION_COST_LIMIT}"
check_budget || { echo "already below reserve before starting — nothing to do"; exit 0; }

for pair in "${PAIRS[@]}"; do
  IFS='|' read -r LABEL GRU_MODEL MINION_MODEL <<< "$pair"
  for INST in "${INSTANCES[@]}"; do
    for armspec in "${ARMS[@]}"; do
      IFS='|' read -r ARM BENCHMARK <<< "$armspec"
      run_one "$LABEL" "$GRU_MODEL" "$MINION_MODEL" "$ARM" "$BENCHMARK" "$INST" \
        || { echo "=== STOPPING BATCH (budget)"; exit 0; }
    done
  done
done

echo "=== batch complete | $(date -u +%FT%TZ)${RESERVE:+ | final balance: \$$(remaining_balance)}"
echo "Next: scripts/verify_artifacts.py ${OUT_ROOT}  — BEFORE destroying anything."
