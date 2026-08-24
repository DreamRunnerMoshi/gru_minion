# Experiment 4 — prompting alone changes when Gru considers delegating (and what it costs)

Note tracking a full day's progression, 2026-08-24: seven live runs, same instance
(`astropy__astropy-14182`), same model pair (Gru: `openrouter/deepseek/deepseek-v4-pro-0813`,
minion: `openrouter/deepseek/deepseek-v4-flash-0731`), same everything except Gru's system
prompt — evolved once per run, each change targeting what the previous run's trajectory
showed was actually missing. Full rationale for each change: [prompts/gru-loop.md](../../prompts/gru-loop.md)'s
2026-08-24 revision notes. Raw data for all seven:
`results/0N-deepseek-v4*/astropy-14182/gru.traj.json` (directories numbered `01`-`07` in the
order the runs were actually conducted). Real SWE-bench verdicts (not Gru's self-report)
for all seven: `reports/*exp4_0N-*.json`.

## The progression

| Run | Prompt change | Result | Turns | Minion mentions | Delegations | Real SWE-bench resolved? |
|---|---|---|---|---|---|---|
| 1 | baseline "don't force it" prompt, vague "cheaper" claim | `LimitsExceeded` | 80 | 0 | 0 | ✅ |
| 2 | + real cost numbers (`cost_context.py`) | `Submitted`, verified | 68 | 1 — turn 66/68 | 0 | ✅ |
| 3 | + `task_workflow.md` ("ask at each stage"), `boundaries.md`, same-vendor fact | `Submitted`, verified | 56 | 4 — turns 25, 26, 41, 55 | 0 | ✅ |
| 4 | + rounded cost bucket, explicit trust, dropped planning-style sentence | `Submitted`, verified | 41 | 1 — turn 29 | 0 | ✅ |
| 5 | + explicit objective: *"minimize cost as much as possible"* | `Submitted`, verified | 29 | 2 — turns 18, 24 | 0 | ❌ |
| 6 | `role.md` rewritten (architect/team-of-engineers metaphor) + *"delegate tasks to minion as much as possible"* | `Submitted`, verified | 31 | — | **1** | ❌ |
| 7 | same architect framing, urgency wording stripped back out (no cost-min objective, no "as much as possible") | `Submitted`, verified | 39 | 0 | 0 | ❌ |

Mechanism, not just outcome, for runs 1→4 — each fix targeted a specific thing the
previous run's own reasoning trace showed was missing, and each one moved the needle on
exactly that thing:

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
- **Run 3 → 4**: `boundaries.md` (added run 3, for an unrelated reason) was being read as
  a reason *against* delegating — *"I could hand it off to the minion, but given the
  boundary constraints around test file modifications, it's better to make the source
  edit myself"* (turn 26, screenshot: [interesting_gru.png](../../docs/interesting_gru.png)).
  Adding an explicit trust statement didn't change the outcome, but turn 24 shows Gru
  explicitly weighing the prompt's own wording against itself: *"the instructions
  explicitly say delegate to minion if work can be done cheaper... I judged simple.
  Fine."* — aware of the instruction, still declining it on its own authority.
- **Run 4 → 5 → 6**: still zero actual delegations through run 4. Landed two
  progressively more direct pushes — an explicit cost-minimization objective (run 5),
  then an explicit "delegate as much as possible" imperative plus an architect/team
  framing (run 6). Run 6 is the first of seven to actually delegate.
- **Run 6 → 7**: stripped the urgency wording back out — kept the architect/team-of-
  engineers role framing, dropped the cost-minimization objective and the "delegate as
  much as possible" imperative. Delegation dropped straight back to zero (as expected,
  since the direct push was the thing removed). Turn count rose to 39 — more than run 6's
  31, closer to run 4's 41 — but the result was still wrong. See "But" section below:
  this breaks the clean "hurry = miss it" reading runs 5-6 suggested.

## Run 6: delegation finally happened — mechanically clean, and cheap

Gru delegated the actual edit (`mode=agentic`, `returns=verdict`), with the exact code
already decided (down to `idx = len(self.data.header_rows)`) — the minion's job was
execution plus self-checking, not diagnosis. Cost: minion ~$0.001 (15,090 tokens, mostly
cache-hit), Gru $0.211 — the delegation itself cost roughly 0.5% of Gru's own spend, the
cost asymmetry the project's underlying hypothesis is actually about, realized for the
first time. The delegation's `verification.checks` were real, independently re-run
commands (not the minion's self-report) — the "verifiability trap" mechanism worked
exactly as designed at the mechanical level.

## But: runs 5, 6, and 7 are the only three of seven to fail real evaluation

Checked directly, not inferred — every patch's diff, `grep`ped for the fix's read-path
line, cross-checked against the real `swebench.harness` report in `reports/`:

```
run 1 (01-deepseek-v4):                    has start_line fix: True   — resolved
run 2 (02-deepseek-v4-costctx):            has start_line fix: True   — resolved
run 3 (03-deepseek-v4-workflow):           has start_line fix: True   — resolved
run 4 (04-deepseek-v4-trust):              has start_line fix: True   — resolved
run 5 (05-deepseek-v4-forced):             has start_line fix: False  — NOT resolved
run 6 (06-deepseek-v4-architect):          has start_line fix: False  — NOT resolved
run 7 (07-deepseek-v4-architect-softened): has start_line fix: False  — NOT resolved
```

The bug fix needs two things: make `RST.write()` handle N header rows (visible directly
in the PR's literal example), and set `self.data.start_line` so reading a written table
back also accounts for N header rows (not in the PR's example — only surfaces from
tracing how `FixedWidth` reading actually works). Runs 1-4 all found and fixed both;
runs 5, 6, and 7 found only the first.

**Whose fault, run 6**: the minion's, not at all. It received a fully-specified
instruction from Gru, executed it exactly, and Gru's own re-run checks (not the
minion's self-report) passed — because Gru's own checks, both at the delegation and at
`finish`, only ever tested writing, never reading a table back. The defect is entirely
upstream: Gru's diagnosis never identified the read-path requirement, before it ever
delegated anything.

**The clean "hurry up" story from runs 5-6 doesn't fully survive run 7.** Runs 5 and 6
both failed at low turn counts (29, 31) under prompt wording that explicitly pushed
toward finishing fast — one framed around cost, the other around delegating "as much as
possible." That pattern predicted run 7, with the push removed, would recover both the
turn count *and* the correctness of runs 1-4. It recovered the turn count (39 — above
run 6's 31, close to run 4's 41) but not the correctness: the read-path fix is still
missing, delegation is back to zero, and the extra ~8 turns over run 6 didn't buy the
one insight that mattered.

So the picture is more tangled than "hurry up" alone explains:

- Run 5 failed under an explicit **cost-minimization objective** — 29 turns, no
  delegation.
- Run 6 failed under an explicit **"delegate as much as possible" imperative** plus a
  new architect/team-of-engineers role framing — 31 turns, one delegation.
- Run 7 failed with **both explicit pushes removed**, keeping only the architect/team
  framing — 39 turns, zero delegation.

Turn count alone doesn't cleanly separate the three failures from the four successes
(run 7 at 39 turns sits inside the successful range of runs 1-4, not below it). What's
common to runs 5, 6, and 7 but absent from runs 1-4 is the architect/team-of-engineers
`role.md` rewrite itself, introduced at run 6 and never reverted — runs 5 and 7 both
postdate or share elements of that framing shift in ways the turn-count story alone
doesn't capture. This note is not claiming that's proven either; it's flagging that
"prompt urgency compresses investigation" is not the whole explanation, and the honest
open question is now *which specific piece of the role/framing change (if any), as
opposed to sampling variance on this one instance, is responsible* — not something this
data can settle.

## Caveat

n=1 instance, one model pair, one task shape (a small, self-contained bug fix requiring
non-obvious two-part reasoning). Seven data points, one continuous progression under
changing conditions — not seven independent trials, and not a general claim about what
makes models delegate or hurry. The turn-count correlation that looked clean at n=6
(runs 1-6) does not extend cleanly to run 7 — see above — so neither "hurrying costs
thoroughness" nor any alternative explanation is settled by this data; both need a
repeated run under identical prompts, or a different task instance, before either can be
trusted.

## Next

Two candidates, not yet tried:
1. **Repeat runs 6 and 7's exact prompts on fresh sessions** (or a different instance) to
   check whether either result — run 6's failure-with-delegation or run 7's
   failure-without-urgency — is a repeatable property of its prompt, or this run's own
   sampling variance. Run 7 in particular now needs this before anything is concluded
   from it.
2. **A task genuinely too large for one context** — forcing an actual need to split
   work, rather than an efficiency judgement call — to see whether delegation happens
   for a different reason than "the prompt pushed me to," and whether that version
   preserves investigation depth better than an explicit imperative does.
