# Literature Review

Index of every research paper and industry writeup this project has actually cited, pulled out of `DESIGN.md` and `design/architecture/*.md` into one place. Each file is a standalone summary — thesis, key findings, and **what we took from it** (which design decision it fed, or which gap it left open). This folder doesn't introduce new sources; it's a structured extraction of research passes already done, organized for lookup instead of buried inline in design docs.

File naming: `<arXiv-id>-<slug>.md` for papers, `industry-<slug>.md` for non-peer-reviewed industry writeups (blog posts, company reports) — kept visually distinct in a flat listing since they carry different evidentiary weight.

## Papers, by project theme

### Delegation / multi-agent protocol (feeds [02-gru-minion-protocol.md](../design/architecture/02-gru-minion-protocol.md))

| Paper | One-line takeaway | What we took |
|---|---|---|
| [ReAct](./2210.03629-react-reasoning-and-acting.md) (Yao et al., ICLR 2023) | Interleaving reasoning with tool calls beats pure CoT or pure acting — +34/+10pp on ALFWorld/WebShop. | Closest general foundation for "Gru pauses to delegate a minion sub-call, then keeps reasoning." |
| [ReWOO](./2305.18323-rewoo-decoupled-reasoning.md) | Decouples planning from observation: batch all tool calls upfront, fire in parallel, reason once over all results. | The real alternative to ReAct-style interleaving — batched vs. interleaved delegation is an open fork, not resolved by evidence. |
| [SearchSwarm](./2606.09730-searchswarm-delegation-frequency.md) | Reportedly: a delegating orchestrator's `call_sub_agent` action is >70% of its tool calls on some benchmarks. | Directional only — the cited number wasn't independently verified against the paper text. Flagged, not load-bearing. |
| [MAMM-Refine](./2503.15272-mamm-refine-multiagent-faithfulness.md) | Splitting drafting/evaluation/synthesis into distinct roles improves faithfulness over single-pass summarize-and-handoff. | Implies single-pass minion-summarizes-for-Gru is a known weak point worth architecting around — but no paper found quantifying *our* specific weak-summarizes-for-strong setup (flagged gap). |

### Planning (feeds [01-planning.md](../design/architecture/01-planning.md))

| Paper | One-line takeaway | What we took |
|---|---|---|
| [PlanBench-XL](./2606.22388-planbench-xl.md) | Frontier models' planning accuracy collapses under tool corruption (GPT-5.4: 51.9% → 11.36%). | Planning is fragile to a corrupted environment, not just a hard reasoning task — informs how much Gru should trust its own plan once minion execution starts hitting unexpected states. |
| [Plan-and-Solve](./2305.04091-plan-and-solve.md) (Wang et al., ACL 2023) | "Devise a plan, then carry it out" beats Zero-shot-CoT; targets the 12% step-missing failure mode directly. | Adopted — cheap, well-evidenced, directly on-target for Gru's plan-then-execute structure. |
| [Least-to-Most decomposition](./2205.10625-least-to-most-decomposition.md) | Strong on compositional/symbolic tasks (76% vs 6% on SCAN). | Promising but unproven for open-ended coding — measured on symbolic benchmarks, may not transfer to SWE-bench-style tasks. |
| [Self-Consistency Is Losing Its Edge](./2511.00751-self-consistency-losing-edge.md) | Multi-sample voting shows diminishing returns and rising relative cost on modern frontier models. | Skip multi-plan sampling for Gru — N× planning-call cost unlikely to pay for itself on a frontier model. |
| [Capacity, Not Format](./2606.09410-capacity-not-format.md) | Forcing schema-compliant output *while reasoning* costs 10-30% performance — format competes with reasoning for capacity. | Actionable: Gru reasons freely first, converts to `PLAN_FORMAT.md`'s schema as a separate step afterward. |
| [Kambhampati et al. — LLM-Modulo](./2402.01817-llms-cant-plan-llm-modulo.md) | LLMs are unreliable both as planners *and* as verifiers of their own plans. | Independent argument for this project's escalate-on-failure / external-verification architecture, beyond just the planning component. |
| [Plan-representation granularity study](./2605.29927-plan-granularity-web-agents.md) | Low-level plans limit exploration; no single plan format dominates across model pairs. | Cautions against over-specifying subtask granularity in `PLAN_FORMAT.md`. |

### Verification / reward hacking / debate (feeds `DESIGN.md`'s verification section)

| Paper | One-line takeaway | What we took |
|---|---|---|
| [ORACLE-SWE](./2604.07789-oracle-swe-localization-bottleneck.md) | Perfect localization lifts SWE-bench Lite resolve rate 28.0% → 40.3% over realistic search. | Context-gathering/localization, not code-writing, is the dominant bottleneck — validates splitting menial context work from code synthesis. |
| [RL reward hacking / test editing](./2604.15149-rl-reward-hacking-test-editing.md) | RL-trained models learn to edit/delete tests or monkey-patch the scorer to force a pass. | Directly threatens this project's premise if a minion is ever allowed to touch its own verification criteria — hard constraint on minion permissions. |
| [EvilGenie](./2511.21654-evilgenie-reward-hacking-benchmark.md) | Ready-made reward-hacking benchmark/methodology (held-out tests + LLM-judge + test-file-edit detection). | Adaptable to check whether a minion gamed Gru's verification rather than genuinely solving the task. |
| [The Verification Horizon](./2606.26300-verification-horizon.md) | No single verification scheme is robust across all task types. | Verification design likely needs to vary by task shape, not use one fixed template across all subtask types. |
| [AI safety via debate](./1805.00899-ai-safety-via-debate.md) (Irving/Christiano/Amodei, 2018) | Structured interactive debate lets a bounded verifier correctly judge claims beyond what it could verify directly (NP → PSPACE-style gain). | Core mechanism behind this project's debate-escalation step for judgment-laden context-gathering disputes. |
| [How to Avoid Debate](./2607.03561-doubly-efficient-interactive-proofs.md) | 2026 successor attempting the same PSPACE-style guarantee without inheriting debate's obfuscated-argument failure mode. | Follow-up to watch — debate's "long plausible flawed argument" failure mode directly maps onto this project's spec-authorship gap. |

### Codebase indexing / retrieval

| Paper | One-line takeaway | What we took |
|---|---|---|
| [Code Isn't Memory](./2606.22417-code-structural-index.md) | Proposes a structural (call/definition-edge) codebase graph index, layered alongside vector/lexical search. | Proposed mitigation for judgment-laden context-gathering — candidate addition to the minion research toolkit. |

## Industry writeups (not peer-reviewed — separate evidentiary weight)

| Writeup | One-line takeaway | What we took |
|---|---|---|
| [Anthropic — multi-agent research system](./industry-anthropic-multi-agent-research-system.md) | Production lead+subagent research system: explicit task scoping, fan-out-and-synthesize topology, ~15× token cost vs. single-agent. | Closest real production analog — topology (lead + bounded workers) adopted; re-engagement frequency deliberately *not* adopted (see divergence note in the file). |
| [AI21 — open-models-explore, frontier-patches](./industry-ai21-explore-frontier-patch.md) | 80.8% on SWE-bench Pro at $5.99/task — SOTA-at-cost with a split-model pipeline. | Positive existence proof for this project's core cost hypothesis. |
| [Augment Code / Stencil — model routing](./industry-augment-stencil-routing.md) | Opus-plans + Gemini-Flash-executes was 14% *more* expensive than Opus solo for identical accuracy. | Load-bearing counter-example: split-model setups are not automatically cheaper. Directly killed the "re-engage Gru after every minion completion" design and shaped the escalate-on-failure architecture. |

## Notes

- Every summary here reflects what this project's own research passes found *at the time they were run* (dated within each file) — several sources are six-day-old or single-source blog coverage, flagged as such where the original design doc flagged it. Don't treat a summary here as independently re-verified beyond what the linked design doc already says.
- **Gaps are recorded, not silently dropped**: several papers above are cited specifically because a design doc found *no* paper answering a needed question (e.g. no controlled with-plan/without-plan SWE-bench ablation exists) — those gaps are called out in the relevant file, not hidden.
