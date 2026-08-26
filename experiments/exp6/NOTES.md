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

## What's still open

The corrected harness is live-verified (one smoke-test instance,
`experiments/exp6/results/smoke-test/17b5a6a3`) but the full batch has not been
rerun under it yet — the 12/23 number from the divergent-prompt run is not a valid
substitute and should not be cited. Next step: rerun the pilot + Level 3 batch (same
23 instances as before, same glm-paired pair) under the corrected, shared-prompt
harness to get real numbers for this experiment's actual question — does the
minion-token-share finding, and the "delegation doesn't cost accuracy" finding, from
exp5 carry over to GAIA's task shape, now that the only thing that changed between
this run and exp5's is the benchmark, not the prompt.
