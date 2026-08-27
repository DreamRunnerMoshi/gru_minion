# Experiment 6 — porting the Gru/minion architecture to GAIA

exp5 established the core finding on SWE-bench: the Gru/minion architecture shifts the
substantial majority of tokens and dollars to the cheap minion without a visible cost to
accuracy, across four model pairs. The open question this experiment starts on: does
that hold outside code-editing tasks? GAIA (huggingface.co/datasets/gaia-benchmark/GAIA)
is a genuinely different task shape — multi-hop web research and light computation,
scored by exact-match against a hidden gold answer, no repository, no test suite.

**The point of this experiment, stated explicitly by the user and initially gotten
wrong (see "Correction" below): one architecture, one prompt — only the benchmark
underneath changes.** Gru's actual instructions (`orchestrator/prompts/gru/*.md`) and
tool schema (`orchestrator/gru_toolcall.py`) must be byte-identical to the SWE-bench
setup. Only the environment executing `run_check`/`delegate_to_minion`/`finish` differs.

## Scope (user-confirmed)

- **Dataset**: standard GAIA validation set (165 instances), filtered to Level 2/3 (the
  harder, more multi-step tiers — the closest proxy this release has for "long horizon",
  since there's no separate split for it) and no attached file (this pilot's toolset
  can't parse files/images/audio). 5 instances picked deterministically
  (`orchestrator/gaia_dataset.py::pick_pilot`, seed=0).
- **Toolset**: minimal — a network-enabled sandbox (unlike SWE-bench's, which gets none)
  with Python and a `websearch.py` helper (wraps Tavily) on PATH. No file/image/audio
  parsing.
- **Pair**: `z-ai/glm-4.6` (Gru) / `z-ai/glm-4.5-air` (minion) — chosen as the pilot
  default since it showed the cleanest, most balanced delegation behavior in exp5.

## Correction (2026-08-25/26): the first build used a divergent prompt

The first version of this harness (`orchestrator/gaia_tools.py`/`gaia_model.py`,
`orchestrator/prompts/gaia/*.md`) introduced a **new** tool schema
(`web_search`/`python_exec` instead of `run_check`, `finish` taking an `answer` field
that doesn't exist in the shared schema) and **rewrote** the shared prompt fragments —
new "Recommended Workflow" steps, new delegation guidance, new wording throughout —
instead of reusing `orchestrator/prompts/gru/*.md` unchanged. User caught this directly:
*"why did you change the prompt from GAIA... we will use same prompt as swe_bench."*
That's not a stylistic nitpick — it's the actual independent variable this experiment
is supposed to hold constant. A 23-instance batch (5 pilot + 18 Level 3, 12/23
resolved, 52%) was run under the divergent prompt before this was caught; **those
results are confounded (different prompt, not just different benchmark) and have been
deleted, not archived** — they don't answer the question this experiment asks.

Fixed by deleting `orchestrator/prompts/gaia/`, `gaia_tools.py`, `gaia_model.py`,
`gaia_config.py` entirely and rebuilding `gaia_environment.py`/`run_gaia_session.py` to
reuse `orchestrator/gru_toolcall.py`, `orchestrator/gru_model.py::GruModel`, and
`orchestrator/gru_config.py::load_gru_config` **unchanged** — the exact same imports
`run_gru_session.py` uses. `orchestrator/config/gaia.yaml` composes the identical
`system_template_fragments: [role, task_approach, actions, delegation, verification]`
list as `gru.yaml`; only `instance_template` differs, and only where it mechanically
has to (a `<question>` tag instead of `<pr_description>`/`<repository_context>` — GAIA
has no PR or repo).

**The one genuine design problem this surfaced**: `finish()`'s shared schema is
`summary` + `final_verification.checks` (shell commands, exit 0 = pass) — there is no
`answer` field, because SWE-bench never needed one (the real patch comes from `git diff`,
independent of anything Gru writes in `summary`). GAIA has no filesystem state to diff,
so it needs an equivalent independent extraction point. Resolved by having GAIA's
`instance_template` (legitimately per-benchmark, unlike the shared fragments) instruct
Gru to make its **last** `final_verification` check literally print the final answer
(e.g. `echo '<answer>'`) — `gaia_environment.py::_finish()` takes that check's own
captured stdout as the scored answer, never trusting `summary`. Confirmed live
(`experiments/exp6/results/smoke-test/17b5a6a3`): Gru wrote
`"checks": ["echo '34423, 34428, 34429'"]`, and that string was extracted exactly.

`run_check` is what reaches the sandbox now, not a dedicated tool — the same way
SWE-bench's `run_check` reaches `git`/`sed`/whatever else lives in that testbed. Gru
runs `websearch.py "<query>"` or `python3 -c "<code>"` as plain shell commands; no new
tool-calling schema needed, matching how the minion's own agentic loop already worked
(mini-swe-agent's stock bash-tool, unmodified, verified against the installed library
source — `DockerEnvironment._check_finished`'s `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
marker convention, same as always).

Control flow re-tested against a scripted model after the fix
(`tests/gaia_harness.py`, `tests/test_gaia_harness.py`) — 6 tests, zero docker/network
dependency, all passing: `think`→`finish` (answer extraction from the last check),
`run_check` reaching real shell commands and the fake `websearch.py`,
`delegate_to_minion` in both agentic/findings and verdict modes (confirming the
independent-check verifiability-trap behavior still holds), and a rejected-`finish`
path. All 25 project tests (19 SWE-bench + 6 GAIA) still pass together.

`orchestrator/gaia_scorer.py` (GAIA's quasi-exact-match answer scoring) and
`orchestrator/gaia_dataset.py` (dataset loading/filtering) are unaffected by this
correction — they're harness-internal, not prompt content.

## Results: the corrected batch (glm-paired, same 23 instances)

22 of 23 completed (`ad37a656`, a pilot instance, hung mid-session — same
reproducible glm-paired hang pattern documented in exp5 — killed after ~15 minutes
of zero log progress; no cost_limit/step_limit caught it in time because the hang
sat inside a single call, not a runaway loop, so there was nothing to trip against
until it was killed manually).

**3/22 resolved (14%) — a sharp drop from the divergent-prompt run's 12/23 (52%).**
Checked directly that this isn't a scoring or extraction bug: the mechanism is
sound (`0bdb7c40`: extracted `White;5875` against gold `White; 5876` — a genuine
near-miss, not a parsing failure). Delegation itself increased under the corrected,
shared prompt — 11/22 instances delegated at all (vs. 6/23 before), and minion
token share rose to **69.7%** (2.31M Gru tokens vs. 5.30M minion tokens, vs. 56.6%
before) — both numbers moving in the direction you'd expect once `delegation.md`'s
real, unedited "delegate whenever mechanical and checkable" guidance is actually in
effect instead of a rewritten version of it.

**The real, reportable finding: a large share of the wrong answers are Gru
explicitly giving up, not guessing wrong.** 6 of 22 final answers are refusals —
`"Unable to complete task: Tools designed for code deb..."`,
`"UNABLE_TO_COMPLETE_TASK - No access to YouTube or..."`,
`"Cannot fulfill academic research request with avai..."`,
`"Data not found in repository"`,
`"TASK_INCOMPLETE: Requires web/database access capabi..."` — and at least one more
(`676e5e31`) dumped a whole `=== Definitive Analysis ===` block into the final
check instead of a single clean answer line, violating the one-line-answer
instruction outright. The remaining wrong answers are genuine misses (`72c06643`:
`230` vs. gold `55`; `56db2318`: `2, 8` vs. gold `7, 9`; `e961a717`: `6` vs. gold
`12`; `de9887f5`: `0` vs. gold `22`).

**Why this is a genuine prompt/task-shape interaction, not (only) a capability
gap**: the shared prompt fragments were written for SWE-bench, where "the tests
still fail" is a normal, non-catastrophic thing to submit — `task_approach.md` and
`verification.md` never tell Gru it must commit to a best-effort answer rather than
report failure, because on SWE-bench that instinct is fine. GAIA's scoring has no
such tolerance: a refusal string scores identically to a confident wrong guess —
both are just "not the gold answer." The one instance-template line asking for a
clean final-line answer (necessary plumbing, not shared prompt content — see
Correction above) doesn't address this at all; it's a formatting instruction, not
a "you must attempt an answer" one. Whether to add that instruction anywhere is a
real design question this data surfaces, not yet decided — it would need to live in
the instance_template (benchmark-specific) to keep the shared fragments untouched.

## What's still open

n=22 is a small sample for a resolve-rate claim, but large enough to say the
give-up pattern is real (6+ of 19 wrong answers, not 1-2). Not yet decided: whether
addressing it belongs in this experiment's scope at all (it would mean touching the
instance_template again, which is legitimate per-benchmark plumbing but worth a
deliberate decision, not a reflexive fix) or whether it's simply the honest first
data point on "the SWE-bench-native prompt, unmodified, doesn't transfer cleanly to
a benchmark with zero tolerance for reported failure." Also open: the minion
token-share finding (69.7%) is the strongest version of exp5's core result seen
yet, on a completely different task shape — worth another pair to see if it's
GLM-specific or general once the give-up-rate question is settled.

## Second pair: gemini-3.7-flash / deepseek-v3.2, and the give-up question resolved

Second question this batch answers: was the low glm-paired resolve rate (14%) about
GAIA being genuinely hard for GLM specifically, or the shared prompt itself? Ran the
identical 23 instances, identical harness, only the model pair changed — Gru:
`google/gemini-3.7-flash` ($0.375/$1.875 per M, a reasoning model — confirmed live
its `reasoning_content` counts against completion tokens and gets billed), minion:
`deepseek/deepseek-v3.2` ($0.26/$0.38 per M). Both verified live for real
tool-calling before the batch (`litellm.completion` with `build_tools()`, confirmed
`finish_reason: tool_calls`) — Gemini's `:batch` suffix variant was confirmed
earlier (exp5) to be batch-API-only and incompatible with this harness; the
non-batch `gemini-3.7-flash` used here is not that.

**12/23 resolved (52%)** — a dramatic swing from glm-paired's 14%, and it settles
the open question directly: **zero give-up/refusal answers this run** (vs. GLM's 6
of 22), so the low GLM number was substantially GLM's own behavior interacting
with the shared prompt, not a property of the prompt or the harness that would
sink any model on GAIA. $1.437 total Gru cost, ~$1.73 drawn from the real
OpenRouter balance across the whole batch.

| Instance | Resolved | Gru calls | Delegations | Gru tok | Minion tok | Minion share | Gru $ | Wall |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 00d579ea | ❌ | 4 | 1 | 12,136 | 327,975 | 96.4% | $0.0055 | 231s |
| 0512426f | ❌ | 60 | 0 | 1,059,319 | 0 | 0.0% | $0.1760 | 465s |
| 0bdb7c40 | ❌ | 34 | 0 | 384,040 | 0 | 0.0% | $0.0724 | 270s |
| 384d0dd8 | ❌ | 60 | 0 | 1,064,160 | 0 | 0.0% | $0.1592 | 482s |
| 50f58759 | ✅ | 19 | 1 | 211,260 | 99,405 | 32.0% | $0.0445 | 634s |
| 56db2318 | ✅ | 3 | 0 | 14,426 | 0 | 0.0% | $0.0098 | 21s |
| 5f982798 | ❌ | 60 | 0 | 908,141 | 0 | 0.0% | $0.1502 | 411s |
| 676e5e31 | ❌ | 45 | 1 | 836,727 | 613,637 | 42.3% | $0.1269 | 818s |
| 72c06643 | ❌ | 10 | 0 | 43,284 | 0 | 0.0% | $0.0182 | 54s |
| 8131e2c0 | ❌ | 60 | 0 | 879,695 | 0 | 0.0% | $0.1422 | 307s |
| 851e570a | ✅ | 3 | 0 | 10,124 | 0 | 0.0% | $0.0058 | 19s |
| 983bba7c | ✅ | 16 | 1 | 159,176 | 352,451 | 68.9% | $0.0435 | 491s |
| 9e1fc53b | ❌ | 19 | 0 | 93,837 | 0 | 0.0% | $0.0344 | 84s |
| ad2b4d70 | ✅ | 4 | 1 | 10,968 | 266,653 | 96.0% | $0.0050 | 231s |
| c3a79cfe | ✅ | 7 | 0 | 26,929 | 0 | 0.0% | $0.0139 | 35s |
| de9887f5 | ✅ | 4 | 1 | 12,043 | 183,764 | 93.8% | $0.0059 | 243s |
| e961a717 | ✅ | 13 | 0 | 64,447 | 0 | 0.0% | $0.0273 | 70s |
| ebbc1f13 | ❌ | 60 | 0 | 729,575 | 0 | 0.0% | $0.1346 | 410s |
| 08f3a05f | ✅ | 3 | 0 | 9,107 | 0 | 0.0% | $0.0053 | 15s |
| 17b5a6a3 | ✅ | 18 | 0 | 100,572 | 0 | 0.0% | $0.0346 | 82s |
| 872bfbb1 | ❌ | 56 | 1 | 741,255 | 275,417 | 27.1% | $0.1340 | 547s |
| ad37a656 | ✅ | 4 | 1 | 10,805 | 101,619 | 90.4% | $0.0050 | 134s |
| f46b4380 | ✅ | 33 | 0 | 415,622 | 0 | 0.0% | $0.0827 | 147s |

### Cache hit stats (real, provider-reported — not this project's own estimate)

Pulled directly from OpenRouter's own per-call `usage.cached_tokens`/
`prompt_tokens_details.cached_tokens` fields, not the heuristic
`estimated_cache_hit_pct` this project computes locally (`orchestrator/cache_stats.py`)
— worth separating the two, since the heuristic runs noticeably hot against reality
here.

| Role | Prompt tokens | Real reported cache hits | Real % | This project's own estimate |
|---|---:|---:|---:|---:|
| Gru (gemini-3.7-flash) | 8,731,196 | 5,725,461 | **65.6%** | 97.0% |
| Minion (deepseek-v3.2), 210 calls | 3,015,593 | 2,034,368 | **67.5%** | — |

Both roles land in the same real 65-68% range once a session runs long enough —
but short sessions get zero benefit: every instance with only 3-4 Gru turns
(`00d579ea`, `56db2318`, `851e570a`, `ad2b4d70`, `c3a79cfe`, `de9887f5`,
`08f3a05f`, `ad37a656`) shows **0% real cache hits**, too few calls for the cache
to warm up before the session ends, while the longer, delegation-heavy instances
(`384d0dd8`, `0512426f`, `5f982798`, `676e5e31`, `8131e2c0`, `ebbc1f13`,
`872bfbb1`) hit 59-72%. The local estimate doesn't track this split at all —
it reports 66-88%+ even on the 0%-real short sessions, which is the same
overshoot pattern the estimate has shown before in this project's earlier
experiments, now confirmed on a third, unrelated model pair.

**A different, more expensive failure mode replaces the give-up pattern: grinding
to the step limit.** 5 of 11 failures are `exit_status=LimitsExceeded` — Gemini
used its entire 60-turn budget without ever calling `finish()` (`0512426f`,
`384d0dd8`, `5f982798`, `8131e2c0`, `ebbc1f13`), each burning 700K-1.06M Gru tokens
in the process (vs. a typical resolved instance's 10K-200K). **Every one of these
5 has zero delegations** — when Gemini gets stuck on a hard question, it does 100%
of the investigation itself rather than farming any of it out, the opposite of the
resolved instances, most of which delegated at least once. Minion token share for
the whole batch is **22.2%** (7.80M Gru tokens vs. 2.22M minion tokens) — far below
glm-paired's 69.7%, because Gemini simply delegates far less often (8/23 vs.
11/22) and, when stuck, not at all.

**So the two pairs fail in opposite, informative ways.** GLM: delegates heavily,
fails cheaply and fast by explicitly refusing. Gemini: delegates rarely, fails
expensively and slowly by grinding alone to the turn limit. Both point at the same
underlying gap in the shared prompt (written for SWE-bench, where a bounded amount
of investigation before either succeeding or reporting failure is the norm) — GAIA
apparently needs either an explicit "you must commit to an answer" instruction
(would help GLM) or a cheaper way to recognize "this line of investigation isn't
converging, try delegating a different angle instead of grinding" (would help
Gemini) — neither of which exists in the current shared prompt, deliberately, since
adding either would be exactly the kind of prompt change this experiment is
supposed to hold constant.

### Root cause of the grinding, and a sandbox-level (not prompt-level) fix

Traced one `LimitsExceeded` trajectory (`0512426f`) turn by turn: Gemini never
uses `websearch.py` at all across 60 turns. Instead it writes fresh raw
`urllib.request` scraping code against DuckDuckGo, then Google, then Wikipedia,
then YouTube transcripts, then GitHub, then the Wayback Machine — a new hand-rolled
scraper per turn, each a dead end (blocked, wrong format, or genuinely no search
capability), never once checking what tools the sandbox actually provides.

Checked GLM's equivalent trajectories for contrast: GLM's own Gru also never uses
`websearch.py` directly (zero uses across all 22 glm-paired instances) — but GLM
delegates the actual searching to its minion, and **the minion** consistently
discovers and uses `websearch.py` heavily (5-13 calls per delegation). Traced the
discovery moment directly (`872bfbb1`'s `t1` minion): after two failed raw
`curl`/`wget` attempts, it runs `find /usr/local/bin -name "*web*" -o -name
"*search*" ...` — a deliberate "what do I actually have" step — finds the tool at
turn 24, and uses it from then on. Gemini never takes that step, in either role.

This is genuinely a tooling-discoverability problem, not a prompt problem — the
tool was equally available to both, just never checked for. Fixed at the sandbox
level, not the prompt: added `orchestrator/gaia_sandbox/TOOLS.md`, copied into
`/workspace` (the container's cwd) at image build time, so a routine `ls` surfaces
it for free — no system prompt or instance_template change, same fix applies
regardless of what model or prompt is pointed at this sandbox later.

**Verified live**: reran the two most expensive `LimitsExceeded` instances
(`0512426f`, `384d0dd8`) under the rebuilt image. `0512426f`: **fixed completely**
— `LimitsExceeded` → `Submitted, resolved=True`, 0 delegations → 2, cost dropped
from $0.176 to $0.0194 (9x cheaper). `384d0dd8`: **partially fixed** — still
`LimitsExceeded`, but now with 1 delegation (confirmed via trajectory: it *did*
discover and use `websearch.py` once, early on) followed by 59 `run_check` turns
doing the rest itself. So the fix reliably solves "does the model know the tool
exists" — it doesn't change Gemini's underlying tendency to delegate once and then
revert to self-directed work rather than defaulting to delegating repeatedly,
which is a separate, deeper behavioral trait (consistent with the batch-wide
22.2% vs. 69.7% minion-token-share gap between the two pairs).
