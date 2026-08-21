# Experiment 1 — supporting notes

Methodology and worked numbers behind the terse Findings bullets in [LOG.md](./LOG.md). Read this only if you need to check how a number was derived or whether it's measured vs. estimated — `LOG.md` alone should be enough for everything else.

## #throughput — measured completion-tok/s

First data point for the gap flagged in [design/infra/04-machine-config.md](../../design/infra/04-machine-config.md) §Gaps ("Qwen3.8-27B's actual tok/s throughput on an RTX 3090 specifically wasn't found"). The 4 batch instances (precise start/end timestamps available) generated 30,432 completion tokens over 1,881s wall-clock ≈ **16.2 completion-tok/s blended average**.

This is well below the design doc's 55 tok/s figure for a 32B model — expected, not contradictory: that figure was pure decode throughput on a short/fixed context, while this run's wall-clock is dominated by prompt *prefill* cost on a growing multi-turn conversation (contexts grew past 24K tokens per `ollama.log`). This is llama.cpp-family (Ollama's backend), not vLLM/SGLang — same caveat the design doc already applies to its own §4 source.

## #effective-cost — measured $/M tokens

$0.1161 GPU rental (≈0.75hr × $0.1548/hr) ÷ 1.196M total tokens ≈ **$0.097/M tokens blended** for this run — cheaper than every API comparator in [design/infra/04-machine-config.md](../../design/infra/04-machine-config.md) §5.

**Not the same claim §6-8 of that doc pressure-tested**: this is amortized over a single sequential run at low GPU utilization, not the "same model at scale" breakeven question, and this run's tokens were 97% prompt / 3% completion, which changes the shape of the comparison versus that section's output-token-only framing. A first real number, not a verdict.

## #tool-call-breakdown — what completion tokens are actually spent on

| | Tokens | Share |
|---|---|---|
| Completion (generation) side | 36,745 | 100% |
| — tool-call payload (bash command JSON) | ~30,452 | ~83% |
| — reasoning/thought text (`content` field) | ~6,293 | ~17% |

Naive read: "83% is cheap mechanical JSON, 17% is the real thinking." **Checked against actual command content, that's wrong.** Of 122 tool calls across the run, 38 (31% of calls) embed multi-line Python — repro scripts, inline fix attempts, verification snippets — and those 38 account for **73% of tool-call character volume** (21,883 of 29,893 chars), against 27% for the 84 short, single-purpose shell calls (`cd`, `grep`, `cat`, `ls`, ...).

So most of the 83% *is* the model's real diagnostic and fix-drafting work, just expressed as executable code inside the tool call rather than as prose in `content`. This model's `content` field, per the swebench.yaml system prompt's "brief THOUGHT + a tool call" instruction, is mostly terse status lines ("All 11 tests passed, submitting patch") — the reasoning doesn't live there. Don't read the completion-side split as "generation is mostly cheap boilerplate a lesser model could skip."

## #cache-estimate — cache-hit %, and why it's estimated not measured

litellm/Ollama's OpenAI-compatible `usage` object left `prompt_tokens_details` as `None` for every call this run, so no per-call cache-hit count was captured through the API, and both vast.ai instances were destroyed before this gap was noticed — no way to go get the real number now. (This is exactly the mistake [EXPERIMENT_LOG_FORMAT.md](../../EXPERIMENT_LOG_FORMAT.md)'s Results section now warns about: capture cache stats live, during the run.)

**Reconstruction method**: the conversation only ever grows (nothing is edited or removed), so each call's prompt is a strict superset of the previous call's prompt + completion. Modeling perfect prefix-cache reuse — `reused = min(prev_prompt + prev_completion, current_prompt)` — gives an estimated upper bound:

| Instance | Calls | Prompt tok | ~Cached (reused) | ~New (computed) | Est. cache-hit |
|---|---|---|---|---|---|
| astropy-12907 | 14 | 119,053 | 112,890 | 6,163 | 94.8% |
| astropy-14182 | 27 | 509,266 | 492,878 | 16,388 | 96.8% |
| astropy-14365 | 11 | 38,684 | 34,890 | 3,794 | 90.2% |
| astropy-14995 | 16 | 145,707 | 135,911 | 9,796 | 93.3% |
| astropy-6938 | 40 | 346,147 | 337,976 | 8,171 | 97.6% |
| **Total** | 108 | 1,158,857 | 1,114,545 | 44,312 | **96.2%** |

**Cross-check**: one real sample glimpsed live in `ollama.log` mid-run — `cached n_tokens = 24298` out of a 24,675-token prompt, 98.5% — is consistent with this table's range. Reassuring, not confirmation across the full run.

**Why it's an upper bound, not just an estimate**: `ollama.log` also showed llama.cpp evicting context checkpoints during the longest conversation (`erasing context checkpoint too close to an earlier one`, checkpoint slots capped at 32) — real cache-hit for `astropy-14182` (27 calls, the longest) is plausibly somewhat below the 96.8% shown here.

**Why it matters for minion delegation**: if minion inherits this same flat resend-everything loop, its *reported* token bill will look dominated by replaying its own prior tool outputs (32:1 prompt:completion this run) — but on self-hosted inference with cache reuse this high, the real marginal GPU cost is far below what the raw token count implies. That distinction mostly disappears against a metered API, which typically bills full prompt tokens per call regardless of server-side prefix caching (some offer cache discounts — e.g. Claude's ~90% cached-input pricing, [design/infra/04-machine-config.md](../../design/infra/04-machine-config.md) §5 — but that's not universal). So the resend-everything architecture is a much smaller cost problem for a self-hosted minion than an API-billed one — a lever independent of which model runs, worth keeping distinct from the #tool-call-breakdown finding (which is about generation cost, not consumption cost) when Phase 2's A/B/C/D ablation compares self-hosted vs. API minion cost.
