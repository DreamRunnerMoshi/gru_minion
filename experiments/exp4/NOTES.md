# Experiment 4 — prompting alone changes when Gru considers delegating (and what it costs)

Note tracking a full day's progression, 2026-08-24/25: twelve live runs, same instance
(`astropy__astropy-14182`), same model pair (Gru: `openrouter/deepseek/deepseek-v4-pro-0813`,
minion: `openrouter/deepseek/deepseek-v4-flash-0731`), same everything except Gru's system
prompt (runs 1-7, 9, 10, 11, 12) and, for run 8, the delegation-reporting mechanism itself.
Full rationale for each prompt change: [prompts/gru-loop.md](../../prompts/gru-loop.md)'s
2026-08-24/25 revision notes. Raw data for all twelve:
`results/0N-deepseek-v4*/astropy-14182/gru.traj.json` (directories numbered `01`-`12` in the
order the runs were actually conducted). Real SWE-bench verdicts (not Gru's self-report)
for all twelve: `reports/*exp4_0N-*.json`.

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
| 11 | `role.md` rewritten again, user-authored "Master Orchestrator" framing with a generic (non-code) menial-task delegation list; step-3 rule from run 10 still live underneath it | `Submitted`, verified | 66 | 0 | 0 | ✅ |
| 12 | + general content-based "When to delegate" default adapted from exp2 (below), no taxonomy; step-3 rule + run 11's role.md still live | `Submitted`, verified | 56 | 5 | **2** | ✅ |

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

Between run 10 and run 11, `task_approach.md`'s step-3 rule was reworded (not re-tested
before run 11): the fixed "step 3" checkpoint was replaced with a state condition plus
explicit permission to loop back to analysis — see gru-loop.md's nineteenth change,
prompted directly by a user concern that naming a specific numbered step as the
delegation trigger risked the same "LLMs are bad at planning" failure mode this project
had already flagged (PlanBench-XL, seventh change). The underlying mechanism is
unchanged; only wording that risked encouraging premature closure was removed. Run 11 is
the first live run under that reworded version.

## Run 11: role.md rewritten again, user-authored — zero delegation, still correct

A second `role.md` rewrite in one day, this one user-authored directly (not
model-drafted): a "Master Orchestrator" framing — *"You are forbidden from doing 'grunt
work' yourself... you must triage the execution plan and delegate any subtask that is a
'low-hanging fruit.'"* Its example "menial tasks" list — formatting into JSON/YAML,
basic arithmetic, extracting names/dates/keywords from text, summarizing a document — is
generic to agentic-assistant tasks in general, not adapted to this project's actual task
domain (editing source code, running tests). This version also lacks the `{{
cost_context }}` placeholder (same gap noted for the twelfth change's `role.md`, never
reintroduced since).

Result: `Submitted`, verified, **zero delegations**, 66 turns — the longest run of the
day (~14 minutes wall clock, 108 raw Gru API log lines). Real SWE-bench evaluation:
**resolved**, read-path fix present, entirely Gru's own work. Checked directly: "minion"
appears exactly once across all 134 trajectory messages — the system prompt itself, same
as run 9. Despite the most forceful wording of any run so far (*"forbidden,"* not
"delegating is the default" or "as much as possible"), delegation never entered Gru's
reasoning even once.

The likely reason, and it's a specific, checkable one rather than a vague "the model
just didn't feel like it": the delegation trigger is framed entirely around *categories
of menial task* (formatting, arithmetic, extraction, summarizing), and none of those
categories describe anything that actually came up while fixing a `RST.write()` bug —
there was no free-standing formatting task, no arithmetic, no text extraction, no
document to summarize. A forceful rule with no matching instance to fire on doesn't
fire. This is a different failure mode from run 9's (a heuristic that was too vague to
be actionable) — run 11's rule is concrete, but concretely aimed at the wrong task
shape for what this project's minion is actually used for (delegated code edits and
investigation, not menial formatting/extraction work). Also notable: `task_approach.md`'s
step-3 rule (reworded per above, still live underneath this `role.md`) didn't fire
either — Gru still made the edit itself via `run_check` rather than delegating it,
so a concrete, task-shaped rule sitting later in the prompt did not overcome a
task-mismatched rule sitting earlier in it, at least this once.

Fourth straight success after the run 5-7 failure streak (runs 8-11), the second with
zero delegation (alongside run 9) — both zero-delegation successes came from prompt
changes that pushed toward delegation through category/heuristic framing rather than a
workflow-state trigger, and both never got exercised. The one run that *did* reliably
delegate under a concrete rule (run 10) is still the only one whose rule was shaped
around this project's actual task type.

## Run 12: exp2-style content-based default — two delegations, one closing a gap the other's own summary flagged

User asked to compare against exp2's original Gru prompt (the earliest Gru/minion
version, before exp3 dropped its delegation-type taxonomy) after run 11's forceful but
task-mismatched `role.md` still produced zero delegation. exp2 framed delegation as the
*default* for a content shape — "mechanical, non-reasoning, checkable" — not an urgency
push: *"this is most of what needs to happen."* Reverting to exp2's prompt wholesale
would also revive what exp3 explicitly dropped it for (a type taxonomy that "encoded our
own guess about which work is delegable") and what exp2 was missing structurally
(`mode=oneshot`, `think`, `run_check`, per-delegation cost visibility — added later for
real bugs, not style) — and exp2's own `astropy-14182` went unresolved by Gru+minion, for
the same narrow-verification failure class runs 5-7 hit later. So instead of reverting,
`delegation.md` gained a new "When to delegate" section: exp2's content-based default,
generalized past the old taxonomy, layered on top of run 11's `role.md` and the run
10/nineteenth-change step-3 rule (neither removed).

Result: `Submitted`, verified, **two delegations** — the first run with more than one —
56 turns, resolved. Checked directly, and this is the clearest evidence yet of the
verdict-summary mechanism (exp4.8) doing exactly the job it was built for:

- **t1** (`returns=verdict`, 9 minion calls): the write-path fix (`RST.write`, plus the
  `header_rows` constructor parameter). Its own summary explicitly flags: *"Reading RST
  tables with multiple header rows is not part of this change... the scope was
  writer-side only."*
- **t2** (`returns=verdict`, 10 minion calls), delegated immediately after: *"Update
  ...rst.py so RST reading also correctly handles multiple header_rows, not just
  writing"* — sets `self.data.start_line`, the exact read-path requirement runs 5-7
  missed entirely and runs 8/10 got right only because Gru's own upstream diagnosis had
  already found it before delegating anything.

This is a different mechanism from every prior success. Runs 1-4 and 8-11 all got the
read-path fix from Gru's *own* diagnosis, before or without delegating. Run 12 is the
first case where **the gap was found and closed through the delegation loop itself**:
Gru delegated a scoped piece, the minion's summary honestly reported what it hadn't
covered, and Gru read that and delegated the fix for exactly the reported gap — the
"loop back to analysis" permission added in the nineteenth change, exercised for real,
via a second delegation rather than an inline fix. This is precisely the failure mode
the verdict-summary mechanism was built to catch (exp4.8: *"Gru never saw what was
actually changed, so had no way to notice the gap"*) — run 8 tested the mechanism's
plumbing without exercising this exact path (its diagnosis was already complete before
delegating); run 12 is the first run where the visibility itself is what closed the gap.

Fifth straight success after the run 5-7 failure streak (runs 8-12). Delegation count
across those five is now 1, 0, 1, 0, 2 — still no visible relationship to correctness on
this task — but run 12 is qualitatively different from the other four: it's the first
where delegating *contributed* to getting the fix right, rather than being incidental to
(runs 8, 10) or absent from (runs 9, 11) a diagnosis Gru had already gotten right on its
own.

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
  edit myself"* (turn 26).
  Adding an explicit trust statement didn't change the outcome, but turn 24 shows Gru
  explicitly weighing the prompt's own wording against itself: *"the instructions
  explicitly say delegate to minion if work can be done cheaper... I judged simple.
  Fine."* — aware of the instruction, still declining it on its own authority.
- **Run 4 → 5 → 6**: still zero actual delegations through run 4. Landed two
  progressively more direct pushes — an explicit cost-minimization objective (run 5),
  then an explicit "delegate as much as possible" imperative plus an architect/team
  framing (run 6). Run 6 is the first of twelve to actually delegate.
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

## But: runs 5, 6, and 7 were the only three (of twelve) to fail real evaluation

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
run 10 (10-deepseek-v4-step3-delegation):     has start_line fix: True   — resolved
run 11 (11-deepseek-v4-master-orchestrator):  has start_line fix: True   — resolved
run 12 (12-deepseek-v4-exp2-style-default):   has start_line fix: True   — resolved
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

**Run 11 breaks the run 10 pattern's generality, though not its mechanism.** A second,
user-authored `role.md` rewrite ("Master Orchestrator," forbidding self-performed
"grunt work") — the most forceful delegation wording of any of the eleven runs — produced
zero delegation, at 66 turns, still resolved. Its menial-task examples (formatting,
arithmetic, extraction, summarizing) don't describe anything in this task's actual shape,
and none fired. Notably, the reworded step-3 rule from run 10 (still live underneath this
`role.md`) *also* didn't fire — a task-shaped, previously-effective rule sitting later in
the prompt lost out to a task-mismatched rule sitting earlier in it, at least this once.
So run 10's success doesn't generalize to "any concrete delegation rule works" — it was
specifically a rule shaped around what this project's minion is actually asked to do.

**Run 12 both confirms that specificity point and adds something new.** Layering exp2's
general content-based default on top of run 11's `role.md` (neither removed) produced
delegation again — two of them — where run 11's `role.md` alone had produced zero. The
new "When to delegate" section is, like run 10's rule, shaped around this project's
actual task type (search, extraction, a fully-specified edit), not generic categories —
consistent with run 11's lesson that content-fit, not forcefulness, is what makes a
delegation rule fire. What's new is *how* the fix got found: for the first time, a
delegation's own summary (t1's "reading... is not part of this change") is the thing that
surfaced the gap, and Gru's next action was a second delegation closing exactly that gap
— not Gru re-deriving it alone (runs 1-4, 8, 10) and not the gap going unfound
(runs 5-7). This is a fourth path to a correct diagnosis, distinct from the three seen
so far (self-directed investigation; a rule triggering delegation after diagnosis is
already complete; a rule never firing at all) — and the first to show the verdict-summary
mechanism actively contributing to correctness, not just being present alongside it.

## Caveat

n=1 instance, one model pair, one task shape (a small, self-contained bug fix requiring
non-obvious two-part reasoning). Twelve data points, one continuous progression under
changing conditions — not twelve independent trials, and not a general claim about what
makes models delegate, hurry, or diagnose correctly. The turn-count correlation that
looked clean at n=6 (runs 1-6) did not extend cleanly to run 7, and the `role.md`-framing
theory that looked plausible after run 7 did not survive run 8. Every theory proposed
through run 8 was broken by the very next run. Runs 9 and 10 were both consistent with
the reading that survived run 8 (turn count / investigation depth, not delegation or
framing, tracks correctness); run 11 broke the narrower claim that run 10's specific rule
reliably triggers delegation (it didn't, once a competing `role.md` framing was layered
on top), without breaking correctness. Run 12 restored delegation on top of run 11's
`role.md` by adding a second, differently-shaped rule — but this is now three prompt
layers stacked on one instance (`role.md` twice-rewritten, the step-3 rule, the new
content-based default), and disentangling which layer is doing what is no longer possible
from outcome alone; only the delegation *chain itself* (t1's summary → t2's scope) is
directly checkable, and that part is solid. At n=1-per-condition on one instance, this
project still cannot fully distinguish a real causal mechanism from this instance's own
run-to-run variance. What's held up across five straight successes (runs 8-12), on a task
that four earlier runs (1-4) also solved without any of this machinery, is only the
correctness of the diagnosis, not any particular explanation for it — delegation has
varied freely across these five runs (1, 0, 1, 0, 2) with no visible effect on whether the
fix was right *except* in run 12, where the delegation chain was directly responsible for
finding the second half of the fix. That exception is the most specific, most directly
verifiable positive result of the whole day — but it's one occurrence, under a
now-three-layer-deep prompt, on one instance.

## Next

1. **Repeat run 12's exact prompt on several fresh sessions**, same instance — it has the
   most specific, directly-verifiable positive mechanism of any run so far (a
   delegation's own summary surfacing a gap, a second delegation closing it), and that's
   exactly the kind of one-occurrence result that most needs a repeat before it's trusted
   as more than this instance's variance.
2. **Unstack the three prompt layers now live** (`role.md`'s two rewrites, the step-3
   rule, the content-based default) and test them individually against a clean baseline
   — run 12's outcome can't currently be attributed to any one of them, only to the
   combination.
3. **Repeat run 10's exact rule alone, without run 11's role.md layered on top**, on
   several fresh sessions — still the cleanest single-rule causal story for triggering
   delegation *before* any gap needs finding, and it still needs isolation from the
   confound run 11 introduced.
4. **Repeat runs 8, 9, and 11 too**, for the same reason, at lower priority than runs 10
   and 12 since neither offers as specific a mechanism to test.
5. **Repeat runs 6 and 7's exact prompts on fresh sessions** (or a different instance) to
   check whether either earlier result — run 6's failure-with-delegation or run 7's
   failure-without-urgency — was a repeatable property of its prompt, or also just
   variance.
6. **A task genuinely too large for one context** — forcing an actual need to split
   work, rather than an efficiency judgement call — to see whether delegation happens
   for a different reason than "the prompt pushed me to," on an instance where n=1
   isn't the whole story.
7. **A different SWE-bench instance**, so any pattern found isn't entirely a property of
   this one astropy bug's specific two-part-fix shape.

## Token and cost spent, all twelve runs

Pulled directly from each run's `cost_summary.json` (`gru.total_tokens`/`gru.cost`, and
per-delegation `prompt_tokens`/`completion_tokens` from `minions[]`). Minion dollar cost
isn't recorded directly — computed here from the same real OpenRouter per-token pricing
`cost_context.py` uses (`deepseek-v4-flash-0731`: $0.14/$0.28 per M input/output tokens,
vs. `deepseek-v4-pro-0813`'s $1.32/$3.96 — the same ~9-14x-per-token, "20-30x cheaper
after cache effects" ratio given to Gru in `role.md`'s `{{ cost_context }}`, where that
placeholder was present).

**Total tokens is a misleading proxy for `$` here — cache-hit tokens are billed at
essentially $0, not the standard per-token rate.** Confirmed by solving each run's
`gru.cost` backward: it reproduces exactly as `non_cached_prompt_tokens × $1.32/M +
completion_tokens × $3.96/M`, with cached tokens contributing ~$0.00001/M — noise. This
is why run 1 (2.46M total tokens, $0.2333) cost *less* than run 2 (2.35M total tokens —
fewer — but $0.5440): run 1's cache hit rate was 95.9% (only 99,496 of 2.43M prompt
tokens were fresh), run 2's was 86.1% (322,127 fresh — 3.2x more, despite a lower total).
Whatever changed run 2's prompt prefix stability (it's the run that added
`cost_context.py`'s dynamic cost line) cost more in cache misses than it saved anywhere
else. Reading this table by total tokens instead of $ will get the ranking wrong in
cases like this one — $ is the number that matters, not tokens.

| Run | Gru tokens | Gru $ | Delegations | Minion tokens | Minion $ | Total $ | % spent on Gru |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2,459,958 | $0.2333 | 0 | 0 | $0.0000 | $0.2333 | 100.0% |
| 2 | 2,345,477 | $0.5440 | 0 | 0 | $0.0000 | $0.5440 | 100.0% |
| 3 | 1,766,452 | $0.2229 | 0 | 0 | $0.0000 | $0.2229 | 100.0% |
| 4 | 1,070,496 | $0.1962 | 0 | 0 | $0.0000 | $0.1962 | 100.0% |
| 5 | 487,159 | $0.0997 | 0 | 0 | $0.0000 | $0.0997 | 100.0% |
| 6 | 637,056 | $0.2107 | 1 | 15,090 | $0.0022 | $0.2130 | 98.9% |
| 7 | 861,359 | $0.1351 | 0 | 0 | $0.0000 | $0.1351 | 100.0% |
| 8 | 1,910,206 | $0.2259 | 1 | 121,338 | $0.0175 | $0.2434 | 92.8% |
| 9 | 1,395,879 | $0.1885 | 0 | 0 | $0.0000 | $0.1885 | 100.0% |
| 10 | 738,528 | $0.2380 | 1 | 27,472 | $0.0041 | $0.2421 | 98.3% |
| 11 | 2,223,160 | $0.4686 | 0 | 0 | $0.0000 | $0.4686 | 100.0% |
| 12 | 1,761,530 | $0.4049 | 2 | 80,271 | $0.0120 | $0.4169 | 97.1% |

Three things stand out, all bearing directly on exp5's stated interest in token savings.

**First, run 10 — not run 12 — is the day's actual best result once cost is the metric.**
Both resolved. Run 12's two-delegation chain is the more mechanistically interesting one
(a delegation's own summary caught a gap, a second delegation closed it — see below), but
it cost 72% more overall ($0.4169 vs. $0.2421) for the identical correctness outcome.
The gap isn't just more turns (56 vs. 41, +37%) — average tokens *per turn* were also
~75% higher (31,456 vs. 18,013), so the two effects compound. The likely mechanism: run
10's pattern was diagnose-completely-then-delegate-once, paying delegation overhead
(description, checks, minion trajectory, observation) a single time; run 12 paid that
overhead twice, plus whatever extra context accumulated discovering the gap between the
two delegations. **The mechanistically richest delegation pattern and the cheapest one
were different runs** — worth remembering before treating "delegation did something
interesting" as the same claim as "delegation saved money."

**Second, delegation's share of total spend has been tiny in every run, including run
10.** Even run 10's single, efficient delegation was only 1.7% of that run's total cost
($0.0041 of $0.2421); run 12's two delegations, despite being the largest delegation
share of the day, were still 2.9%. Run 8's 121,338-token single delegation (the largest
individual delegation of the day) was 7.2% of its run's total — the ceiling observed all
day. None of these runs have actually tested the project's core cost-asymmetry hypothesis
at scale — that meaningful *volume* of work shifts to the cheap model — because
delegation has stayed small and occasional everywhere, not "most of what needs to
happen" the way exp2's and run 12's own prompt wording asked for. This is the real gap
exp5 needs to close, not just "does Gru delegate at all," and not just "does a delegation
chain self-correct" — *whether delegated work can be a large fraction of total spend
while staying correct* is still completely untested.

**Third, Gru's own token spend has nothing to do with whether it delegates.** The
cheapest run (5, $0.10, forced/hurried, wrong) and one of the most expensive (11, $0.47,
zero delegation, correct) bracket the whole range; delegation status doesn't predict
where a run falls. Gru's cost is driven by turn count and how much repeated context
(cache misses, file re-reads) accumulates over a session — the same variable the
turn-count/investigation-depth reading has been tracking all day for *correctness* — not
by how much work it handed off.

## Conclusion — closing exp4

Twelve runs, one instance, one model pair, a single evolving prompt: the honest state of
the hypothesis ("does Gru delegate, and does prompting alone move that without breaking
correctness") is a specific, evidenced *shape*, not a settled answer.

**What's supported by more than one run:**

- **Delegation does not track correctness on this task**, in either direction. 10 of 12
  runs resolved; delegation count across the resolved runs ranged 0-2 with no visible
  pattern. The two unresolved runs (5, 6) both delegated urgency-pushed, compressed
  investigation, not lack of delegation itself.
- **Urgency-based pushes ("minimize cost," "as much as possible") are the one thing that
  reliably broke correctness** (runs 5-6), by compressing investigation before diagnosis
  was actually done — not by delegation itself, since run 6's minion executed its
  fully-specified instruction perfectly.
- **Forceful wording alone does not reliably produce delegation.** Two of the four most
  forceful prompts tried (run 6's "as much as possible," run 11's "forbidden... grunt
  work") differ completely in outcome (delegated / didn't) — what predicted firing was
  whether the rule's *content* matched this task's actual shape (code search, edits,
  verification), not how strongly it was worded. Run 11's generic menial-task categories
  never fired regardless of how forcefully they were stated; run 10 and run 12's
  task-shaped, non-urgent rules did.
- **The verdict-summary visibility mechanism (exp4.8) is a real, positive, checkable
  contribution independent of the delegation-rate question.** Run 12 is direct evidence:
  a delegation's own honest summary ("scope was writer-side only") is what let Gru find
  the second half of a two-part fix through the delegation loop itself, not through its
  own re-derivation. This held up regardless of which delegation-trigger wording was
  layered on top of it, and is the single most mechanically verifiable finding of the
  day — but it is not the same finding as "cheapest correct run": that's run 10, at 58%
  of run 12's total cost, from a single well-specified delegation after diagnosis was
  already complete. Mechanistically interesting and cost-efficient turned out to be two
  different runs, not one — worth keeping separate when exp5 decides what "success"
  means for a prompt change.

**What this argues for going into exp5**, matching the project's original commitment to
not force Gru's behavior: keep delegation rules **content-shaped and state-conditioned**
("delegate this kind of work, once you actually know what it is") rather than **urgency-
or forcefulness-driven** ("as much as possible," "forbidden from"). The evidence this day
produced is that the former can raise delegation without the investigation-compression
failure the latter reliably causes — not because it's gentler, but because it targets a
different thing (what counts as delegable) instead of pressuring the pace of work. That's
a real constraint on how exp5's prompt work should proceed, not just a stylistic
preference: rules should keep naming *content* ("mechanical, checkable, already-decided"),
never *pace* ("quickly," "as much as possible," "minimize cost").

**What exp4 leaves genuinely open, and what exp5 should treat as its starting brief:**

1. Every one-off result in this note (run 10's step-3 mechanism, run 12's self-correcting
   chain) is n=1 on one instance — none has been repeated, and the two zero-delegation
   successes (9, 11) show a forceful rule can simply never fire without necessarily
   breaking anything, which means "success" alone doesn't validate a delegation rule.
2. Delegation's share of total token spend has never exceeded ~7% of a run's cost, even
   on the day's best result. exp5's "look into token saving" needs to treat this as the
   actual open question — not "does delegation happen" but "can it happen at a volume
   large enough to matter to total cost" — which likely means prompt rules that shift
   more than one or two bounded pieces of work per run, and/or a task shape where more
   of the work is genuinely delegable in the first place (see item 6 under Next).
3. The three prompt layers now live (`role.md` twice-rewritten, the step-3 rule, the
   content-based default) have never been tested apart from each other. exp5 should
   start from a clean, single-layer baseline per condition, not by continuing to stack
   changes on top of exp4's end state.
