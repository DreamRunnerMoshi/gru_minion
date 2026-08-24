# Experiment 4 — prompting alone changes when Gru considers delegating

Short note tracking one specific finding from 2026-08-24: three live runs, same instance
(`astropy__astropy-14182`), same model pair (Gru: `openrouter/deepseek/deepseek-v4-pro-0813`,
minion: `openrouter/deepseek/deepseek-v4-flash-0731`), same everything except Gru's system
prompt — evolved once per run, each change targeting what the previous run's trajectory
showed was actually missing. Full rationale for each change: [prompts/gru-loop.md](../../prompts/gru-loop.md)'s
2026-08-24 revision notes (third/fourth/fifth). Raw data for all three:
`results/deepseek-v4*/astropy-14182/gru.traj.json`.

## The progression

| Run | Prompt change | Result | Turns | Minion mentions in Gru's reasoning | Actual delegations |
|---|---|---|---|---|---|
| 1 | baseline "don't force it" prompt, vague "cheaper" claim | `LimitsExceeded` | 80 | 0 | 0 |
| 2 | + real cost numbers (`cost_context.py`) | `Submitted`, verified | 68 | 1 — turn 66/68 | 0 |
| 3 | + `task_workflow.md` ("ask at each stage"), `boundaries.md`, same-vendor fact | `Submitted`, verified | 56 | 4 — turns 25, 26, 41, 55 | 0 |

Mechanism, not just outcome — each fix targeted a specific thing the previous run's own
reasoning trace showed was missing, and each one moved the needle on exactly that thing:

- **Run 1 → 2**: the prompt said only "cheaper," no magnitude, and a sentence explicitly
  told Gru *"if you decide little or nothing should be delegated, that is a legitimate
  outcome, not a mistake to correct."* Zero mentions of the minion across all 80 turns —
  not weighed and rejected, never considered. Replacing the vague claim with the real
  $/token numbers (still no rule) got delegation to enter Gru's reasoning for the first
  time — once, right before `finish`.
- **Run 2 → 3**: one mention, at the very end, was still a dead end — by turn 66 the
  actual work was already done, nothing left to hand off. `task_workflow.md` reframed
  delegation as a question to ask *at each stage* of the locate→reproduce→fix→verify
  shape, not a pre-finish checklist item. Result: delegation genuinely weighed three
  separate times, mid-task (turns 25, 26, 41), not once at the end.

## What it didn't fix

Zero actual `delegate_to_minion` calls across all three runs. Run 3's own reasoning
says why, directly — quoted in full in the chat session this note is tracking
(screenshot: [interesting_gru.png](../../docs/interesting_gru.png)):

> "I could hand it off to the minion, but given the boundary constraints around test
> file modifications, it's better to make the source edit myself and then run the
> verification tests." (turn 26)

`boundaries.md` (added the same run, for an unrelated reason — nothing previously
stopped Gru from touching test files when working through `run_check`) appears to be
read by Gru as a reason *against* delegating: guaranteeing a boundary is easier to do
directly than to trust a minion to also respect it. Two fixes landed in the same commit
pulling in opposite directions on the one thing they weren't both aimed at.

## Caveat

n=1 instance, one model pair, one task shape (a small, self-contained bug fix). This
tracks a within-session progression on identical conditions, not a general claim about
what makes models delegate — the "does providing more relevant context nudge Gru toward
delegating" question stays open beyond this specific case. Real SWE-bench ground truth
(not just Gru's self-report) confirms all three runs resolved the instance regardless —
see `reports/*.json` — so none of this changed *whether* the task got solved, only
*how visibly Gru considered handing pieces of it off*.

## Next

Delegation still hasn't happened once. Two directions on the table, not yet tried:
a task genuinely too large for one context (forcing an actual need to split work, not
just an efficiency judgement call), and a closer look at whether `boundaries.md` can be
worded to not read as an argument against delegating specifically.
