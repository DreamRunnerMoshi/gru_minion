# Component 2: Gru-Minion Interaction Protocol

Status: research pass complete, not yet applied to PLAN_FORMAT.md. Companion to [01-planning.md](./01-planning.md) — that file covers plan *content* quality; this one covers the *mechanism* by which Gru forms a plan, specifically: Gru's planning process is not one-shot generation. While reasoning toward a plan, Gru can pause and delegate bounded information-gathering sub-calls to minions ("find every file that calls method X," "search the web for topic Y and summarize each result"), get findings back, and keep reasoning with that grounded context. Minions are therefore both plan-executors *and* research assistants during plan formation.

## 1. ReAct and tool-augmented reasoning foundations

**ReAct** ([arXiv:2210.03629](https://arxiv.org/pdf/2210.03629), Yao et al., ICLR 2023) interleaves reasoning traces with action/tool calls rather than pure chain-of-thought or pure acting. On HotpotQA/Fever, interleaving with a Wikipedia API reduced hallucination and error-propagation vs. CoT alone. On ALFWorld and WebShop it beat imitation/RL baselines by **34 and 10 absolute points** respectively, with only 1-2 in-context examples. This is the closest general foundation for "pause reasoning, call a tool, incorporate the result, continue reasoning" — directly analogous to Gru pausing to delegate a minion sub-call.

Real fork in protocol design worth naming: **ReWOO** ([arXiv:2305.18323](https://arxiv.org/abs/2305.18323)) decouples reasoning from observations entirely — plan *all* tool/delegate calls upfront in one pass, fire them (in parallel), then reason once over all results, instead of interleaving one call at a time. This is genuinely different from ReAct's approach, not a minor variant — see §5.

## 2. Real-world precedent: Anthropic's multi-agent research system

The closest real production analog to what we're designing. Full writeup: [anthropic.com/engineering/multi-agent-research-system](https://www.anthropic.com/engineering/multi-agent-research-system).

- **Architecture**: orchestrator-worker. A lead agent (Opus-tier) plans and spawns 3-5 subagents (Sonnet-tier) in parallel; subagents search independently and report findings back for synthesis. Reports **90.2% performance improvement** over single-agent on their internal eval.
- **Task structuring that worked**: each subagent needs an explicit objective, output format, tool/source guidance, and clear scope boundary. Vague instructions ("research the semiconductor shortage") caused subagents to duplicate work and misalign — directly relevant to how we should scope a minion's research sub-call.
- **Production failure modes they found**: spawning 50+ subagents for simple queries, endless searching for non-existent sources, "excessive updates" distracting other agents, duplicated work from unclear division of labor, overly verbose search queries degrading result quality.
- **Delegation depth: strictly one level.** Lead agent spawns subagents; subagents do not spawn further subagents. No evidence found anywhere of recursive delegation in their system.
- **Fidelity mitigation**: their own appendix notes "direct subagent outputs can bypass the main coordinator for certain types of results, improving both fidelity and performance" — i.e. routing large results through filesystem/artifact references rather than re-summarizing through conversation turns reduces information loss. They specifically engineered around conversational hand-back being lossy.
- **Cost**: multi-agent systems use **~15× the tokens** of a single chat interaction; individual agents alone use ~4×. Token usage "explains 80% of the variance" in eval performance — more search/delegation generally helps, but at steep, near-linear cost. Only justified when task value clears that cost.
- **Their scaling heuristics** (encoded as guidance, not rigid rules): simple fact-finding → 1 agent, 3-10 tool calls; direct comparisons → 2-4 subagents, 10-15 calls each; complex research → 10+ subagents with clearly divided responsibilities.

Lighter/architectural-only evidence on other frameworks: **LangGraph**'s supervisor pattern (explicit graph state, one supervisor dispatches to specialized workers, traces to Anthropic's own Dec-2024 pattern description); **AutoGen** frames delegation as structured multi-agent conversation with a group-chat manager selecting the next speaker — hierarchical-chat topology is noted to reduce coordination overhead from O(n²) toward O(n) vs. flat peer-to-peer; **CrewAI** supports sequential or hierarchical task-passing with role/goal/backstory-defined agents. None of these three yielded controlled quantitative findings in what was retrievable — architecture descriptions only, no numbers to cite.

## 3. When to delegate vs. reason directly

Weak-to-moderate evidence, no clean tradeoff curve found in the literature. One delegation-intelligence study reportedly found a delegating orchestrator's `call_sub_agent` action accounts for **over 70%** of its tool invocations on some benchmarks — i.e. learned policies favor delegating information-gathering over doing it inline (source referenced: [arXiv:2606.09730](https://arxiv.org/pdf/2606.09730) "SearchSwarm" — the PDF didn't parse for direct verification during this research pass, so treat this number as directional, not confirmed). General heuristic surfaced across sources: delegate when marginal quality gain exceeds marginal cost; don't delegate work cheap enough to do inline. **No paper found with an actual quantified delegation-frequency-vs-quality-vs-cost curve** — flagged gap, not filled with speculation.

## 4. Fidelity of delegate reports back to the orchestrator

A real, documented risk, not just a theoretical concern. Multi-agent hallucination literature converges on: "when agents collaborate, hallucinations no longer remain local; they can propagate across agent boundaries and trigger operational failures." **MAMM-Refine** ([arXiv:2503.15272](https://arxiv.org/pdf/2503.15272)) proposes multi-agent collaboration specifically to *improve* faithfulness by separating drafting/evaluation/synthesis into distinct roles — implies single-pass summarize-and-handoff is a known weak point worth architecting around.

**Gap**: no paper found that directly quantifies information loss specifically in a "cheap sub-agent summarizes for an expensive orchestrator" setup — the literature covers general multi-agent hallucination and strong-summarizes-for-strong, but not our specific weak-summarizes-for-strong scenario. Weakest-evidenced section of this research pass; flagged rather than papered over.

## 5. Practical protocol design implications

1. **Bound every delegated sub-call explicitly** — objective + output format + scope boundary, per Anthropic's finding that vague delegation causes duplication/misalignment. Directly actionable for how Gru phrases a minion research request; this is the same "search_strategy must be explicit" principle [01-planning.md](./01-planning.md) already argued for on granularity grounds, now doubly reinforced from the delegation-fidelity angle.
2. **One level of delegation, not recursive.** Matches the only real production precedent found. No evidence supports minions delegating further; it adds coordination failure surface (per Anthropic's own listed failure modes) without demonstrated benefit.
3. **Route large findings as artifacts/references, not conversational prose summaries, where possible** — Anthropic's own fidelity fix. For us: a minion's "files calling X" result is likely better handed to Gru as a structured list/reference than compressed into prose, which is where information loss creeps in.
4. **Unresolved fork, not resolved by evidence**: interleaved (ReAct-style — delegate, observe, delegate again, more adaptive/accurate, more round-trips) vs. batched (ReWOO-style — plan all research sub-calls upfront, fire in parallel, cheaper/faster, less adaptive to what earlier results reveal). Anthropic's own system leans batched-for-fan-out (parallel subagent spawning) while still allowing follow-up rounds — a hybrid (batch the obvious research calls upfront, allow at most one follow-up round) is a reasonable starting design, but nothing in the literature proves this is optimal for our case specifically.
5. **Treat minion research findings as unverified inputs, not ground truth** — consistent with this project's existing verification-ladder stance (DESIGN.md) and reinforced by the hallucination-propagation risk in §4. A minion's summary should ideally be lightly checkable (e.g., does the file list it returned actually exist) before Gru's plan depends on it — this is our own inference extending the project's existing design principle, not something a cited paper prescribes directly for this scenario.

## Gaps flagged (not filled with speculation)

- No controlled cost/quality delegation-frequency curve found anywhere.
- No direct study of weak-model-summarizes-for-strong-model fidelity loss specifically (only strong-for-strong and general hallucination-propagation literature exists).
- SearchSwarm's 70%-delegation figure (§3) is sourced from a search snippet, not independently verified against the paper's own text — re-verify before relying on it for a design decision.
- No paper directly compares interleaved vs. batched delegation for this exact planning-with-delegated-research use case — the recommendation in §5.4 is a reasonable synthesis, not a cited result.
