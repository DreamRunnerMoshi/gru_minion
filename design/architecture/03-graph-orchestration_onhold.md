# Component 3: Graph-Based Orchestration ("Andrew Ng's graph engineering")

Status: **on hold** (2026-08-20) — research pass complete, deliberately not applied to a PLAN_FORMAT.md-equivalent schema while machine-config/Phase 1 work takes priority. Revisit once Phase 1 (see `design/04-machine-config.md`) validates the base escalate-on-failure pipeline. Companion to [02-gru-minion-protocol.md](./02-gru-minion-protocol.md) — that file covers the Gru↔minion delegation *protocol*; this one covers whether PLAN itself should be represented as a graph (subtasks as nodes, dependencies as edges) rather than the sequential list implied by `docs/architecture.excalidraw`'s "ORCHESTRATOR walks subtasks sequentially."

Question asked: what has Andrew Ng actually said about representing agentic workflows as graphs, and does adopting that representation change anything concrete for this project's PLAN structure and orchestrator logic?

## 1. Correcting the attribution before building on it

"Andrew Ng's graph engineering" does not exist as a named framework in his own primary sources — this needed to be checked rather than assumed, since the project's own memory file had it filed under his name. What Ng has actually published, directly:

- **"Agentic Design Patterns" (The Batch, March–April 2024)** — four patterns: Reflection, Tool Use, Planning, Multi-Agent Collaboration ([Part 4: Planning](https://www.deeplearning.ai/the-batch/agentic-design-patterns-part-4-planning), Apr 17 2024). No graph/node/edge terminology anywhere in these letters. Planning is described as "use an LLM to decide on what sequence of steps to execute"; Multi-Agent Collaboration as splitting a task across role-specialized agents (engineer, PM, QA, ...). Ng flags both patterns as **less mature and harder to predict** than Reflection/Tool Use as of 2024 — a caution worth carrying forward, not just a historical note.
- **"Three Key Loops for Building Great Software" (The Batch, Jun 26 2026)** — a *different*, more recent Ng framework, about iterative dev loops (inner loop = write/test/fix, outer loops = higher-level iteration) for agentic coding. Not about orchestration topology at all. SEO content conflates this with "graph engineering" by proximity of the word "loop" — worth naming explicitly so it isn't re-conflated later.
- **DeepLearning.AI's knowledge-graph course (2026, taught by Neo4j's Andreas Kollegger)** — about extracting entities/relationships from text into a graph *database* (RAG-style data modeling). A third, unrelated sense of "graph." Per community coverage, this course is what's currently causing the most conflation with orchestration graphs, since it's Ng-branded and graph-named but solves a data-modeling problem, not a control-flow problem.

What's circulating as "the Andrew Ng graph engineering playbook" (casys.ai PDF, Studocu/Scribd reposts, aibuilderclub's "Andrew Ng's Agentic Design Patterns, Mapped to Graphs") is **third-party synthesis explicitly labeled as such by its own authors** — aibuilderclub's piece states directly: "the loop-to-graph order below is our synthesis," "this is an implementation menu, not a translation key." It maps Ng's four 2024 patterns onto a graph representation as one *possible* implementation, not something Ng himself proposed.

**Correction for the project's orchestration-design memory**: the phrase "Andrew Ng's graph engineering (nodes as agent steps, edges as task dependencies)" should be read as *community terminology built on Ng's design patterns*, not a Ng-authored framework — cite the pattern, not the graph framing, if precision matters later.

## 2. Where the graph terminology is actually grounded

The technically real version of "nodes = steps, edges = control flow" lives in **LangGraph**, not in anything Ng wrote himself. DeepLearning.AI hosts "AI Agents in LangGraph," authored/taught by LangChain founder Harrison Chase (Ng promotes it, doesn't author it). LangGraph's own docs are explicit about what problem the graph model solves, independent of any Ng attribution:

- Plain chains are **DAGs**: strictly top-to-bottom, no loops.
- LangGraph generalizes to **cyclic graphs**: nodes can route back to earlier nodes — the mechanism needed for retry, self-correction, and iterative reasoning loops.
- **Conditional edges** — a function decides which node to go to next based on current state — is what moves a system "beyond chain-like structures to intricate, conditional, and even cyclic workflows" (LangGraph docs' own framing).
- All nodes read/write a single shared, checkpointed state object, making data flow between steps explicit rather than implicit in conversation history.

This is a real, load-bearing distinction (chains can't cycle; graphs can) — not just rebranding. It's the same distinction underlying **ReWOO vs. ReAct** already covered in [02-gru-minion-protocol.md §1](./02-gru-minion-protocol.md) (batch-all-upfront vs. interleave-with-cycles) — graph orchestration is the general case that subsumes both.

## 3. Graphs vs. loops vs. chains — when each applies

Community framing (explainx.ai, unsourced to any specific Ng claim, but consistent with LangGraph's own docs and general state-machine/workflow-engine precedent — this is "rediscovering classical state-machine vs. retry-loop patterns," not an AI-specific innovation):

| Shape | Fits when | Doesn't fit when |
|---|---|---|
| **Loop** | Single well-scoped task, retryable, one condition to satisfy | Multiple specialized agents, branching logic, state that must persist across the whole run |
| **Chain (DAG)** | Fixed, one-directional sequence of steps, no retry-in-place | Any step needs to route back to an earlier step (self-correction, escalation) |
| **Graph (cyclic)** | Branching + multiple agents + persistent shared state + retry-in-place all present simultaneously | Overkill for a single bounded task — added state-tracking complexity buys nothing there |

## 4. Applying this to the current PLAN / ORCHESTRATOR design

Current state (per `docs/architecture.excalidraw` and [02-gru-minion-protocol.md](./02-gru-minion-protocol.md)): PLAN is an undifferentiated list of subtasks; ORCHESTRATOR "walks subtasks sequentially"; the just-added "amend plan + retry" escalation edge is, in graph terms, **already a cycle** — GRU ESCALATION → PLAN → ORCHESTRATOR routes back to an earlier point in the flow. The diagram is already graph-shaped where it matters (escalation); the open question is whether PLAN's *internal* structure should be too.

**Concrete changes a graph representation would require, and what each buys:**

1. **Explicit dependency edges in the plan schema.** Today's implied list has no `depends_on` field. A graph representation needs subtasks to declare dependencies on other subtasks' outputs (e.g., "subtask 3 needs the file list subtask 1 produced"). This is a real schema change to whatever PLAN_FORMAT.md-equivalent gets written, not free.
2. **Parallel dispatch of independent subtasks.** With dependency edges explicit, ORCHESTRATOR can topologically walk the graph and dispatch all currently-unblocked subtasks to minions concurrently, instead of the diagram's literal "sequentially." This is a genuinely different benefit from Anthropic's parallel fan-out in [02-gru-minion-protocol.md §2](./02-gru-minion-protocol.md) — that pattern pays ~15× tokens because subagents redundantly investigate overlapping ground and everything routes back through the lead for synthesis. Parallel dispatch of *non-overlapping* subtasks doesn't have that redundancy cost — it's closer to free wall-clock parallelism, bounded by minion API rate limits rather than token spend. Worth distinguishing explicitly so this isn't read as "we're paying the same 15× tax Anthropic pays."
3. **Principled blast-radius for plan amendment.** Right now "amend plan + retry" (the escalation loop just added to the diagram) has no defined scope — does Gru reconsider the whole plan, or just the failed subtask? With explicit edges, the answer is computable: only subtasks *downstream* of the failed one (dependent on its output) need re-planning or re-verification; already-completed subtasks with no dependency on the failed one stand. Without the graph structure, this has to be re-decided by Gru's judgment every escalation, which is exactly the kind of unverifiable judgment call the project's orchestration-design memory already flags as the weak point of this architecture.

**Honest verdict — not a relabeling, but not a proven accuracy win either.** This is a systems-engineering argument (clearer dependency semantics, real parallelism, computable invalidation scope), parallel to how [01-planning.md §5](./01-planning.md) treats plan-format choices — actionable on engineering grounds, not backed by a resolve-rate study. No source found (Ng's or otherwise) quantifies accuracy or resolve-rate improvement from graph-structured plans over flat sequential ones for SWE-bench-style coding tasks specifically. The benefit case here is throughput/cost-latency and reduced-ambiguity-on-escalation, not "the model plans/executes better because it's a graph."

## 5. Actionable recommendations

1. **Add explicit `depends_on: [subtask_id, ...]` to the plan schema** once PLAN_FORMAT.md-equivalent is written — currently absent, and both parallel dispatch and principled amendment-scope require it.
2. **ORCHESTRATOR should topologically dispatch, not strictly sequentially walk** — independent subtasks (no edge between them) go to minions concurrently. Update `docs/architecture.excalidraw`'s "walks subtasks sequentially" label once this is adopted, since it will no longer be accurate.
3. **Define amendment blast-radius as "downstream of the failed node"** when specifying GRU ESCALATION's "amend plan + retry" behavior — gives that already-added escalation loop a concrete, checkable scope instead of open-ended whole-plan reconsideration.
4. **Don't cite this as "Andrew Ng's graph engineering" in project docs going forward** — cite Ng's actual Planning/Multi-Agent Collaboration patterns (§1 above) for the design-pattern lineage, and LangGraph's own docs (§2) for the technical graph-vs-chain argument, since that's what the reasoning actually traces back to.
5. **Don't adopt graph structure for its own sake where the loop/chain distinction in §3's table says it isn't needed** — e.g., a minion's own internal execution of one bounded subtask is a loop (execute → mechanical-check → done), not a graph; only PLAN's subtask-to-subtask relationships are graph-shaped.

## Gaps flagged (not filled with speculation)

- No resolve-rate or accuracy study found comparing graph-structured plans to flat sequential plans for coding-agent tasks specifically — the case here is architectural (parallelism, invalidation scope), not empirical.
- `startupfortune.com`'s piece on the knowledge-graph-course "war" returned HTTP 403 and couldn't be directly verified beyond its search-result snippet; the knowledge-graph-vs-orchestration-graph conflation claim in §1 is sourced secondhand and should be re-checked if it becomes load-bearing for anything.
- The "graphs vs. loops" decision table in §3 is community-level synthesis (explainx.ai), not a controlled study or a direct Ng claim — treat as a reasonable heuristic, not a validated result.

## Open question carried forward

Does parallel dispatch of independent minion subtasks actually reduce wall-clock time/cost in practice for this project's workload, or does dependency-tracking overhead (schema complexity, partial-failure bookkeeping) eat the benefit for plans with few genuinely independent subtasks? Not answered by any source found — candidate for a project experiment once PLAN_FORMAT.md-equivalent exists in both flat and dependency-graph form, run against the same task set.
