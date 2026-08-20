# Component 1: Planning (Gru's plan-writing step)

Status: research pass complete, not yet applied to PLAN_FORMAT.md — reiterate/confirm before updating the format. Covers the "Gru decomposes the task" half of the architecture only; verification-writing is a separate component (see `02-*.md` once researched).

Question asked: how good are LLMs actually at writing plans, and what prompting techniques measurably improve planning quality?

## 1. Empirical planning capability

Frontier models are decent but brittle at planning — not reliably strong, and failure is sharp rather than graceful under disruption.

- **PlanBench-XL** ([arXiv 2606.22388](https://arxiv.org/abs/2606.22388)): Gemini-3.1-Pro tops out at 77.06% accuracy in clean settings. GPT-5.4 gets 51.90% in block-free settings but **collapses to 11.36%** when relevant tools are blocked/corrupted.
- **DisasterBench**: Gemini 3.1 Pro 68.24% with direct prompting → 73.39% with Tree-of-Thought; GPT-5.4 54-66% depending on method. Confirms prompting strategy moves the needle, but no frontier model clears ~80% on formal planning tasks.
- Consistent pattern across sources: models handle short-horizon/low-tool-count planning reasonably; accuracy drops sharply as horizon length and recovery-path complexity increase.

## 2. Prompting techniques, with evidence

| Technique | Evidence | Verdict for Gru |
|---|---|---|
| **Plan-and-Solve** ([arXiv 2305.04091](https://arxiv.org/abs/2305.04091), Wang et al., ACL 2023) | Consistently outperforms Zero-shot-CoT across datasets. Vanilla CoT error breakdown: 12% step-missing, 27% semantic misunderstanding — Plan-and-Solve's explicit "devise a plan, then carry it out" framing targets the step-missing failure directly. | Adopt — cheap, well-evidenced, directly on-target. |
| **Least-to-Most decomposition** ([arXiv 2205.10625](https://arxiv.org/abs/2205.10625)) | Strong on compositional/symbolic tasks — 76% vs 6% success on SCAN (text-davinci-002), 99.7% with code-davinci-002. | Promising but unproven for open-ended coding tasks specifically — the magnitude was measured on symbolic/compositional benchmarks, may not transfer. |
| **Self-consistency / multi-plan sampling + voting** | Real effect historically, but [arXiv 2511.00751](https://arxiv.org/abs/2511.00751) ("Self-Consistency Is Losing Its Edge") finds diminishing returns and rising relative cost specifically on modern/frontier models — validated on older, weaker models. Also breaks down when many distinct valid plans exist (common in open-ended coding), since voting needs near-exact match. | Skip for Gru — N× planning-call cost unlikely to pay for itself on a frontier model. |
| **Reflection / self-critique on the plan** | Mixed, context-dependent; effectiveness depends on the model being able to spot its own errors with no ground truth — no oracle for that in plan quality specifically. Diminishing/negative returns reported on easier prompts and already-strong models. | Weakest-evidenced technique here — optional cheap sanity pass at most, not load-bearing. |
| **Few-shot exemplars vs. zero-shot** | No direct planning-specific quantified comparison found. General literature suggests exemplars help but risk overfitting to exemplar structure/granularity. | Flag, not resolved — a fixed few-shot plan example could bias Gru toward that example's decomposition granularity regardless of task fit. |
| **Structured/JSON-constrained output** | [arXiv 2606.09410](https://arxiv.org/abs/2606.09410) ("Capacity, Not Format"): forcing schema-compliant output *while reasoning* causes **10-30% performance degradation** — format constraints compete with reasoning for the same generation capacity. Effect is capacity-dependent: strong models absorb it better, weak models degrade severely, worst when task is already near the model's capability boundary. | **Actionable now**: have Gru reason freely first, convert to PLAN_FORMAT.md's schema as a separate step — don't ask for the structured plan directly while it's still reasoning. |

## 3. Planning specifically for coding/SWE agents

**No direct with-plan/without-plan controlled ablation on SWE-bench resolve rate was found** — real gap, not filled with speculation. This may need to be run as our own experiment rather than sourced from literature.

What exists instead (weak, indirect evidence): SWE-agent (interactive, exploration-based, ACI tool interface) reaches ~12.47% resolved vs. a then-best non-interactive/retrieval-augmented baseline at 3.8% on original SWE-bench (NeurIPS 2024). On SWE-bench Multimodal, interactive systems average ~11.5% vs. Agentless-style non-interactive baselines at ~3.9%. Suggestive that *interactive exploration* beats static upfront planning without exploration — but this compares whole system architectures, not plan-vs-no-plan within one system, so treat as directional at best.

## 4. Negative / contrarian findings

- **Kambhampati et al., "LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks"** ([arXiv 2402.01817](https://arxiv.org/abs/2402.01817)) — core claim: LLMs are unreliable both as autonomous planners *and* as verifiers of their own plans; they frequently accept their own flawed self-generated plans as valid. Recommendation: never trust an LLM's self-assessed plan validity; pair generation with an external, ideally deterministic, verifier. **This is a direct, independent argument for this project's escalate-on-failure / external-verification architecture** — not just for the planning component, worth citing in DESIGN.md's prior-art section.
- **Plan-representation granularity study** ([arXiv 2605.29927](https://arxiv.org/abs/2605.29927), web agents) — "low-level plans can limit exploration and generalization"; executors failed when constrained to exact low-level specs even where flexible reasoning would have worked; "high-level guidance appears crucial for balancing structure with adaptability." Also: **no single plan representation dominates** — best format was planner/executor-model-pair-dependent (narrative best for GPT-4.1-mini, checklist best for Qwen-2.5-VL, mixed pairs beat homogeneous pairs). Directly cautions against over-specifying subtask granularity.

## 5. Actionable recommendations for Gru's prompt (synthesized, not yet applied)

1. **Reason before structuring** — free-form plan narrative first, separate step converts to PLAN_FORMAT.md's JSON schema. Directly supported by finding #2's structured-output degradation.
2. **Bias toward high-level subtask granularity, not low-level prescriptiveness** — matches the granularity study and this project's existing instinct for `search_strategy` as a bound rather than a literal script (already reflected in PLAN_FORMAT.md — confirms it, no change needed there).
3. **Don't trust Gru's own plan-validity confidence** — per Kambhampati, treat any "I'm confident this plan is correct" from Gru as unverified until it passes the external ladder.
4. **Skip self-consistency/multi-plan-voting** for Gru specifically — cost not justified by evidence on frontier models.
5. **Self-critique/reflection pass is optional, not load-bearing** if included at all.
6. **No single best plan format found** — worth A/B testing narrative vs. checklist vs. pseudocode framing against our specific minion model empirically, rather than assuming one is correct a priori.

## Open question carried forward

Does upfront planning actually improve SWE-bench-style resolve rate over pure agentic exploration, controlled within one system? Not answered by literature — candidate for a project experiment (compare Gru-plans-first vs. minion-explores-freely on the same instances, holding the model fixed).
