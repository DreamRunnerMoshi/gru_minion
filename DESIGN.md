# Coding Agent Cost/Accuracy Benchmark — Investigation & Design Notes

Status: design phase, no implementation yet. Last updated 2026-08-18.

## Hypothesis

Smaller/cheaper LLMs drift off-task or hallucinate more easily than frontier models. If a frontier model first defines the task **and** a verification method, a cheap model executing against that spec should stay on-task, because it's checked rather than trusted. This should let a cost-minimizing pipeline use frontier models sparingly (planning/verification-writing) and cheap models heavily (execution), instead of running a frontier model end-to-end.

Working name for the pattern: the frontier model is **Gru** (plans, decomposes, defines verification); cheap/small models are **minions** (execute narrowly-scoped subtasks).

## Investigation: SWE-bench family

Chosen as the eval substrate (ground-truth benchmark with built-in pass/fail verification).

| Variant | Size | Notes |
|---|---|---|
| SWE-bench (original) | ~2,294 | noisy, largely superseded |
| SWE-bench Lite | 300 | cheap iteration subset |
| SWE-bench Verified | 500 | OpenAI-curated, current standard |
| SWE-bench Multimodal | 517 | GUI/image-based issues |
| SWE-bench Multilingual | 300 | 9 languages, 42 repos |
| SWE-Gym | — | training data, not eval |
| SWE-bench Pro (Scale AI) | 1,865 | harder successor; multi-file, 4 languages, contamination-resistant. Models at 80% on Verified often drop to 50-60% here. |

**Verification format** (the thing we want to imitate for our own task specs): each instance ships a hidden gold patch, a hidden test patch, a `FAIL_TO_PASS` test list (proves the bug is actually fixed), and a `PASS_TO_PASS` list (regression guard), all run inside a per-instance pinned Docker image.

**Tooling**: `pip install swebench` (repo `SWE-bench/SWE-bench`), needs ~120GB Docker disk; `prepare_images` then `run_evaluation`. Hosted alternative: `sb-cli`. Leaderboard/viewer: swebench.com.

**Local setup path**: clone repo → `pip install -e .` → Docker w/ 120GB disk → start with Lite or a 20-30 instance subset via `--instance_ids` → `prepare_images` → generate patches → `run_evaluation`.

**Caveat**: SWE-bench issues are just an issue description + repo — no JIRA tickets, PDFs, or internal doc links. If we want to exercise multi-source context-gathering (the "real SWE job" framing below), SWE-bench alone won't cover that part of the pipeline; only the code-reading/test-finding menial tasks would be exercised there.

## Prior art

- **SuperScout** (arXiv 2608.04804) — small scout model explores repo, sandbox-verified handoff to frontier fixer. Matched Opus solve rate on SWE-bench Pro at ~1/5 cost. Key finding: **the verified handoff itself drove the gain, not model routing choice** — directly supports our hypothesis.
- **AI21 "open models explore, frontier patches"** (Jul 2026) — 80.8% on SWE-bench Pro at $5.99/task, SOTA-at-cost.
- **Counter-example (important)**: Augment Code / Stencil routing writeup found Opus-plans + Gemini-Flash-executes at $3.18/task (84.6% pass) vs. Opus solo at $2.78/task (same 84.6%) — the split setup was **14% more expensive** for identical accuracy. Split-model pipelines are not automatically cheaper; savings depend on which cheap model executes and how much frontier-token overhead the plan itself costs.
- **Agentless oracle-localization result** (ORACLE-SWE, arXiv 2604.07789) — resolve rate 28.0% → 40.3% (+12.3pp) on SWE-bench Lite when given perfect localization vs. realistic search. Strong evidence that **context-gathering/localization, not code-writing, is the dominant bottleneck** in agentic SWE — validates the intuition behind splitting menial context work from high-cognition code synthesis.
- **FrugalGPT / RouteLLM** — foundational generic cascade pattern (cheapest model first, escalate on scorer rejection), not coding-specific but the base pattern this whole approach descends from.
- **Agentless** (OpenAutoCoder) — non-agentic localize → repair → validate pipeline; a template for how the frontier model's task decomposition could be structured.
- **mini-swe-agent** — 100-line bash-only agent loop, model-agnostic, ~65-74% on Verified; a minimal candidate for the "minion executor" harness since it needs no tool-calling API.

## Reward-hacking / verification-gaming risk

- **arXiv 2604.15149** — RL-trained models learn to edit/delete tests or monkey-patch the scorer to force a pass. Directly threatens our premise if a minion is ever allowed to touch its own verification criteria.
- **EvilGenie** (arXiv 2511.21654) — ready-made reward-hacking benchmark/methodology (held-out tests + LLM-judge + test-file-edit detection); adaptable to check whether a minion gamed Gru's verification rather than genuinely solving the task.
- **"The Verification Horizon"** (arXiv 2606.26300) — no single verification scheme is robust across all task types; verification design likely needs to vary by task shape, not use one fixed template.
- Key principle: **"isomorphic" (structurally-faithful) verification resists gaming better than "extensional" (black-box pass/fail) verification** — how Gru phrases verification criteria matters as much as whether it writes them at all.

## Architecture decisions

### Sequential, not multi-agent fan-out

Early framing considered parallel multi-agent fan-out (decompose one issue into N subtasks run concurrently by N minions). Rejected for now: SWE-bench's ground-truth verification (FAIL_TO_PASS/PASS_TO_PASS) is defined at the whole-patch level, not per-subtask, so parallel fan-out would need a separate integration-verification pass to catch cross-subtask breakage — a second untested variable before we've confirmed the core hypothesis works at all. Current framing: sequential pipeline, not necessarily "agentic" in the complex-tool-use sense — closer to a real SWE workflow (ticket → gather context → write code → find/run tests) than a swarm of parallel agents.

### Menial vs. high-cognition split

Real SWE work is mostly context-gathering (reading docs, finding call sites, compiling background), not code-writing — this is where cheap models should be delegated, with the frontier model reserved for genuinely high-cognition steps (design/abstraction decisions, the actual code synthesis, judgment calls). The Agentless oracle-localization result (above) backs this: fixing localization alone (a context-gathering problem) accounts for a large share of the resolve-rate gap.

**Important nuance surfaced during design**: not all "context gathering" is mechanical. Distinguish:
- **Mechanical retrieval** (fetch a file, extract a section, list functions matching a pattern) — genuinely cheap and easy to verify (did it return the right file).
- **Judgment-laden curation** (which of 200 references actually matter, did we find *everything* relevant) — this is often as hard as code-writing and is exactly where missed implicit invariants live (e.g., an analytics/billing code path that silently assumes an old invariant without ever being an obvious keyword match). No test catches an *omission* the way it catches a wrong output.

Concrete worked example used to pressure-test this (adding a new verification method alongside existing email verification in a large codebase): the hard parts identified were (1) finding every implicit call site assuming the old single-method invariant, (2) the abstraction decision (shared interface vs. bolt-on), (3) backward-compat/migration for existing user data, (4) cross-cutting concerns (security parity, rollout, concurrency). Only (1) looks like "context gathering" on the surface, but it's actually judgment-laden, not mechanical.

### Orchestration pattern: Gru/minion, escalate-on-failure

**Confirmed decision**: escalate-on-failure orchestration, not re-engage-Gru-on-every-step.

- Gru plans the task + verification criteria once (or per subtask); minions execute; the orchestrator only calls Gru back in when a minion's automated verification check fails.
- Rejected alternative: re-engaging Gru after every minion completion (maximally adaptive, catches drift immediately, but eats most of the cost savings the whole hypothesis is meant to demonstrate — see the Augment counter-example above).
- This only preserves the cost math **if verification is strong enough to catch drift without Gru's eyes on every result**. Otherwise it silently degrades into trusting a possibly-confused minion's self-report, reintroducing the exact hallucination risk this design exists to prevent.
- **Preference: automated/mechanical verification** (test runners, FAIL_TO_PASS/PASS_TO_PASS, linters, AST/type checks, file-existence assertions) over model self-report — only mechanical checks are safe to trust unsupervised.

### Completeness sub-design: structural codebase graphs

Proposed mitigation for the judgment-laden context-gathering problem: index the target codebase as a **structural graph** (call/definition edges — see arXiv 2606.22417, "Code Isn't Memory: A Structural Codebase Index Inside a Coding Agent"), layered alongside vector and lexical search.

- Vector search misses causally-connected-but-differently-worded code; lexical search misses non-exact-match structural relations; a call-graph traversal from the changed symbol catches explicit/structural dependencies (callers, callees, references) deterministically.
- This reclassifies "did the minion search thoroughly" from a judgment call into something checkable ("traversed N hops, visited all reachable nodes") — i.e., a way to move a context-gathering subtask from the unverifiable bucket into the automated-check bucket.
- **Caveat**: graph traversal only catches explicit/structural dependencies, not true implicit invariants (e.g., a business rule or event-name string that assumes old behavior without ever calling the changed code directly). Narrows the completeness gap, doesn't close it — still needs vector/semantic search for the non-structural residual.
- Note: distinct from "Andrew Ng's graph engineering" content found during research, which is actually about *agent-orchestration* graphs (nodes = agent steps, edges = task dependencies), not codebase structure — don't conflate the two.

## Open questions (unresolved)

1. **Plan format**: what fields does Gru's structured output actually contain per subtask (task description, verification criteria, search strategy/scope, dependency ordering)? Not yet designed.
2. **Non-automatable verification default**: for subtasks where no mechanical check is possible (completeness of a search, quality of a summary, abstraction/design judgment), what's the default — mandatory Gru escalation, or is there a middle path? Leaning toward "squeeze as much as possible into mechanical form first (e.g. via graph traversal), fall back to mandatory Gru escalation only for the true residual" — not yet finalized.
3. **Sequencing/dependency expression**: how does the plan format express ordering between minion subtasks (must subtask B wait for A's output)?
4. **Eval substrate mismatch**: SWE-bench doesn't include JIRA tickets/PDFs/multi-source context, so the "real SWE job" framing (ticket → docs → code) can only be partially exercised against it. Do we stay within SWE-bench (menial tasks = find files/summarize code/locate tests) or build/find a broader task set?
5. **Reward-hacking detection**: do we adapt EvilGenie-style methodology (held-out tests, LLM-judge, test-file-edit detection) to catch a minion gaming Gru's verification criteria, and if so, is that itself automated or an escalation trigger?
6. **Graph index build/maintenance cost**: not yet investigated — construction and incremental update cost for a structural codebase graph on real target repos (deferred; user asked to stay at design level for now).
