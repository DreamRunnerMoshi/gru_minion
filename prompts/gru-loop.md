# Gru — the continuous agentic loop

Gru's prompt. **The "System prompt" block below is the `gru.yaml` variant's text, composed from fragments** under `orchestrator/prompts/gru/` — regenerate it from `orchestrator/prompt_fragments.compose(...)` rather than editing it by hand (`.venv/bin/python -c "from orchestrator.gru_config import load_gru_config; print(load_gru_config('gru.yaml')['agent']['system_template'])"`). It contains a `{{ cost_context }}` placeholder resolved at session-start, not at compose time — see the next note.

**Revised 2026-08-24, seventh change: dropped the one-step-at-a-time / no-upfront-planning sentence from `role.md`.** Explicit user framing: "let Gru solve the problem as it sees fit, we will only instruct Gru to delegate task." Safe to drop cleanly rather than partially — the mechanical fact half of that sentence ("take exactly one action") is stated independently and unconditionally by `actions_footer.md` ("Exactly one action per turn."), always included right after the four action bullets, so nothing about the hard one-tool-call-per-turn interface constraint is lost; only the planning-philosophy half goes away. Worth remembering if this ever gets revisited: that half wasn't arbitrary — it traced back to PlanBench-XL evidence (planning accuracy collapses once reality diverges from what was assumed upfront, see the 2026-08-21 correction earlier in this file's history) about why Gru shouldn't front-load a plan. Not reintroduced here; recorded so the reasoning isn't lost if a future run's trajectory suggests Gru is doing exactly the upfront-planning thing that sentence existed to prevent.

**Revised 2026-08-24, sixth change: rounded cost ratio, explicit trust, vendor-revenue framing.** Motivated directly by `experiments/exp4/NOTES.md`'s finding: run 3's own reasoning (turn 26) declined to delegate specifically *because* of `boundaries.md`'s content — *"I could hand it off to the minion, but given the boundary constraints around test file modifications, it's better to make the source edit myself"* — reading enforcing a boundary as safer to guarantee directly than by trusting the minion to also respect it. Three explicit user-directed changes to `cost_context.py`/`role.md`:

1. **Cost ratio rounded to a bucket** (`_round_ratio`) — "roughly 20x to 30x less per token" instead of exact per-token prices. Same underlying fact, just not precise enough to read as something to compute with.
2. **Explicit trust statement** in `role.md`: *"You can trust it to do what you ask, exactly as instructed."* Directly answers the turn-26 friction — a stated fact about reliability, not a rule about when to delegate.
3. **Same-vendor economics, extended**: the existing same-family fact (`_vendor`) now also states *why* it matters — *"spending on the minion stays with your own vendor, not a competitor's"* — real only when the vendor segments actually match (openrouter/\<vendor\>/... shape), omitted otherwise, same as the cost figures.

Not yet run live — next diagnostic pass is whether turn-26-style boundary-triggered refusals still happen with the trust sentence in place.

**Revised 2026-08-24, fifth change: task_workflow + boundaries fragments, `<pr_description>` wrapper.** Both live DeepSeek runs (third/fourth changes below) raised the question of whether Gru's prompt was simply thinner than a solo agent's — missing the stock SWE-bench prompt's boundaries ("DO NOT MODIFY: tests, configuration files" — a real, current gap: nothing stops Gru from touching test files when it works via `run_check`, which is most of the time) and its recommended workflow (analyze → reproduce → edit → verify → edge cases). Explicit user framing settled it: deployed for real, a user just gives Gru an instruction and expects it followed with the rigor a solo coding agent would bring — delegation is an internal efficiency mechanism, not something that should mean *less* context reaches Gru than a solo deployment would get.

Not a verbatim copy of the stock prompt (`.venv/.../minisweagent/config/benchmarks/swebench.yaml`), though — it assumes a raw `bash` tool and a shell-echo submission ritual (`echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt`), neither of which fits Gru's actual interface (`delegate_to_minion`/`think`/`run_check`/`finish` — `finish` already *is* the submission mechanism, no ritual needed at Gru's level; that ritual was already correctly minion-only). Pasting it in unmodified would have told Gru to call a tool it doesn't have. Adapted instead: `boundaries.md` carries the do-not-modify guidance reworded for Gru's actual situation (applies whether it edits directly or delegates); `task_workflow.md` carries the workflow shape, with each step framed as a live "is this delegation-shaped?" question rather than solo-agent instructions. That framing is a direct response to the diagnostic below it: delegation was mentioned in Gru's reasoning exactly once across two full runs, at turn 66 of 68, as a pre-`finish` afterthought after all the real work was already done — `task_workflow.md` tries to surface the question at each stage instead of only at the end. `instance_template` now wraps the task in `<pr_description>` exactly as the stock prompt does — that part transfers with zero adaptation needed.

**Revised 2026-08-24, third change: real cost numbers instead of a vague "cheaper" claim, dropped the sentence pre-authorizing zero delegation.** First live run under the second change's "don't force it" prompt (DeepSeek V4 Pro planning, V4 Flash executing, over OpenRouter — the first genuinely different-cost model pair this project has run) delegated **zero times across all 80 turns**, hit `LimitsExceeded` without ever calling `finish`, and still produced a substantively correct patch entirely through `run_check`. Same behavior exp3's self-hosted Qwen showed — not a capability artifact, apparently, but it leaves the project's actual cost hypothesis untestable: no delegation means nothing to compare. `role.md` previously said only "cheaper," no magnitude, and explicitly told Gru that *"if you decide little or nothing should be delegated, that is a legitimate outcome, not a mistake to correct"* — read back after this run, that sentence is closer to a nudge away from delegating than a neutral one.

Resolution (explicit user decision, one of three considered — restoring a soft delegation nudge, or leaving the prompt alone and treating the null result as the finding): **give Gru the real number, still no rule.** `orchestrator/cost_context.py`'s `describe_cost_ratio(gru_model, minion_model)` looks up real per-token pricing (litellm's registry first, falling back to OpenRouter's live catalog for models too new to be in it yet — confirmed needed: litellm had Pro priced the same day but not Flash) and renders a factual sentence — *"you cost $X/$Y per million input/output tokens; the minion costs $A/$B — about Nx/Mx cheaper per token"* — with the actual DeepSeek pair's numbers. No real pricing (self-hosted models, Phase 1's original design) means the sentence is omitted, not fabricated. This is a fact injected into the prompt, still not an instruction — the "that judgement is entirely yours" sentence right after it is unchanged. `{{ cost_context }}` is a Jinja variable resolved per-session (via `gru_agent.run(..., cost_context=...)`, since it depends on which models this particular run uses), not baked into the fragment at compose time.

**Revised 2026-08-24, second change: modularized into fragments + `ToolPolicy`.** `gru.yaml`'s system prompt was one hand-written block; trying a leaner variant meant either duplicating shared paragraphs into a second block or hand-editing the one that existed. Split it into small reusable pieces (`orchestrator/prompts/gru/*.md`) that a config now lists (`agent.system_template_fragments`) instead of embedding text directly — `gru.yaml` renders to the same prompt it always did, just assembled instead of typed once.

Prompt text alone couldn't express "no verification step, no failure handling" honestly, though — `finish` mechanically required a non-empty `final_verification.checks` and `delegate_to_minion` mechanically required `verification.checks` whenever `returns='verdict'`, regardless of what the prompt said about them. So `orchestrator/gru_toolcall.py` gained `ToolPolicy`: four independent toggles (`allow_think`, `allow_run_check`, `allow_verdict`, `require_finish_verification`) that shape the actual tool schemas sent to the model (`build_tools(policy)`) and the validation applied to what comes back (`parse_gru_actions(..., policy=policy)`), not just the wording around them. A tool or field the policy excludes is rejected the same way an unknown tool name always was — not silently accepted because the prompt just didn't mention it. `orchestrator/config/gru-minimal.yaml` is the first config to use this: fragments for just `role` + `delegate_to_minion` + a bare `finish`, and a policy that turns off `think`, `run_check`, `verdict` delegations, and finish verification entirely — see "The fragment library and bit-by-bit variants" below.

This is deliberately the only thing `ToolPolicy` does: define which session is running (what exists to be used at all), never nudge how Gru uses what it's given — same principle as the first 2026-08-24 change below, just extended to the two places prompt wording alone couldn't reach.

**Revised 2026-08-24, first change.** Stripped the prescriptive "What to delegate" section (the "token-heavy and judgement-light" framing, the two-part "before delegating" checklist) and removed `run_check`'s write-rejection enforcement (`_looks_like_repo_write`, added the day before). This is an explicit design decision, not a bugfix: **do not force Gru's delegation behavior**, even running a smaller model that may under-delegate relative to what a frontier model would eventually do on its own. The previous day's work treated "Gru isn't delegating enough" as a defect to engineer around — first with prompt criteria, then with harness-level command rejection when the criteria alone didn't hold. Both are the same mistake from this decision's point of view: the point of the experiment is to observe what a model given a minion actually chooses to do with it. If a smaller model chooses not to delegate, or delegates badly, that is the finding — not something to correct until the numbers look right. The prompt now says only that a minion exists and is cheaper, and leaves the delegation judgement entirely to Gru.

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

You have a minion available: a companion LLM, cheaper to run than you.{{ cost_context }} You can trust it to do what you ask, exactly as instructed. Delegate to it whenever you judge that a piece of work can be done by a cheaper model than you — that judgement is entirely yours.

## A useful shape for this kind of task

1. Locate the code the problem actually touches.
2. Get, or write, a reproduction of the reported issue — confirm it currently fails before you have a fix.
3. Decide what the fix should be.
4. Apply it.
5. Re-run the reproduction, and the relevant existing tests, to confirm.

Any of these can be something you do yourself or hand to the minion — the shape of the task is the same either way. Worth asking at each stage, not just at the end: is this specific piece of work something a cheaper model could do for you right now?

## Boundaries

Modify regular source files to fix the issue, in a way that is general and consistent with the codebase — not a narrow patch for the literal example in the task. Do not modify test files, or configuration/build/packaging files (pyproject.toml, setup.cfg, and similar), unless the task explicitly calls for it. This applies whether you make the change yourself or hand it to the minion — if you delegate, the minion needs the same boundary, not just you.

## Your actions

- **`delegate_to_minion`** — hand a piece of work to the minion.

- **`think`** — spend a turn on a decision instead of on work. Nothing runs, no minion is charged.

- **`run_check`** — run a shell command against the repository yourself and see the result.

- **`finish`** — declare the task complete, with a verification that should confirm it.

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

## The fragment library and bit-by-bit variants

Fragments live under `orchestrator/prompts/gru/`, one small piece of prompt text per file:

| Fragment | Contains |
|---|---|
| `role.md` | Who Gru is, that a minion exists, one-step-at-a-time framing. Always included. |
| `task_workflow.md` | The locate → reproduce → fix → verify shape, each step framed as a live delegation question. |
| `boundaries.md` | Modify source, don't modify tests/config unless asked — applies whether Gru or the minion does the work. |
| `actions_header.md` | `## Your actions` |
| `action_delegate.md` | The `delegate_to_minion` bullet. Always included. |
| `action_think.md` | The `think` bullet. |
| `action_run_check.md` | The `run_check` bullet. |
| `action_finish.md` | The `finish` bullet, mentioning verification. |
| `action_finish_bare.md` | The `finish` bullet without mentioning verification — for a session where it isn't required. |
| `actions_footer.md` | `Exactly one action per turn.` |
| `delegation_shape.md` | Full `returns`/`mode` explanation (both `findings` and `verdict`). |
| `delegation_shape_findings_only.md` | `mode`-only explanation, for a session where `verdict` isn't offered. |
| `failure_handling.md` | The "On failure" section. |
| `verification_guidance.md` | The "Authoring final_verification" section. |

A config picks a list (`agent.system_template_fragments`) and, if it wants anything other than the fully-permissive default, a `tool_policy` block (`allow_think`, `allow_run_check`, `allow_verdict`, `require_finish_verification` — see the second 2026-08-24 revision note above for why the policy exists separately from the fragment choice). `orchestrator/gru_config.load_gru_config(filename)` resolves both; `run_gru_session.py` and `tests/harness.py` both call it instead of a plain `yaml.safe_load`.

**Variants so far:**

- **`gru.yaml`** — the full set: all four actions, `verdict` delegations allowed, `finish` requires verification, `task_workflow`/`boundaries` included. This file's own prompt, above.
- **`gru-minimal.yaml`** (2026-08-24) — step 1 of a bit-by-bit ablation: `role` + `action_delegate` + `action_finish_bare` + `delegation_shape_findings_only`, policy turns off `think`, `run_check`, `verdict`, and finish verification entirely. Just delegation and handling whatever comes back — see that file's own header comment for the rationale. Deliberately does not include `task_workflow`/`boundaries` either, added to `gru.yaml` after this variant existed — they're about task-solving rigor, not the verification/failure-handling dimension this variant ablates, so adding them would mix two things being tested separately. `tests/test_minimal_variant.py` confirms the excluded pieces are genuinely rejected, not just unmentioned.

**Adding the next step** (add verification back, then failure handling, then think/run_check) is additive: point a new config at `gru-minimal.yaml`'s fragment list plus the piece being reintroduced (e.g. `+ verification_guidance`, `require_finish_verification: true`), rather than writing a new prompt from scratch or editing `gru-minimal.yaml` in place.

`load_gru_config` still falls back to a literal `agent.system_template` block for any config not converted to fragments — nothing currently uses that path (`gru-taxonomy.yaml`, the old arm A taxonomy control, was deleted 2026-08-24: deferred per exp3/LOG.md's Conclusion and never actually run), but the fallback stays so a future config doesn't have to be fragment-based to work.

## User/task template

```
<pr_description>
Consider the following PR description:
{{ task_description }}
</pr_description>

<repository_context>
{{ repo_name }}, accessible at {{ repo_path_or_access_instructions }}
</repository_context>

Work the task per the system instructions. Start by restating what you understand the task to require, then take your first step.
```
