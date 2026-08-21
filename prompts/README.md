# Prompts

Actual prompt text for Gru's two call types, for the next experiment (exp2 — first experiment to introduce Gru, not just a solo minion like [exp0](../experiments/exp0/LOG.md)/[exp1](../experiments/exp1/LOG.md)). Companion to [PLAN_FORMAT.md](../PLAN_FORMAT.md) (the schema these prompts produce) and [design/architecture/01-planning.md](../design/architecture/01-planning.md) §5 (the literature-derived recommendations these prompts implement).

**Scope for this experiment** (confirmed 2026-08-21): mechanical → Gru-escalation ladder only. Debate-based verification ([DESIGN.md](../DESIGN.md)'s debate branch) stays deferred — it's still an unprototyped design branch with no debater/judge prompts drafted, and adding it now would mean designing 3 more prompts before Gru's own prompt is even validated. Matches this project's incremental-validation pattern from exp0→exp1.

## Gru has two call types here, not one

1. **Planning** ([gru-planning-reasoning.md](./gru-planning-reasoning.md) → [gru-planning-format.md](./gru-planning-format.md)) — given a task, produce a plan. Split into two separate LLM calls, not one, per [Capacity, Not Format](../literature-review/2606.09410-capacity-not-format.md): forcing schema-compliant output *while reasoning* costs 10-30% performance, worst on weaker models near their capability boundary — directly relevant since Phase 1 runs Qwen3.8-27B in the Gru role too, not a frontier model. Call 1 reasons freely in prose; call 2 is a separate, mechanical transcription-into-JSON pass that isn't allowed to introduce new content.
2. **Escalation handling** ([gru-escalation.md](./gru-escalation.md)) — given a subtask that failed mechanical verification after one retry, decide what to do. This is Gru's *only* re-engagement point in the escalate-on-failure ladder ([DESIGN.md](../DESIGN.md)'s confirmed orchestration decision) — not called on every minion completion, only on failure.

## Format decisions this experiment needed (resolving PLAN_FORMAT.md's open questions, scoped to what's needed now)

[PLAN_FORMAT.md](../PLAN_FORMAT.md)'s "Open questions specific to this format" section left four things undesigned. This experiment needs answers to three of them — resolved here, not as a permanent verdict, just enough to run:

1. **Single-shot planning** (open question 1): **yes, single-shot for this experiment.** Gru emits the entire plan in one pass before any minion runs. Staged/re-planning-after-early-results is real future work, but the escalation ladder's `amend_plan` action (see [gru-escalation.md](./gru-escalation.md)) already gives Gru a path to revise later subtasks once something concrete goes wrong — that covers the failure case single-shot planning can't handle, without needing full staged planning yet.
2. **Symbolic reference resolution** (open question 2): **orchestrator does raw content passthrough.** When subtask N's `inputs.from` names an earlier subtask, the orchestrator hands the minion the referenced subtask's actual `output_contract` content verbatim (the diff, the file list, the extracted text) as prior context — no extraction/summarization step in between. Simplest thing that works; if a subtask's raw output is too large to pass through directly, that's a real problem to hit and solve empirically, not to pre-solve here.
3. **Mid-execution plan expansion** (open question 3): **no, not outside escalation.** A minion can't spawn new subtasks on its own. If a subtask's execution surfaces something unanticipated, that's exactly what should make its mechanical check fail (or make the minion's `output_contract` visibly incomplete) and trigger escalation — `amend_plan` in [gru-escalation.md](./gru-escalation.md) is the only path to a changed plan shape.
4. **Debate verdict re-entry** (open question 4): **N/A this experiment** — no debate step exists yet.

**Schema restriction for this experiment**: `verification.method` is restricted to `mechanical` and `gru_escalation` only — `debate` is a valid value in [PLAN_FORMAT.md](../PLAN_FORMAT.md)'s general schema but the formatting prompt below rejects it, since nothing downstream can execute it yet.

## What's still not defined here

**The minion execution prompt** — how a minion is actually handed one subtask + its verification spec + upstream context, and told to produce `output_contract`-shaped output — is a separate, not-yet-drafted piece. `mini-swe-agent`'s `swebench.yaml` (used in exp0/exp1) is the closest existing template, but it was written for "solve this whole SWE-bench issue," not "execute this one Gru-authored subtask against this one verification spec" — needs its own pass, out of scope for this file.
