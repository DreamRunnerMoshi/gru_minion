# Experiment 4 — prompting alone changes when Gru considers delegating (and what it costs)

Note tracking a full day's progression, 2026-08-24: six live runs, same instance
(`astropy__astropy-14182`), same model pair (Gru: `openrouter/deepseek/deepseek-v4-pro-0813`,
minion: `openrouter/deepseek/deepseek-v4-flash-0731`), same everything except Gru's system
prompt — evolved once per run, each change targeting what the previous run's trajectory
showed was actually missing. Full rationale for each change: [prompts/gru-loop.md](../../prompts/gru-loop.md)'s
2026-08-24 revision notes (third through twelfth). Raw data for all six:
`results/deepseek-v4*/astropy-14182/gru.traj.json`. Real SWE-bench verdicts (not
Gru's self-report) for all six: `reports/*.json`.

## The progression

| Run | Prompt change | Result | Turns | Minion mentions | Delegations | Real SWE-bench resolved? |
|---|---|---|---|---|---|---|
| 1 | baseline "don't force it" prompt, vague "cheaper" claim | `LimitsExceeded` | 80 | 0 | 0 | ✅ |
| 2 | + real cost numbers (`cost_context.py`) | `Submitted`, verified | 68 | 1 — turn 66/68 | 0 | ✅ |
| 3 | + `task_workflow.md` ("ask at each stage"), `boundaries.md`, same-vendor fact | `Submitted`, verified | 56 | 4 — turns 25, 26, 41, 55 | 0 | ✅ |
| 4 | + rounded cost bucket, explicit trust, dropped planning-style sentence | `Submitted`, verified | 41 | 1 — turn 29 | 0 | ✅ |
| 5 | + explicit objective: *"minimize cost as much as possible"* | `Submitted`, verified | 29 | 2 — turns 18, 24 | 0 | ❌ |
| 6 | `role.md` rewritten (architect/team-of-engineers metaphor) + *"delegate tasks to minion as much as possible"* | `Submitted`, verified | 31 | — | **1** | ❌ |

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
  framing (run 6). Run 6 is the first of six to actually delegate.

## Run 6: delegation finally happened — mechanically clean, and cheap

Gru delegated the actual edit (`mode=agentic`, `returns=verdict`), with the exact code
already decided (down to `idx = len(self.data.header_rows)`) — the minion's job was
execution plus self-checking, not diagnosis. Cost: minion ~$0.001 (15,090 tokens, mostly
cache-hit), Gru $0.211 — the delegation itself cost roughly 0.5% of Gru's own spend, the
cost asymmetry the project's underlying hypothesis is actually about, realized for the
first time. The delegation's `verification.checks` were real, independently re-run
commands (not the minion's self-report) — the "verifiability trap" mechanism worked
exactly as designed at the mechanical level.

## But: runs 5 and 6 are the only two of six to fail real evaluation

Checked directly, not inferred — every patch's diff, `grep`ped for the fix's read-path
line:

```
run 1 (deepseek-v4):          has start_line fix: True   — resolved
run 2 (deepseek-v4-costctx):  has start_line fix: True   — resolved
run 3 (deepseek-v4-workflow): has start_line fix: True   — resolved
run 4 (deepseek-v4-trust):    has start_line fix: True   — resolved
run 5 (deepseek-v4-forced):   has start_line fix: False  — NOT resolved
run 6 (deepseek-v4-architect):has start_line fix: False  — NOT resolved
```

The bug fix needs two things: make `RST.write()` handle N header rows (visible directly
in the PR's literal example), and set `self.data.start_line` so reading a written table
back also accounts for N header rows (not in the PR's example — only surfaces from
tracing how `FixedWidth` reading actually works). Runs 1-4 all found and fixed both;
runs 5 and 6 found only the first.

**Whose fault, run 6**: the minion's, not at all. It received a fully-specified
instruction from Gru, executed it exactly, and Gru's own re-run checks (not the
minion's self-report) passed — because Gru's own checks, both at the delegation and at
`finish`, only ever tested writing, never reading a table back. The defect is entirely
upstream: Gru's diagnosis never identified the read-path requirement, before it ever
delegated anything.

**The actual pattern isn't "delegation caused the failure."** It's turn count / depth of
investigation before committing to a fix, and that correlates with *how hard the prompt
pushes toward finishing fast* — independent of whether that push is framed around cost
or around delegating:

- Run 5 failed under an explicit **cost-minimization objective** (*"minimize cost as
  much as possible"*) — 29 turns, no delegation at all.
- Run 6 failed under a **different, unrelated wording** — by run 6, `role.md` had been
  rewritten and the cost-minimization sentence was gone entirely, replaced by an
  architect/team metaphor and an explicit *"delegate tasks to minion as much as
  possible."* 31 turns, one delegation.

Two different instructions, neither present in the other's run, landing on the same
outcome: turn counts drop from 41-80 (runs 1-4, all correct) to 29-31 (runs 5-6, both
wrong), and the specific thing lost both times is the extra investigation depth this
bug needed. The common factor reads as "hurry up," not "cost" or "delegate" specifically
— both framings compress the same investigation phase, whichever one is asking for it.

## Caveat

n=1 instance, one model pair, one task shape (a small, self-contained bug fix requiring
non-obvious two-part reasoning). Six data points, one continuous progression under
changing conditions — not six independent trials, and not a general claim about what
makes models delegate or hurry. The correlation above (shorter run → missing read-path
fix) is clean at n=6 but hasn't been tested against a different task or a repeated run
under the same prompt, so "does hurrying always cost this specific kind of thoroughness"
stays open.

## Next

Two candidates, not yet tried:
1. **Re-run run 6's exact prompt on a fresh session** (or a different instance) to check
   whether the investigation-depth loss is a repeatable property of the "hurry up"
   framing, or this run's own variance.
2. **A task genuinely too large for one context** — forcing an actual need to split
   work, rather than an efficiency judgement call — to see whether delegation happens
   for a different reason than "the prompt pushed me to," and whether that version
   preserves investigation depth better than an explicit imperative does.
