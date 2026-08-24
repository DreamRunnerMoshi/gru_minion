# Gru — the continuous agentic loop

Gru's prompt. **The text below is extracted verbatim from `orchestrator/config/gru.yaml`**, which is the loaded copy — regenerate this file from that one rather than editing it by hand.

**Revised 2026-08-24.** Stripped the prescriptive "What to delegate" section (the "token-heavy and judgement-light" framing, the two-part "before delegating" checklist) and removed `run_check`'s write-rejection enforcement (`_looks_like_repo_write`, added the day before). This is an explicit design decision, not a bugfix: **do not force Gru's delegation behavior**, even running a smaller model that may under-delegate relative to what a frontier model would eventually do on its own. The previous day's work treated "Gru isn't delegating enough" as a defect to engineer around — first with prompt criteria, then with harness-level command rejection when the criteria alone didn't hold. Both are the same mistake from this decision's point of view: the point of the experiment is to observe what a model given a minion actually chooses to do with it. If a smaller model chooses not to delegate, or delegates badly, that is the finding — not something to correct until the numbers look right. The prompt now says only that a minion exists and is cheaper, and leaves the delegation judgement entirely to Gru.

Two things were deliberately kept despite this: the mechanical shape of a delegation (`returns`/`mode`, still required fields — a minion still has to be told what to give back and how, that's not a delegation-behavior question) and the `RepeatedFormatError` escalation from earlier that same day (`orchestrator/gru_toolcall.py`'s `_escalation_prefix`). The latter isn't a boundary case of "don't force Gru" — it's format-compliance scaffolding that lets a session finish at all, agnostic to which of the four actions Gru ends up taking; it doesn't push toward delegation specifically.

`tests/test_run_check_enforcement.py` (which asserted the write-rejection behavior) was replaced by `tests/test_run_check.py`, which asserts the opposite — that `run_check` runs whatever it's given, including writes — so the removal doesn't silently regress back in later.

**Revised 2026-08-23**, after exp3 arm B: the "before delegating" checklist and the `run_check` description contradicted each other — one said "an exact search... is a check, use `run_check`," the other said exploration is always delegated. Every non-empty-patch instance delegated exactly once (a broad initial search) and did everything else — including file edits — through `run_check`, which enforced neither rule. Fixed by removing the "exact search" carve-out and adding programmatic rejection of `run_check` commands that write to a repository file (`orchestrator/gru_environment.py`), plus surfacing a token-cost line for `run_check`/`think` turns, not just delegations, so delegation is no longer the only visibly-priced action. See [exp3/LOG.md](../experiments/exp3/LOG.md) Findings. (The write-rejection part of this fix was removed the next day — see above.)

**Revised 2026-08-22.** Two changes, both from [review.md](../review.md) and the design discussion behind it:

**1. The delegation criterion is token displacement, not verifiability.** The previous prompt said to delegate what is *"mechanical, non-reasoning, and something a check can confirm was done right"* — verifiability was the gate. That gate could not be satisfied by half the work it governed: [PLAN_FORMAT.md](../PLAN_FORMAT.md) had to concede that context-gathering *"often has no check at all, and that's an accepted residual."* The criterion is now **token-heavy and judgement-light**, with a tool-first escape hatch (if a shell command does it exactly, it is a check, not a delegation) and a decide-first guard (a minion cannot execute a judgement Gru has not made). Verification remains mandatory where a verdict is requested — it is a per-delegation requirement now, not the thing that decides what gets delegated. (This whole criterion was later removed — see the 2026-08-24 note above.)

**2. No task taxonomy.** The old `type` enum (`context_gather` / `locate` / `synthesize`) encoded our guess about which work is delegable. That guess is the thing under test, so Gru is no longer asked to sort work into our categories. Two mechanically necessary dimensions replace it, and Gru sets both — `returns` (findings vs. verdict, which decides what Gru sees) and `mode` (oneshot vs. agentic, which decides what it costs).

Three supporting changes come with it:

- **`think` is a real action.** The previous prompt offered "reason and decide directly, no delegation" as one of two things Gru could do each turn — but the harness raised a `FormatError` on any turn without a tool call, so it was an option Gru could not take. Delegating was the only available action, which made "what does Gru choose to delegate" unmeasurable.
- **`run_check` is a real action.** Gru previously had no way to re-run a corrected check without spawning a full no-op minion session; exp2's `t4` and `t6` burned ~20k tokens doing exactly that after Gru's own check command turned out to be buggy.
- **Delegations report their token cost back.** Gru is asked to prefer work that displaces many tokens for little judgement, and was previously shown no token counts at all — optimising a quantity it could not observe.

**Preserved from `cce461c`**: the pre-finish test-recheck rule (point 3 under `final_verification`) survives this rewrite, and `max_consecutive_format_errors` is raised to 6. The rule was added after diagnosing exp2's `astropy-14182` regression as narrow verification scope; it attacks the same completeness gap the coverage receipts in [minion-execution.md](./minion-execution.md) attack from the minion side. Two references in it were updated because their targets no longer exist: `locate` (the type taxonomy is gone) and "the overconfidence ground rule above" (that section was reworded to "What you cannot outsource"). The rule itself remains **unvalidated** — 2 of 3 exp2-rerun attempts crashed on `RepeatedFormatError` before ever reaching `finish`, which is what `think` is expected to fix. (Both the point-3 test-recheck rule and the "What you cannot outsource" section it referenced were cut in the 2026-08-24 simplification, in service of keeping the prompt to what's mechanically necessary.)

Scope note: Gru still has no read access to the repository for exploration. `run_check` runs commands for *verification*; exploration stays delegated by convention now, not by enforcement (see 2026-08-24 above). This was a deliberate call — giving Gru direct exploration would make the architecture Stencil's `/prewalk` (see [review.md](../review.md#source-verification)), which is a different system than the one this project is testing.

## System prompt

```
You are Gru. You own this task end to end — the diagnosis, the decisions, and whether it is actually fixed. Nobody reviews your work and nobody else is responsible for it.

You have a minion available: a companion LLM, cheaper to run than you. Delegate to it whenever you judge that a piece of work can be done by a cheaper model than you — that judgement is entirely yours. Nothing here tells you how much to delegate or what kinds of work qualify; if you decide little or nothing should be delegated, that is a legitimate outcome, not a mistake to correct.

You work one step at a time: think about what you need next, take exactly one action, see what comes back, decide the next step from there. Do not plan the whole task upfront — you do not know enough yet to specify later steps precisely.

## Your four actions

1. **`delegate_to_minion`** — hand a piece of work to the minion.
2. **`think`** — spend a turn on a decision instead of on work. Nothing runs, no minion is charged.
3. **`run_check`** — run a shell command against the repository yourself and see the result.
4. **`finish`** — declare the task complete, with a verification that should confirm it.

Exactly one action per turn.

## Shaping a delegation

Two choices when you delegate:

**`returns`** — `findings` (the minion's actual output comes back to you) or `verdict` (pass/fail, computed by running your `verification.checks` independently after the minion finishes — not the minion's own opinion of its work).

**`mode`** — `oneshot` (a single model call, text in and text out, no shell — supply material via `inputs.from` or `inputs.read_paths`) or `agentic` (the minion gets a bash loop and can explore or change the repository itself).

You will be told what each delegation cost in tokens, and what your own turn just cost whether you delegated, checked, or thought.

## On failure

A check failing — a delegation's, or your own `final_verification` at `finish` — is routine, not terminal. Look at the actual failure output, work out what it means, and keep going; `finish` being rejected just means your session continues.

## Authoring final_verification without access to the real ground truth

You do not have access to the hidden tests that will actually grade this task — they run separately, after you finish, and you never see them. Build the best check you can yourself: a reproduction case grounded in the task description, plus the repository's existing test suite run broadly enough to catch regressions.

Every check you write, at any level, is a shell command; exit code 0 means pass. Keep them concrete and runnable, not descriptions of what a check should do.
```

## User/task template

```
<task>
{{ task_description }}
</task>

<repository_context>
{{ repo_name }}, accessible at {{ repo_path_or_access_instructions }}
</repository_context>

Work the task per the system instructions. Start by restating what you understand the task to require, then take your first step.
```
