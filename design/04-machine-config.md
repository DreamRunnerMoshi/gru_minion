# Component 4: Machine Config — Self-Hosted Minion Inference on vast.ai

Status: research pass complete, not yet run as an experiment. Companion to [DESIGN.md](../DESIGN.md) and [EXPERIMENT_LOG_FORMAT.md](../EXPERIMENT_LOG_FORMAT.md) — this covers whether the minion tier should run as self-hosted open-weight inference on rented GPUs instead of a paid API, a different axis from [01](./01-planning.md)/[02](./02-gru-minion-protocol.md)/[03](./03-graph-orchestration.md), which are all about *what* Gru and minions do, not *where the minion's weights live*.

Question asked: the user's hypothesis is "deploying [minion] models locally [on vast.ai] I think will be cheaper [than API]." Pressure-test this with real numbers, the way [DESIGN.md](../DESIGN.md)'s Augment/Stencil counter-example pressure-tests "split-model setups are automatically cheaper" (they aren't, there — it was 14% *more* expensive for the same accuracy).

## 1. What this changes vs. Experiment 0

[experiments/exp0/LOG.md](../experiments/exp0/LOG.md) already used a vast.ai VM — but only as a cheap generic compute box to run mini-swe-agent, which called out to OpenRouter's API for `claude-haiku-4.5`. The GPU on that instance (a Quadro P4000, 8GB) was incidental — part of whatever cheapest VM offer vast.ai matched, never used for inference. This doc is about a categorically different setup: renting a GPU specifically to load minion model *weights* onto it and serve them locally (vLLM/SGLang/TGI), replacing the per-token API call with a self-hosted server the orchestrator calls instead.

## 2. Candidate minion models and VRAM

Single-GPU-rentable range, coding-capable, open-weight:

| Model | Params | VRAM (fp16) | VRAM (INT4/AWQ) | Fits on |
|---|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | 7B | ~16GB | ~5-6GB | RTX 3090/4090 comfortably |
| Qwen2.5-Coder-14B-Instruct | 14B | ~30GB | ~10GB | RTX 3090/4090 (AWQ), needs quantization for a single 24GB card |
| Qwen2.5-Coder-32B-Instruct | 32B | ~71GB ([Qwen2.5-Coder-32B-Instruct discussion](https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct/discussions/28), [Spheron VRAM tool](https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen2.5-Coder-32B-Instruct/)) | ~18GB ([Spheron](https://www.spheron.network/tools/gpu-recommender/Qwen/Qwen2.5-Coder-32B-Instruct/)) | needs A100-80GB+ at fp16; fits a single RTX 3090/4090 (24GB) at INT4/AWQ |

32B at fp16 needs data-center-class VRAM; quantized it fits the same consumer 24GB cards as the 7B/14B tiers, at the usual quantization-accuracy tradeoff (not measured here — flagged, not assumed away). Qwen3-Coder-specific VRAM figures weren't found in this pass (search returned mostly Qwen2.5-Coder data); treat Qwen3-Coder sizing as directionally similar to Qwen2.5-Coder until confirmed.

**Out of scope for single-GPU self-hosting**: DeepSeek-V4/V3.2 — 685B-parameter MoE, floor of 8×H100 SXM5 (640GB) just to serve, 8×H200 recommended for full context ([Spheron](https://www.spheron.network/blog/deepseek-api-vs-self-hosted-llms-cost-privacy-2026/), [techjacksolutions](https://techjacksolutions.com/ai-tools/deepseek/running-deepseek-v4-cost-effectively/)). Not a candidate for a single-GPU vast.ai minion setup; DeepSeek only enters this analysis as an API-pricing comparator (§5).

## 3. vast.ai GPU pricing (current, Aug 2026)

| GPU | Interruptible/spot | On-demand |
|---|---|---|
| RTX 3090 | $0.10–0.25/hr | higher, not separately quoted |
| RTX 4090 | $0.25–0.45/hr | $0.35–0.59/hr (vast.ai's own pricing page lists a $0.13/hr floor, but realistic *typical* listings cluster $0.29–0.59/hr) |
| A100 80GB | $0.50–1.00/hr | — |

Sources: [vast.ai RTX 4090 pricing page](https://vast.ai/pricing/gpu/RTX-4090), [vast.ai RTX 3090 pricing page](https://vast.ai/pricing/gpu/RTX-3090), [SynpixCloud Apr 2026 pricing](https://www.synpixcloud.com/blog/vast-ai-vs-runpod-rtx-4090-pricing). Marketplace pricing — varies by host reliability/region; treat as ranges, not fixed rates. **Storage**: $0.10–0.20/GB/month, host-defined, billed even while an instance is stopped (not deleted) ([usagepricing.com](https://www.usagepricing.com/tools/pricing-calculator/vast-ai)) — relevant since exp0's instance used an 80GB disk and a fp16 32B model's weights alone (~65GB) would nearly fill that; quantized weights (~18-20GB) fit with headroom.

## 4. Self-hosted inference throughput (vLLM)

| Model tier | GPU | Throughput | Source |
|---|---|---|---|
| 7-8B, Q4 | RTX 4090 | ~90-140 tok/s single-stream (one cited at 135 tok/s) | [databasemart RTX4090 vLLM benchmark](https://www.databasemart.com/blog/vllm-gpu-benchmark-rtx4090) |
| 32B, Q4_K_M | RTX 4090 (Qwen3-Coder, 32K context) | ~55 tok/s single-stream | [mustafa.net 2026 benchmarks](https://mustafa.net/llm-tokens-per-second-benchmarks/) (llama.cpp-family benchmark, not confirmed as vLLM specifically — flagged) |

**Caveat that matters more than the raw numbers**: these are single-stream (one request at a time) figures. vLLM's actual advantage over naive serving is continuous batching — serving many concurrent requests raises *aggregate* tok/s well above single-stream, at little extra wall-clock cost, because GPU compute is memory-bandwidth-bound at low batch sizes and has slack to absorb more concurrent decode steps. A single sequential Gru→minion→verify pipeline issuing one request at a time never exercises this — it would only benefit if multiple minion subtasks (or multiple experiment instances) run concurrently against the same server. This is a direct lever on §6's breakeven math and isn't optional to consider — a single-stream-only workload leaves most of vLLM's cost advantage over naive per-request serving unused.

## 5. API pricing comparators (current, Aug 2026)

| Model | Input $/M | Output $/M | Note |
|---|---|---|---|
| Claude Haiku 4.5 (used in exp0) | $1.00 | $5.00 | batch API halves both; prompt caching cuts cached input 90% ([finout.io](https://www.finout.io/blog/anthropic-api-pricing), [getapipulse](https://www.getapipulse.com/blog-haiku45-pricing.html)) |
| Gemini 2.5 Flash | $0.15 | $1.25 | [metacto.com](https://www.metacto.com/blogs/the-true-cost-of-google-gemini-a-guide-to-api-pricing-and-integration) |
| DeepSeek V4-Flash (API) | $0.14 | $0.28 | cached input ~$0.05/M; not self-hostable on one GPU (§2) | [morphllm](https://www.morphllm.com/deepseek-api) |
| **Qwen2.5-Coder-32B-Instruct, hosted by OpenRouter** | $0.66 | $1.00 | **same open weights as the self-hosting candidate in §2** — cleanest apples-to-apples comparator | [OpenRouter](https://openrouter.ai/qwen/qwen-2.5-coder-32b-instruct/providers) |

The OpenRouter row is the load-bearing comparison: it's literally the model this doc considers self-hosting, priced by someone who already solved the batching/utilization problem at scale.

## 6. Breakeven math — the core question

Effective self-hosted $/M output tokens = `(GPU $/hr) ÷ (tok/s × 3600) × 1,000,000 ÷ utilization`, where utilization = fraction of rented wall-clock time the GPU is actually generating tokens (vast.ai bills wall-clock rental regardless of whether the GPU is busy or idle — this is the entire crux, stated in the user's own framing as "deploying locally," which shifts cost from per-token to per-rented-hour).

**Worked case: Qwen2.5-Coder-32B-Instruct, INT4, RTX 3090 spot ($0.15/hr midpoint), ~55 tok/s single-stream:**

- 55 tok/s × 3600 = 198,000 tokens/hr
- $0.15 / 198,000 × 1,000,000 ≈ **$0.76 per M output tokens at 100% utilization**

Compare to §5's rows:

| Comparator | $/M output | Self-hosted breakeven utilization needed to match it |
|---|---|---|
| Same model, OpenRouter-hosted ($1.00) | $1.00 | **~76%** |
| Claude Haiku 4.5 ($5.00) | $5.00 | ~15% (but not the same model — capability, not just cost, differs) |
| Gemini 2.5 Flash ($1.25) | $1.25 | ~61% (also not the same model) |
| DeepSeek V4-Flash ($0.28) | $0.28 | >100% — self-hosting cannot win here at any utilization, at this GPU/model pairing |

The **~76% utilization-to-match-the-same-model's-own-API-price** number is the sharpest test of the hypothesis, because it holds capability constant — it isolates the pure infra-economics question from "is a different model good enough." Real utilization for a bursty, single-experiment research workload (waiting on mechanical verification, waiting on Gru, waiting on Docker test execution between minion turns) is very unlikely to reach 76% unless multiple minion calls are deliberately batched concurrently against one warm server (§4's caveat) or the same rented instance is kept busy across many parallel/sequential experiment runs rather than spun up per-run.

## 7. Practical infra considerations

- **Container vs. VM template**: exp0's Docker-in-Docker failure ([LOG.md](../experiments/exp0/LOG.md) Issues) was specific to needing *nested* Docker (SWE-bench's per-instance pinned Docker images running inside the rental). A self-hosted inference server (vLLM etc.) run directly in a standard vast.ai Docker container needs only direct GPU access, not nested containerization — vast.ai's own marketplace is built around exactly this (official PyTorch/CUDA docker templates are the common case for GPU inference workloads). This suggests the VM-template requirement from exp0 **does not carry over** to a self-hosted-inference setup — but this wasn't independently confirmed against vast.ai's docs in this pass (the docs page fetched didn't explicitly state GPU device-passthrough behavior for container vs. VM instances) — verify empirically before assuming it, don't just port exp0's VM requirement forward by default.
- **Disk**: quantized 32B weights (~18-20GB) fit exp0's 80GB disk with room for vLLM + dependencies + a repo checkout; fp16 32B weights (~65-71GB) would not, and would need a larger (costlier) disk allocation.
- **Cold start**: not independently measured in this pass — model weight download time depends on host network speed (unverified per-host, vast.ai listings vary) and is a real cost if instances are spun up per-experiment-run rather than kept warm; a kept-warm instance amortizes this one-time cost across an entire experiment batch, which also directly raises effective utilization (§6) since idle-between-runs time shrinks relative to total rental time.

## 8. Verdict on "I think it will be cheaper"

**Conditional, and the condition is specific: self-hosting only wins if the same open-weight model, run by a commercial API provider at scale, is being paid a premium for redundant infrastructure margin *and* this project can hit real utilization north of ~76% on the rented GPU.** Neither half of that is true by default:

- Commercial hosts (OpenRouter et al.) already operate at scale with continuous batching across many concurrent users — the exact mechanism (§4) that would need this project's own batching discipline to match. A single researcher's bursty, single-experiment workload starts at a structural disadvantage on utilization that a hyperscale host doesn't have.
- Against the *same* self-hostable model's own commercial price, breakeven needs ~76% utilization (§6) — high, and specifically hard to hit for exactly the sequential, escalate-on-failure pipeline this project's own architecture ([DESIGN.md](../DESIGN.md), [02-gru-minion-protocol.md](./02-gru-minion-protocol.md)) is built around, since minion calls are interleaved with mechanical verification and possible Gru escalation, not fired back-to-back.
- Against non-open, more-aggressively-priced API options (DeepSeek V4-Flash at $0.28/M output), self-hosting a comparable-capability model on a single rented consumer GPU likely cannot win at any realistic utilization.

So: **likely wrong as a blanket claim, but not unconditionally wrong** — it's plausible specifically if (a) the same server is kept warm and shared across many concurrent minion calls within an experiment batch (not spun up per single request), and (b) the comparison target is a premium API-only model (Haiku-tier) rather than the same open weights' own commercial hosting price. Framing it as "cheaper than Haiku, run at high batch concurrency" is a defensible hypothesis; framing it as "cheaper than API" unqualified is not supported by the numbers found here.

## 9. Phased rollout: framework validation first, frontier Gru later

The user's actual plan (clarified 2026-08-20, mid-research): run the first experiments with **open-weight models in both the Gru and minion roles**, self-hosted on vast.ai, specifically to validate the Gru/minion *framework mechanics* — plan format, escalate-on-failure ladder, verification routing, the "amend plan + retry" loop — before spending frontier-tier tokens on Gru. Only once the plumbing works does Gru get swapped to a frontier API model, which is when this project's actual hypothesis ([DESIGN.md](../DESIGN.md): frontier-plans + cheap-executes beats frontier solo) starts being tested for real.

This is a different rationale from §6-8's cost-per-token analysis, and doesn't contradict it:

- §8's "likely wrong as a blanket claim" verdict is about whether self-hosting **beats paying an API for the minion tier at production-run cost**, model capability held equal or better. That's a different question from "is self-hosting worth it while the framework itself is still buggy."
- Framework validation is dominated by iteration on plumbing (a broken escalation trigger, a malformed plan-schema field, a verification-harness bug), not clean single-pass runs — every bug caught costs a full Gru+minion round trip to reproduce and re-run. A flat-rate self-hosted GPU converts an unpredictable, bug-driven number of retries into a fixed hourly cost instead of a metered per-token one. That's the same logic as renting instead of metering when usage is bursty and hard to forecast — it holds regardless of whether the self-hosted *rate* beats the API rate on paper.
- Using an open model for Gru's role too during this phase is fine specifically **because framework validation isn't measuring plan quality**. It's a mechanics sanity check in the same spirit as Experiment 0's framing ("does X actually behave as expected," not a graded capability eval) — a weaker planner still exercises every code path (plan → subtask dispatch → mechanical check → debate → Gru escalation → amend-plan-and-retry) that needs debugging before a frontier model's token spend is on the line.
- **Phase 1 should reuse one self-hosted server for both roles where practical** — e.g. a single Qwen2.5-Coder-32B-AWQ vLLM instance on one rented GPU serving both Gru-role and minion-role prompts (different system prompts, same weights), instead of paying two separate metered APIs while debugging. This is actually a stronger case for self-hosting than anything in §6-8, because it sidesteps the utilization argument entirely — the goal isn't minimizing $/M-tokens at scale, it's bounding total spend during an unpredictable debugging phase.

**Phase boundary, concretely** (sharpened 2026-08-20): Phase 1's only success criterion is that the pipeline *runs* — a small SWE-bench subset goes end-to-end through plan → subtask dispatch → mechanical check → debate → Gru escalation → amend-plan-and-retry without a plumbing failure. Resolve rate and cost/token spend are **not** the point of Phase 1 and shouldn't be read as signal either way — a bad resolve rate at this stage could mean the framework works but the open model is weak, or the framework itself is still broken; Phase 1 alone can't distinguish those, and isn't trying to.

Cost/token comparison only becomes meaningful once the plumbing is trusted, which motivates a **Phase 2 ablation matrix** rather than a single swap. Holding the harness and SWE-bench subset fixed, vary which role(s) run on frontier/API inference vs. the self-hosted open model:

| Condition | Gru | Minion | Isolates |
|---|---|---|---|
| A (Phase 1 baseline) | self-hosted open | self-hosted open | pipeline correctness only — not a cost data point |
| B | frontier API | self-hosted open | this project's actual core hypothesis ([DESIGN.md](../DESIGN.md)): does frontier-plans + cheap-executes beat cheap-solo, and at what cost |
| C | self-hosted open | frontier/API | sanity-check in the other direction — weak planner + strong executor, useful as a contrast case, not expected to be the target config |
| D | frontier API | frontier API | frontier-solo cost/accuracy ceiling — the baseline B and C are actually being compared against |

B vs. D is the real cost claim this whole project is testing (cheap minion execution vs. frontier solo, holding Gru's planning quality fixed at frontier). A and C exist to isolate *why* a result looks the way it does — e.g. if B underperforms D, is that because the open-weight minion genuinely can't execute well even against a good spec, or because Gru's plan/verification-spec authorship itself has a bug that only frontier-tier Gru papers over? Running the full 2×2 rather than jumping straight to B vs. D answers that without re-running anything.

Each condition should log cost as `(API $ actually billed)` and/or `(GPU $/hr × wall-clock hours rented)` per role, per [EXPERIMENT_LOG_FORMAT.md](../EXPERIMENT_LOG_FORMAT.md)'s existing Results table — this is where §6-8's self-hosted-vs-API breakeven math (currently theoretical) gets replaced with real measured numbers from conditions A/C's self-hosted GPU-hours vs. B/D's API bills, on the identical task set.

## 10. Actionable recommendations

1. **Phase 1 (framework validation): self-host one open model for both Gru and minion roles** on a single vast.ai GPU instance, run a small SWE-bench subset, success = completes the full escalation ladder without a plumbing failure. Not a cost or resolve-rate data point (§9) — don't read anything into the numbers this run produces beyond "did it run."
2. **Phase 2: run the full A/B/C/D ablation matrix from §9**, not just a single self-hosted-vs-API swap — same harness, same small SWE-bench subset (ideally the same instances Phase 1 used, for direct comparability), varying only which role(s) use frontier/API inference vs. the self-hosted open model. B vs. D is this project's actual cost hypothesis; A and C exist to localize *why*, not just *whether*, a result differs.
3. **Log cost per role, not just per run** — API $ billed for whichever role(s) use it, GPU $/hr × wall-clock-hours-rented for whichever role(s) stay self-hosted, plus GPU-busy-seconds vs. rented-wall-clock-seconds for the self-hosted role(s) specifically (§6-8's breakeven math is currently theoretical; this is what replaces it with measured numbers). Use [EXPERIMENT_LOG_FORMAT.md](../EXPERIMENT_LOG_FORMAT.md)'s existing Results/Findings split so a bad number can be traced to "model is worse" vs. "GPU sat idle waiting on Docker tests" vs. "plumbing bug."
4. **Confirm the container-vs-VM GPU-access question empirically before assuming it** (§7) — a wasted VM-template rental (paying VM overhead vast.ai charges for init-manager/ptrace support that a self-hosted-inference workload doesn't need) is a small but avoidable tax on every condition that self-hosts, including Phase 1.
5. **When comparing self-hosted-vs-API within a single role (conditions A vs. C, or B vs. D), use the OpenRouter-hosted price of the same open-weight model as the primary baseline** (§6's $1.00/M row), not Haiku or Gemini Flash — those conflate cost with capability and won't cleanly isolate the "local deployment is cheaper for this role" claim.

## Gaps flagged (not filled with speculation)

- No source found gives vLLM-specific (vs. llama.cpp-family) throughput for a 32B model on consumer GPUs — the 55 tok/s figure used in §6 is sourced from a benchmark that may not be vLLM itself; re-verify before treating it as load-bearing for a real experiment's cost projection.
- No source directly confirms or denies whether vast.ai's standard Docker container instances (non-VM) expose GPU device access identically to VM templates — inferred from vast.ai's marketplace being built around Docker-based GPU workloads generally, not confirmed against their docs for this specific question.
- Cold-start (weight download + server boot) time not measured or sourced — could matter significantly for per-run-spun-up instances vs. a kept-warm instance, and directly affects effective utilization.
- Continuous-batching aggregate throughput (vs. the single-stream figures used throughout) not sourced with real numbers for this project's candidate models/GPUs — the utilization argument in §6/§8 would look meaningfully better with concurrent-request throughput data, which wasn't found in this pass.
- Qwen3-Coder-specific VRAM figures (as opposed to Qwen2.5-Coder, used as the proxy throughout) not found — sizing assumed similar but not confirmed.

## Open question carried forward

Does keeping one vast.ai instance warm across an entire experiment batch (rather than spinning up per-run) push realistic utilization high enough to clear the ~76% same-model breakeven line from §6? This is answerable directly by running recommendation #3 and logging busy-vs-rented time — not resolved by literature, since it depends on this project's own call pattern (escalate-on-failure ladder, mechanical-check wait times) which no external source models.
