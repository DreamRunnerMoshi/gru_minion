#!/usr/bin/env bash
# Run one exp3 config over all instances. Runs ON the harness VM.
#
#   nohup scripts/run_arm.sh B gru.yaml ollama_chat/qwen3.8:27b http://<gpu-ip>:<port> > run_B.log 2>&1 &
#
# nohup + a remote-side redirect is deliberate: a dropped SSH connection silently
# stops a local-side `ssh cmd > file` pipe while the remote process keeps running,
# which cost a run in exp2. Poll the log over fresh connections instead.
#
# Revised 2026-08-24: took an explicit gru-config filename instead of a hardcoded
# A/B->config lookup table (A was gru-taxonomy.yaml, the old type-taxonomy prompt —
# deleted; deferred per exp3/LOG.md's Conclusion and never actually run). A new
# variant no longer needs a case added here — just pass its filename.
set -uo pipefail

# Use the venv explicitly rather than whatever python3 resolves to — nohup'd jobs
# have bitten this project before by not inheriting an activated environment.
PYTHON="${PYTHON:-$(command -v python3)}"
[[ -d orchestrator && -d experiments ]] || { echo "run from the repo root" >&2; exit 2; }

LABEL="${1:?usage: run_arm.sh <label> <gru-config.yaml> <model> <api-base>}"
GRU_CONFIG="${2:?}"
MODEL="${3:?}"
API_BASE="${4:?}"
INSTANCES=(astropy__astropy-12907 astropy__astropy-14182 astropy__astropy-14365 astropy__astropy-14995 astropy__astropy-6938)

[[ -f "orchestrator/config/${GRU_CONFIG}" ]] || { echo "no such config: orchestrator/config/${GRU_CONFIG}" >&2; exit 2; }

OUT_ROOT="experiments/exp3/results/${LABEL}"
mkdir -p "$OUT_ROOT"
export MSWEA_COST_TRACKING=ignore_errors

echo "=== exp3 ${LABEL} | config ${GRU_CONFIG} | model ${MODEL} | $(date -u +%FT%TZ)"
FAILED=()
for INST in "${INSTANCES[@]}"; do
  SHORT="${INST#astropy__}"
  DIR="${OUT_ROOT}/${SHORT}"
  if [[ -f "${DIR}/cost_summary.json" ]]; then
    echo "--- ${SHORT}: already complete, skipping"; continue
  fi
  echo "--- ${SHORT}: starting $(date -u +%FT%TZ)"
  # Each instance is independent: one crash must not take the batch with it.
  "$PYTHON" -m orchestrator.run_gru_session \
      --instance "$INST" --model "$MODEL" --api-base "$API_BASE" \
      --gru-config "$GRU_CONFIG" --output-dir "$DIR" \
      > "${OUT_ROOT}/${SHORT}.console.log" 2>&1
  RC=$?
  if [[ $RC -ne 0 ]]; then
    echo "--- ${SHORT}: EXIT ${RC} (see ${SHORT}.console.log)"; FAILED+=("$SHORT")
  else
    echo "--- ${SHORT}: done $(date -u +%FT%TZ)"
  fi
done

echo "=== ${LABEL} finished $(date -u +%FT%TZ)"
[[ ${#FAILED[@]} -gt 0 ]] && echo "FAILED: ${FAILED[*]}"
echo "Next: scripts/verify_artifacts.py ${OUT_ROOT}  — BEFORE destroying anything."
