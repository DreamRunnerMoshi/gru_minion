# exp3 arm B: one self-hosted model in both roles over the 5-instance astropy set.
# Was scripts/run_arm.sh before 2026-08-26 — the same sweep, minus the budget check
# (a self-hosted Ollama instance has no OpenRouter balance to watch).
#
#   OLLAMA_API_BASE=http://<gpu-ip>:<port> \
#     nohup scripts/run_batch.sh scripts/batches/exp3-arm-b.sh > run_B.log 2>&1 &
#
# nohup + a remote-side redirect is deliberate: a dropped SSH connection silently stops
# a local-side `ssh cmd > file` pipe while the remote process keeps running, which cost
# a run in exp2. Poll the log over fresh connections instead.

OUT_ROOT="experiments/exp3/results"

INSTANCES=(
  astropy__astropy-12907
  astropy__astropy-14182
  astropy__astropy-14365
  astropy__astropy-14995
  astropy__astropy-6938
)

MODEL="${MODEL:-ollama_chat/qwen3.8:27b}"
PAIRS=("B|${MODEL}|${MODEL}")

# One arm, no label — results land in experiments/exp3/results/B/<instance>/.
ARMS=("|swe_bench")

API_BASE="${OLLAMA_API_BASE:?set OLLAMA_API_BASE to the serving instance}"
RESERVE=""
