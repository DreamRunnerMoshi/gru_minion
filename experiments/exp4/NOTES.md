# Experiment 4 — prompting alone changes when Gru considers delegating (and what it costs)

Note tracking a full day's progression, 2026-08-24: ten live runs, same instance
(`astropy__astropy-14182`), same model pair (Gru: `openrouter/deepseek/deepseek-v4-pro-0813`,
minion: `openrouter/deepseek/deepseek-v4-flash-0731`), same everything except Gru's system
prompt (runs 1-7, 9, 10) and, for run 8, the delegation-reporting mechanism itself. Full
rationale for each prompt change: [prompts/gru-loop.md](../../prompts/gru-loop.md)'s
2026-08-24 revision notes. Raw data for all ten:
`results/0N-deepseek-v4*/astropy-14182/gru.traj.json` (directories numbered `01`-`10` in the
order the runs were actually conducted). Real SWE-bench verdicts (not Gru's self-report)
for all ten: `reports/*exp4_0N-*.json`.

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
| 8 | same as 7, plus the verdict-summary mechanism (below): minion always compiles a summary Gru sees, never the raw patch | `Submitted`, verified | 53 | — | **1** | ✅ |
| 9 | + DecisionBench-inspired "When delegation is worth it" heuristic and a grounding-discipline line (below) — *reverted after this run* | `Submitted`, verified | 54 | 0 | 0 | ✅ |
| 10 | DecisionBench additions reverted; + concrete step-3 delegation rule (below) — investigation untouched, only post-diagnosis execution targeted | `Submitted`, verified | 41 | — | **1** | ✅ |

## Run 8: the verification/summary system, and the first success-with-delegation

Separate change from runs 1-7's prompt-wording iteration — this is a mechanism change,
not a wording change. Two pieces, both implemented and unit-tested
(`tests/test_delegation_flow.py::test_verdict_delegation_shows_gru_the_summary_but_not_the_raw_patch`)
before this run:

1. **Gru's prompt** (`delegation_and_verification.md`, new "What comes back" section)
   now states plainly that the minion always reports back what it did, for either
   `returns` mode — Gru is never delegating into a black box.
2. **The minion** (`config/minion.yaml`) now compiles a `summary.md` before submitting a
   verdict-mode delegation — what changed, why, and explicitly what was *not* addressed —
   separated from `patch.txt` by a `===PATCH===` marker. `gru_environment.py`'s new
   `_split_verdict_submission()` shows Gru the summary but never the raw patch; the
   independently re-run check is still the only thing that decides PASS/FAIL (the
   "verifiability trap" principle is unchanged — this adds visibility, not a new trust
   channel).

Run 8 is the first of what were, at the time, eight runs where delegation happened *and* real evaluation passed.
Mechanically, the summary system worked exactly as designed: the minion's
`delegations/t1.txt` is a clean `summary.md` + `===PATCH===` + `patch.txt`, and its
"Not addressed / notes" section reads "None" — an honest, checkable claim, since the
patch does contain both halves of the fix this time.

**Important caveat on causality**: Gru's own delegation *instruction* to the minion
(`minion_records[0].description`, `gru.traj.json`) already specified the read-path fix
(`self.data.start_line = len(self.header.header_rows) + 2`) in full, *before* delegating
— the same diagnosis quality that made runs 1-4 succeed. So this run does not show the
summary mechanism *catching* an under-scoped check after the fact (the scenario the
mechanism was built for, per runs 5-7's failure) — it shows a run where Gru's upstream
diagnosis was already correct, delegated the already-fully-specified execution, and the
new reporting mechanism worked cleanly on top of that. Whether the new prompt section
itself contributed to the better diagnosis (e.g., by front-loading "you'll see what
happened" and reducing the incentive to delegate before finishing the investigation) or
this is just this run's own sampling variance is not something one data point can
separate — turns rose to 53 from run 7's 39, which is at least consistent with more
investigation before delegating, but n=1 is n=1.

## Run 9: DecisionBench-inspired framing — correct again, but zero delegation

A different kind of change from run 8: not a delegation-reporting mechanism, but a
decision-heuristic addition to Gru's own prompt, adapted from DecisionBench's published
orchestrator prompt (user-provided). Two additions, both framed as heuristics ("what
tends to make X worth it"), not rules ("do X when Y"):

1. `actions.md` gained a short grounding-discipline paragraph: ground factual claims in
   something actually run or read, not assumption — a generalization of the project's
   existing verifiability-trap principle beyond pass/fail.
2. `delegation_and_verification.md` gained a "When delegation is worth it" section:
   delegate mechanical execution against judgment you've already formed, not because the
   minion is more skilled (it isn't — it's cheaper); don't delegate when specifying and
   verifying the work costs more than doing it yourself; don't delegate the judgment
   calls themselves (diagnosis, deciding the fix, deciding what a check needs to cover).

Result: `Submitted`, verified, **zero delegations**, 54 turns — the highest turn count of
any run so far, one above run 8's 53. Real SWE-bench evaluation: **resolved**, with the
read-path fix (`self.data.start_line = len(self.header.header_rows) + 2`) present in the
patch, entirely Gru's own work.

This is two-for-two correct since the run 5-7 failure streak (runs 8 and 9), but for
opposite reasons on the delegation axis — run 8 delegated once and succeeded, run 9
delegated zero times and succeeded. What both share is turn count in the 53-54 range,
noticeably above run 7's 39 (the last run with this same architect `role.md` but neither
of run 8 or 9's additions) and back in the range of runs 1-4. That's the closest thing to
a consistent signal across runs 7, 8, and 9: whatever additions came after run 7 —
whether the verdict-summary mechanism or the DecisionBench-style heuristics — correlate
with *more* investigation before committing to an answer, not less, and correctness
tracked that in both cases. Still n=2 beyond run 7, on one instance, so "these prompt
additions cause deeper investigation" is a hypothesis this data is consistent with, not
one it proves — see Caveat below, which now covers three broken theories plus this
fourth still-standing one.

Worth being explicit about what run 9 does *not* show: checked directly (`grep`ping
`gru.traj.json`'s messages for "minion"), the word appears exactly once across all 110
messages — in the system prompt itself. Gru never mentioned, weighed, or declined
delegation anywhere in its own reasoning; it simply never came up. So the "When
delegation is worth it" heuristic didn't *suppress* a delegation Gru was considering the
way runs 5-6's urgency wording *encouraged* one — this run doesn't exercise that heuristic
at all. Consistent with runs 1 and 4 (also zero delegation, also zero or near-zero minion
mentions) rather than with runs 2-3's "considered, then declined with a stated reason"
pattern — this instance's difficulty may simply not be shaped in a way that surfaces
delegation as a live option most of the time, independent of what the prompt says about it.

## Run 10: a concrete step-3 delegation rule — third straight success, delegated and correct

Run 9's DecisionBench-derived heuristic was reverted (never exercised — see above). In
its place, a differently-shaped change: not a heuristic to weigh, but a rule tied to a
specific point in the Recommended Workflow. `task_approach.md` now names step 3 (making
the edit) as the default delegation point, once steps 1-2 (diagnosis) have decided what
the fix is: *"delegating is the default once you know what the fix is, not something to
talk yourself out of."* Deliberately narrower than the sixth/eighth changes' "delegate as
much as possible" — this targets only post-diagnosis execution, on the hypothesis (from
the runs 5-6 analysis above) that what broke those runs was compressed *investigation*,
not compressed *execution*, so a rule that leaves steps 1-2 alone should raise delegation
without repeating the read-path-fix miss.

Result: `Submitted`, verified, **one delegation**, 41 turns. Real SWE-bench evaluation:
**resolved**, read-path fix present. Checked directly against the hypothesis — did Gru's
diagnosis stay intact, with only execution handed off? Yes, cleanly: the delegation
`description` (`minion_records[0]`, `gru.traj.json`) already spells out both halves of
the fix in full, including `self.data.start_line = len(self.header.header_rows) + 2`,
*before* delegating — Gru did steps 1-2 itself, then handed step 3 to the minion exactly
as the rule describes. The minion's `delegations/t1.txt` summary confirms it executed
precisely that spec (8 minion API calls, `Submitted`) and flags nothing as out of scope.

This is the third straight success after the run 5-7 failure streak (runs 8, 9, 10), and
the first where delegation was both **reliably triggered by a concrete rule** (not left
to chance the way run 8's incidental delegation was, or entirely absent the way run 9's
was) **and** correct — the two things every earlier attempt had managed only one of at a
time (runs 5-6: delegated, wrong; run 9: correct, no delegation). It's also the cleanest
evidence yet for the specific mechanism proposed in the runs 5-6 analysis: a delegation
push that targets only execution, leaving investigation untouched, does not reproduce the
investigation-compression failure that a whole-task push (runs 5-6) did. Still one run —
see Caveat below, updated to treat this as the current leading hypothesis, not settled.

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
  framing (run 6). Run 6 is the first of ten to actually delegate.
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

## But: runs 5, 6, and 7 were the only three (of ten) to fail real evaluation

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
run 8 (08-deepseek-v4-verified-summary):   has start_line fix: True   — resolved
run 9 (09-deepseek-v4-decisionbench):      has start_line fix: True   — resolved
run 10 (10-deepseek-v4-step3-delegation):  has start_line fix: True   — resolved
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

**Run 8 weakens the `role.md`-framing theory too.** It reused run 7's exact `role.md`
(architect/team-of-engineers, no cost-min or "as much as possible" wording) unchanged —
the only prompt-side difference from run 7 is the "What comes back" paragraph added to
`delegation_and_verification.md`, plus the mechanism change on the minion side. It
succeeded, at 53 turns. So neither "architect framing" nor "low turn count" alone
separates runs 5-7 from the rest anymore — run 8 has the framing runs 5-7 shared and the
result runs 1-4 had. The most turns-consistent read left standing after run 8: whatever
made runs 5-7 rush past the read-path requirement wasn't the role framing by itself, and
run 8's 53 turns (compared to run 7's 39, same framing) is the one variable that moved in
the direction "more investigation, correct diagnosis" would predict.

**Run 9 is a second data point consistent with that same turn-count reading, on a prompt
change that has nothing to do with the verdict-summary mechanism.** Run 9 kept run 7's
`role.md` and added the DecisionBench-derived "When delegation is worth it" section
instead — a completely different addition from run 8's — and also came in above run 7's
39 turns, at 54, also resolved. Two different post-run-7 additions, both correct, both
higher-turn-count than run 7, one with delegation and one without.

**Run 10 adds a third data point, and is the first with a plausible causal story rather
than just a turn-count correlation.** Run 9's DecisionBench additions were reverted (they
never got exercised); in their place, a rule aimed specifically at step 3 of the
Recommended Workflow — delegate the edit once diagnosis is done, leave steps 1-2 alone.
41 turns, one delegation, resolved, and the delegation's own instruction (checked
directly in `gru.traj.json`) shows the read-path fix was fully diagnosed *before*
delegating — Gru did the investigation itself, then handed off exactly the execution step
the rule names, nothing more. That's a mechanism, not just a number: a rule that targets
only post-diagnosis execution produced delegation *and* full investigation depth in the
same run, for the first time across all ten runs. Turn count (41) sits mid-pack (below
runs 8-9's 53-54, well above runs 5-7's 29-39) — so the "more turns = more correct"
reading from runs 8-9 isn't the whole story either; run 10 succeeded with meaningfully
fewer turns than runs 8-9 while still getting the diagnosis right, consistent with the
turns saved being exactly the step-3 typing work now delegated instead.

## Caveat

n=1 instance, one model pair, one task shape (a small, self-contained bug fix requiring
non-obvious two-part reasoning). Ten data points, one continuous progression under
changing conditions — not ten independent trials, and not a general claim about what
makes models delegate, hurry, or diagnose correctly. The turn-count correlation that
looked clean at n=6 (runs 1-6) did not extend cleanly to run 7, and the `role.md`-framing
theory that looked plausible after run 7 did not survive run 8. Every theory proposed
through run 8 was broken by the very next run. Runs 9 and 10 are both consistent with the
reading that survived run 8 (turn count / investigation depth, not delegation or framing,
tracks correctness) — but "consistent with" is a lower bar than "confirms," and run 10 in
particular is one run under a brand-new rule, evaluated on the same single instance every
other run in this table used. At n=1-per-condition on one instance, this project still
cannot fully distinguish a real causal mechanism from this instance's own run-to-run
variance — though run 10's design (checked directly: diagnosis stayed intact, only
execution was delegated) is the strongest evidence yet for a specific, checkable
mechanism rather than a correlation alone. Nothing here should be read as "the
verification/summary system," "the DecisionBench heuristics," or "the step-3 rule" as
proven fixes — they are three successes right after three failures, on a task that four
earlier runs (1-4) also solved without any of this machinery, and run 9 in particular
solved it with zero delegation, so no single mechanism explains all three successes.

## Next

1. **Repeat run 10's exact rule on several fresh sessions** (same instance) — it has the
   most specific, checkable causal story of any run so far (delegate only post-diagnosis
   execution, investigation stays intact), which makes it the single highest-value thing
   to try to break or confirm before trusting it over "this instance's variance."
2. **Repeat runs 8 and 9 too**, for the same reason, at lower priority now that run 10
   offers a more specific mechanism to test than "more turns" alone.
3. **Repeat runs 6 and 7's exact prompts on fresh sessions** (or a different instance) to
   check whether either earlier result — run 6's failure-with-delegation or run 7's
   failure-without-urgency — was a repeatable property of its prompt, or also just
   variance.
4. **A task genuinely too large for one context** — forcing an actual need to split
   work, rather than an efficiency judgement call — to see whether delegation happens
   for a different reason than "the prompt pushed me to," on an instance where n=1
   isn't the whole story.
5. **A different SWE-bench instance**, so any pattern found isn't entirely a property of
   this one astropy bug's specific two-part-fix shape.
