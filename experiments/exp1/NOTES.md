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

## #external-literature-cross-check — how exp1's numbers compare to published findings

Started from the question "how many tokens are real reasoning vs. tool-call mechanics, based on our experiment?" — a short literature pass turned up 5 papers, written up in full in [literature-review/](../../literature-review/README.md#token-efficiency--reasoning-vs-tool-call-cost-feeds-experimentsexp1notesmd). Summary of how each connects to exp1's own numbers:

- **[Reasoning not required for tool calls](../../literature-review/2605.09252-reasoning-not-required-for-tool-calls.md)**: a model's hidden state reportedly already "knows" whether a tool call is needed before generating explicit reasoning about it (AUROC 0.89-0.96 across 6 models); skipping the verbalization cut tool calls 48% for 1.7% accuracy loss in that paper's setup. This complicates the #tool-call-breakdown correction above — that correction showed the `content` field's ~6,293 tokens and the embedded-script tokens are both genuine work, but this paper suggests *some* of even the `content`-field reasoning could, in principle, be narrating an already-made decision rather than producing it. **Untested for Qwen3.8-27B/SWE-bench specifically** — would need a controlled ablation (strip or compress `content`, measure resolve-rate delta) to know if this transfers here.
- **[CodeAgents](../../literature-review/2507.03254-codeagents-codified-reasoning-efficiency.md)**: independently confirms, on different benchmarks (GAIA/HotpotQA/VirtualHome), that code-based reasoning beats natural-language CoT on both token cost (40-87% less) *and* accuracy. This is external support for the #tool-call-breakdown correction's core claim — that Qwen embedding diagnostic Python scripts in 31% of its tool calls (73% of tool-call token volume) is a token-efficient reasoning medium, not mechanical overhead competing with "real" prose reasoning.
- **[Token Economics for LLM Agents](../../literature-review/2605.09104-token-economics-llm-agents.md)**: reports input:output ratios **exceeding 150:1** on SWE tasks in production, well above exp1's measured 32:1 — suggesting exp1's ratio, while already dramatic, may be on the low end for this task family, plausibly because Lite-tier instances and Qwen's relatively short trajectories (11-40 calls) bounded context growth more than a longer production run would. Also reports **up to 30× token-usage variance across repeated runs of the same task** — a caveat exp1 doesn't have any data on, since every instance ran exactly once. Worth building repeat-runs into Phase 2's ablation design if the cost numbers there need to be trustworthy rather than illustrative.
- **[Agentic AI Workload Characteristics](../../literature-review/2605.26297-agentic-workload-characteristics.md)**: qualitatively corroborates both the #cache-estimate section above (effective caching makes execution "decode-dominated," matching exp1's ~96% estimated cache-hit) and the explore-then-execute command pattern visible in exp1's own trajectories (early `find`/`grep`/`cat`, later diagnostic scripts, final patch). Numbers weren't extractable from this paper in this pass — corroboration is qualitative, not a numeric confirmation of exp1's specific 96.2% figure.
- **[Notation Matters](../../literature-review/2605.29676-notation-matters-tool-call-formats.md)**: incomplete — flags a potential fourth cost lever (tool-call notation format, JSON vs. alternatives) but the actual benchmark numbers didn't parse through automated fetching. Placeholder, not a finding.

**Net read**: exp1's own two findings — (1) tool-call payload is mostly genuine reasoning-via-code, not boilerplate, and (2) prompt-side cost is dominated by cacheable context replay — both have independent support in the literature, at broadly similar or even more extreme magnitudes. The one open question the literature raises that exp1 can't currently answer is whether Qwen3.8-27B's explicit `content`-field reasoning is fully load-bearing or partly redundant with information already implicit in its hidden state before generation — that would need a dedicated ablation, not just more literature reading.
