# exp5: 3 model pairs x {solo, paired} x the 5-instance astropy set, over OpenRouter.
# Budget-limited — the reserve stops the batch rather than a self-tracked spend total.
#
#   nohup scripts/run_batch.sh scripts/batches/exp5-cross-vendor.sh > exp5_batch.log 2>&1 &

OUT_ROOT="experiments/exp5/results"

INSTANCES=(
  astropy__astropy-12907
  astropy__astropy-14182
  astropy__astropy-14365
  astropy__astropy-14995
  astropy__astropy-6938
)

# label | gru model | minion model
PAIRS=(
  "qwen|openrouter/qwen/qwen3-max|openrouter/qwen/qwen3-coder-flash"
  "glm|openrouter/z-ai/glm-4.6|openrouter/z-ai/glm-4.5-air"
  "gpt|openrouter/openai/gpt-5-mini|openrouter/openai/gpt-4.1-nano"
)

# Solo first, deliberately: a budget cutoff mid-batch then always leaves complete
# (solo, paired) comparison groups behind, never a dangling half.
ARMS=(
  "solo|swe_bench_solo"
  "paired|swe_bench"
)

RESERVE="${RESERVE:-0.50}"
GRU_COST_LIMIT="${GRU_COST_LIMIT:-0.30}"
MINION_COST_LIMIT="${MINION_COST_LIMIT:-0.15}"
