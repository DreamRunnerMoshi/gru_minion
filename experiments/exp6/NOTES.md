# Experiment 6 — porting the Gru/minion architecture to GAIA

exp5 established the core finding on SWE-bench: the Gru/minion architecture shifts the
substantial majority of tokens and dollars to the cheap minion without a visible cost to
accuracy, across four model pairs. The open question this experiment starts on: does
that hold outside code-editing tasks? GAIA (huggingface.co/datasets/gaia-benchmark/GAIA)
is a genuinely different task shape — multi-hop web research and light computation,
scored by exact-match against a hidden gold answer, no repository, no test suite.

## Scope (user-confirmed)

- **Dataset**: standard GAIA validation set (165 instances), filtered to Level 2/3 (the
  harder, more multi-step tiers — the closest proxy this release has for "long horizon",
  since there's no separate split for it) and no attached file (this pilot's toolset
  can't parse files/images/audio). 5 instances picked deterministically
  (`orchestrator/gaia_dataset.py::pick_pilot`, seed=0).
- **Toolset**: minimal — `web_search` (Tavily) + `python_exec` (sandboxed Python), no
  browsing/file/image/audio parsing.
- **Pair**: `z-ai/glm-4.6` (Gru) / `z-ai/glm-4.5-air` (minion) — chosen as the pilot
  default since it showed the cleanest, most balanced delegation behavior in exp5.
- **Batch size**: 5 instances, 1 pair, to validate the harness end-to-end before
  committing to a bigger/more expensive run.

## Building the harness

Full details in the exp6.1 commit message and `GRU_MINION_COMMUNICATION.md`-style
inline docs across the new files. Summary: `orchestrator/gaia_tools.py`/`gaia_model.py`
are a new tool schema for Gru's own loop (`delegate_to_minion`/`think` reused verbatim
from the SWE-bench side, `run_check` replaced with `web_search`/`python_exec`, `finish`
now submits an `answer`+`reasoning` string instead of a git diff). The minion's own
agentic-mode loop needed zero new code — mini-swe-agent's stock bash-tool loop already
handles it, verified directly against the installed library source
(`DockerEnvironment._check_finished`'s `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` marker
convention). Only the sandbox differs: `orchestrator/gaia_sandbox/` is a network-enabled
image (SWE-bench containers get none) with a `websearch.py` helper wrapping Tavily on
PATH, no git repo. `orchestrator/gaia_scorer.py` reimplements GAIA's quasi-exact-match
scoring (number/list/string normalization) from the documented shape of the official
scorer — not verified byte-identical, flagged as such in its own docstring.

Control flow tested against a scripted model before any live run
(`tests/gaia_harness.py`, `tests/test_gaia_harness.py`) — 6 tests, zero docker/network
dependency, covering think/python_exec/web_search/delegate_to_minion (both
agentic/findings and verdict modes, confirming the independent-check
verifiability-trap behavior carries over)/finish validation. All passed before any
money was spent.

## Infrastructure: getting a live host up

Took three attempts and roughly 45 minutes, longer than any prior experiment's
provisioning. First instance (Quebec host): never became SSH-reachable despite
clean boot logs (docker started, cloud-init finished, key correctly authorized) —
destroyed after ~7 minutes. Second (same offer, immediate retry): the VM crashed
during creation (`libvirt: QEMU Driver error`) before ever reaching `running`.
Third (UK host): reached `running` with clean boot logs but stayed SSH-unreachable
for 40+ minutes — the user found vast.ai's own UI note that VM-style images
(`vms_enabled=true`, needed for this project's confirmed-working image) can take
30+ minutes to fully register, which these first three attempts simply hadn't been
given. A fourth instance (Hong Kong, smaller spec — 16GB RAM, since this pilot needs
none of the SWE-bench testbed's resources) was launched in parallel as a race rather
than waiting further, and became reachable via its **direct** IP:port (not the
`ssh_host`/`ssh_port` proxy fields `vastai show instance` reports — those stayed
refused for this instance too; `vastai ssh-url` gave the working direct address).
The UK instance was destroyed once the HK one was confirmed working.

Also hit: `mini-swe-agent`'s dependency chain (`litellm`, unpinned) pulled a version
whose Anthropic-specific submodule uses `typing.NotRequired`, a Python 3.11+ stdlib
feature — broke on this image's Python 3.10. Fixed by pinning `litellm==1.79.0`
rather than upgrading Python (attempted via `apt`, but that hung on a slow/blocked
mirror and was abandoned in favor of the faster fix).

## Results: the first live pilot

| Task | Resolved | Answer | Gold | Gru cost | Delegations | Wall-clock |
|---|---|---|---|---:|---:|---:|
| 08f3a05f (Newton's method) | ✅ | `2` | `2` | $0.0093 | 0 | 57s |
| 17b5a6a3 (invasive fish zip codes) | ✅ | `34689` | `34689` | $0.0179 | 0 | 105s |
| 872bfbb1 (painting fruits) | ❌ | — (empty) | `pears, bananas` | $0.0277 | 0 | 115s |
| ad37a656 (Bikini Atoll bomb) | ✅ | `Bravo` | `Bravo` | $0.0094 | 0 | 61s |
| f46b4380 (Fiona Apple / Paul Thomas Anderson bet) | ✅ | `Harbinger, Tidal` | `Harbinger, Tidal` | $0.0200 | 2 | 246s |

**4/5 resolved, total cost $0.084 for all five.** The one failure isn't a wrong
answer — it's a harness-level crash. Checked directly
(`experiments/exp6/results/glm-paired/872bfbb1/gru.traj.json`): after 4 real,
substantive `web_search` calls that were finding the right source, Gru attempted
`delegate_to_minion` with `inputs` missing the required `scope` field. The error
message named the exact problem ("delegate_to_minion.inputs missing required
'scope'"), escalated over 6 consecutive turns exactly as designed
(`gaia_tools.py::_escalation_prefix`), and GLM never corrected it — the session hit
`RepeatedFormatError` with real investigation work already done but no submission.
This is a concrete, reproducible model-behavior finding, not a scoring artifact.

**Delegation was rare in this pilot — only 1 of 5 resolved instances used it at
all**, and that one instance (`f46b4380`) was also the slowest (246s) and most
expensive (`$0.02`) of the four resolved runs. On this small a sample it's not
possible to say whether that's a real pattern (GAIA's mostly-search-then-synthesize
shape may just not decompose into many delegable sub-pieces the way a multi-file
code fix does) or noise — worth checking once a bigger batch runs.

## What's still open

n=5 is nowhere near enough to say anything about resolve rate, delegation rate, or
cost-shift patterns with confidence — this pilot's job was proving the harness works
live end-to-end, which it did. Natural next steps, not yet done: a bigger batch (more
instances, ideally the full no-file Level 2/3 pool — 85 instances — or a meaningful
subset of it); more pairs, mirroring exp5's cross-vendor design, once the pilot's
cost/behavior profile is better understood; fixing the `delegate_to_minion` missing-
`scope` failure mode, either via a stricter tool schema (mark `inputs` fields required
at the JSON-schema level, not just in prose) or a repair step that fills in a sane
default rather than looping the same correction; and, if this line of work continues,
extending the toolset past search+compute to actually match GAIA's full task shape
(many real GAIA instances need file/image/audio parsing, filtered out entirely here).
