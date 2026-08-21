# Prompts

Actual prompt text for Gru, for the next experiment (exp2 — first experiment to introduce Gru, not just a solo minion like [exp0](../experiments/exp0/LOG.md)/[exp1](../experiments/exp1/LOG.md)). Companion to [PLAN_FORMAT.md](../PLAN_FORMAT.md) (the schema `delegate_to_minion`/`finish` calls use) and [design/architecture/01-planning.md](../design/architecture/01-planning.md)/[02-gru-minion-protocol.md](../design/architecture/02-gru-minion-protocol.md) (the research this implements).

**Scope for this experiment** (confirmed 2026-08-21): mechanical-check-and-inline-retry only. Debate-based verification ([DESIGN.md](../DESIGN.md)'s debate branch) stays deferred — still unprototyped, no debater/judge prompts drafted, and adding it now would mean designing more prompts before Gru's own is even validated.

## Revision history

**2026-08-21, corrected**: the first draft of this folder had Gru do two separate calls — reason about the *entire* plan, then convert that whole plan to JSON — before any minion ran, with a distinct third "escalation" call for handling failures. That contradicted two things already established: [02-gru-minion-protocol.md](../design/architecture/02-gru-minion-protocol.md)'s framing that Gru's planning "is not one-shot generation," and the planning-literature evidence that LLM planning accuracy collapses sharply once reality diverges from what was assumed upfront ([PlanBench-XL](../literature-review/2606.22388-planbench-xl.md): 51.9% → 11.36% for GPT-5.4 once tools are blocked/corrupted). Corrected to: **Gru runs one continuous session per task** — [gru-loop.md](./gru-loop.md) — deciding one step at a time what to delegate next, not committing to a full decomposition before anything has run.

## Gru's one prompt: the continuous loop

[gru-loop.md](./gru-loop.md) — Gru is a ReAct-style agent, structurally identical to how the minion itself already works in exp1 (`content` = reasoning, one tool call per turn = the action), just with a different toolset. Two tools: `delegate_to_minion` (hand a bounded, mechanical/verifiable piece of work to a minion) and `finish` (declare the task done, trigger the whole-task verification gate). No separate "planning call" and no separate "escalation call" — both collapse into the same loop, because Gru is already present for every delegation's result; there's nothing to re-engage it into.

### The delegation-return split (why it's not just pass/fail everywhere)

Whether a delegation returns real content or just pass/fail depends on what kind of thing was delegated — this was the key clarifying question that shaped the design:

- **Research/context-gathering** (`context_gather`, `locate`): returns actual findings. There's usually no independent check for "was this summary any good" — the content itself is the deliverable, and Gru's next reasoning step depends on it. This directly matches [02-gru-minion-protocol.md](../design/architecture/02-gru-minion-protocol.md)'s original framing: "delegate bounded information-gathering sub-calls to minions... get findings back, and keep reasoning with that grounded context."
- **Execution with a real check** (`synthesize`): returns pass/fail (+ a reference to the result) only. The mechanical check is the informative signal; Gru doesn't need to re-read the diff to keep working. This is where [DESIGN.md](../DESIGN.md)'s escalate-on-failure cost-saving mechanism actually lives — the Augment/Stencil counter-example that motivated it was specifically about the code-writing/execution tier, not research delegation.
- **Judgment calls** (`design_decision` in the old taxonomy) aren't delegated at all — no minion involved; Gru just decides, in its own reasoning turn.

### Trust the mechanical signal, don't re-verify it (the "verifiability trap")

Gru does not independently re-check content that a real mechanical check already confirmed — doing so would just be redoing the minion's work, defeating the purpose of delegating it. This isn't a relaxation of [DESIGN.md](../DESIGN.md)'s "never trust model self-report" principle, it sharpens it: the pass/fail signal must still come from a real, deterministic check (an actual test run), never from a minion's subjective claim of success — and a subtask that touches tests or verification logic can never be the one that verifies itself. What's new is specifically that *Gru* stops re-deriving a result once a real check already established it.

### Failure handling, two tiers

- **A single subtask fails its check**: routine. Gru modifies the subtask and retries, inline, in the same loop turn — no separate escalation call, since Gru is already right there. A soft cap (2-3 attempts without a materially different approach) is guidance to stop blind retrying, not a hard mechanism.
- **The whole-task `final_verification` fails despite every individual check passing**: a stronger signal — something about the overall decomposition was wrong, not one step. Gru reconsiders its approach from a wider view (keeping everything it learned — same session, not a hard reset) rather than patching the last thing it did.

## Format decisions this experiment needed (resolving PLAN_FORMAT.md's open questions, scoped to what's needed now)

[PLAN_FORMAT.md](../PLAN_FORMAT.md)'s "Open questions specific to this format" section left four things undesigned. Resolved here, scoped to this experiment, not as a permanent verdict:

1. **Single-shot vs. staged planning**: **neither, superseded** — there is no upfront plan to stage or not stage. Gru decides one delegation at a time; the "plan" is the trace of what actually happened, built incrementally, not a document written before execution starts.
2. **Symbolic reference resolution**: **orchestrator does raw content passthrough.** When a delegation's `inputs.from` names an earlier one, the orchestrator hands the minion the referenced delegation's actual output verbatim as prior context — no extraction/summarization step in between.
3. **Can Gru expand the plan mid-execution?**: **yes, by construction** — every delegation is decided in the moment, so "expanding the plan" isn't a special case requiring its own mechanism; it's just what the loop does every turn.
4. **Debate verdict re-entry**: **N/A this experiment** — no debate step exists yet.

## The minion execution prompt

[minion-execution.md](./minion-execution.md) — one shared, Jinja-templated system prompt for all three delegation types, reusing exp0/exp1's proven bash-tool-use agent loop rather than a new mechanism. Key points that took some deciding:

- **The minion sees `verification.checks` transparently** and is expected to self-check with them while working (same pattern `mini-swe-agent`'s existing agents already use) — but **the minion's self-report is never what determines pass/fail**. The orchestrator independently re-runs the same check(s) against the minion's final submitted state after its turn ends; that's the signal Gru actually receives. This is what keeps "trust the mechanical signal" (see above) from quietly collapsing into "trust the model's claim."
- **Two different submission rituals**, matched to the two return shapes: `context_gather`/`locate` write findings to a file and submit via the same `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` sentinel exp0/exp1 already use, just with a findings file instead of a patch; `synthesize` keeps exp0/exp1's exact patch-diff ritual unchanged (create patch → verify → submit as separate steps).
- **Gru's `verification.checks` are a distinct layer from the experiment's own ground truth** — they're Gru's own best-effort checks, not SWE-bench's hidden `FAIL_TO_PASS`/`PASS_TO_PASS` tests (Gru doesn't have access to those either). The real resolve/not-resolve verdict for logging results still comes from running the actual SWE-bench evaluation harness against the session's final patch, same as exp0/exp1 — this prompt's checks exist to catch problems early and cheaply, not to replace that.

## Cost attribution — a harness requirement, not just a logging preference

The actual thing this whole project is testing (per [DESIGN.md](../DESIGN.md)'s hypothesis, sharpened by Phase 2's B-vs-D comparison in [design/infra/04-machine-config.md](../design/infra/04-machine-config.md) §9) is: does a frontier Gru + self-hosted minion combination hold roughly the same resolve rate as frontier-solo, at way lower cost, because minions do most of the token-heavy work cheaply? **Exp2 itself can't test this** — it self-hosts Qwen in both roles (Phase 1's plumbing-validation scope), so there's no cost *gap* between roles to measure yet. But the harness has to track cost *per role* from the start, or that gap won't be measurable later when Phase 2 actually varies which role uses which tier.

This is mechanically straightforward given the architecture already designed here — Gru's loop is one continuous session ([gru-loop.md](./gru-loop.md)); each `delegate_to_minion` call spawns a genuinely separate minion sub-session ([minion-execution.md](./minion-execution.md)) with its own token usage — but it has to be stated as a requirement, not assumed: **every LLM call the orchestrator makes must be logged with which role it belongs to (and, for minions, which delegation `id`)**, not aggregated into one undifferentiated total. [EXPERIMENT_LOG_FORMAT.md](../EXPERIMENT_LOG_FORMAT.md) already asks for cost broken down by role in results tables — this is the harness-level mechanism that makes that possible to fill in truthfully, rather than reconstructed after the fact (which is what happened once already: exp1's cost tracking crashed on a self-hosted model and had to be recovered from raw `usage` fields post-hoc, see [experiments/exp1/LOG.md](../experiments/exp1/LOG.md) Issues).

The final artifact submitted to the real SWE-bench evaluation is just `git diff` of the shared, persistent testbed at the moment Gru calls `finish` — since every minion across every delegation operates on the same working tree, nothing needs manual accumulation across `synthesize` delegations; the repo state already carries everything.

## What's still not defined here

The orchestrator/harness code itself — how `delegate_to_minion`/`finish` tool calls actually get executed (spinning up a minion sub-session, running the real verification check independently, doing raw-passthrough context injection, looping Gru's session forward). Everything in this folder is prompt text; wiring it into a runnable harness (likely still `mini-swe-agent`-based, given exp0/exp1) is separate implementation work, not yet started.
