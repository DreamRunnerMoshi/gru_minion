# exp6: the GAIA pilot. Same architecture and prompt as the SWE-bench batches — only
# benchmark spec differs (orchestrator/config/gaia/benchmark.yaml), which is the
# whole point of the port. Needs orchestrator/benchmarks/gaia_sandbox built as a local
# Docker image, plus HF_TOKEN (gated dataset) and TAVILY_API_KEY (the sandbox's search).
#
#   nohup scripts/run_batch.sh scripts/batches/exp6-gaia.sh > exp6_batch.log 2>&1 &

OUT_ROOT="experiments/exp6/results"

# Task ids from orchestrator/benchmarks/gaia_dataset.py's deterministic pilot pick:
#   python -m orchestrator.benchmarks.gaia_dataset
INSTANCES=(
)

PAIRS=(
  "glm|openrouter/z-ai/glm-4.6|openrouter/z-ai/glm-4.5-air"
)

ARMS=(
  "solo|gaia/solo"
  "paired|gaia"
)

RESERVE="${RESERVE:-0.50}"
GRU_COST_LIMIT="${GRU_COST_LIMIT:-0.30}"
MINION_COST_LIMIT="${MINION_COST_LIMIT:-0.15}"
