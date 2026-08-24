# Experiment 3: rewritten delegation architecture, same model both roles

- **Status**: complete (arm B only — see Conclusion on arm A)
- **Date**: 2026-08-23
- **Hypothesis under test**: does the rewritten architecture ([review.md](../../review.md) `R5`/`R6`/`R13`/`R15`/`R16`/`R17`) recover [exp1](../exp1/LOG.md)'s solo-Qwen baseline of 4/5, and what does delegation cost once `mode="oneshot"` and one-action-per-turn are in place? Same model in both roles again, so this is **not** a test of the cost hypothesis — Phase 1 framework validation per [[project-machine-config]].

## Setup

- **Model**: `ollama_chat/qwen3.8:27b` for **both** Gru and minion — deliberate. Holding the model fixed makes this directly comparable to exp1 (solo) and exp2 (Gru/minion, old design) on the identical instances. Frontier-Gru is deferred; the runner still uses one `--model` for both roles and cannot split them.
- **Dataset**: `SWE-bench/SWE-bench_Lite`, split=`test`, same 5 instances as exp0/exp1/exp2: `astropy__astropy-{12907,14182,14365,14995,6938}`.
- **Arms**: **B only, first** (`gru.yaml`, no taxonomy — the change under test). **A** (`gru-taxonomy.yaml`, exp2's policy on the fixed harness) is the taxonomy control and costs a second full batch; run it only if B's result needs the harness-vs-policy separation explained — see [RUNBOOK.md](./RUNBOOK.md) step 3 for the decision table.
- **Infra**: two vast.ai instances, same pattern as exp1/exp2 (RTX 3090 serving Ollama; harness VM for nested Docker), plus a GPU-less VM for evaluation.
- **Harness**: `orchestrator/` as of `exp3_*` commits. New since exp2: one action per turn enforced in the parser, `think`, `run_check`, `mode` (`oneshot`/`agentic`), `returns` (`findings`/`verdict`) replacing the `type` taxonomy, per-delegation token cost fed back to Gru, coverage receipts on findings delegations, live cache capture, persisted delegation outputs.
- **Pinned**: `litellm==1.90.0`; `MSWEA_COST_TRACKING=ignore_errors` (both same reasons as exp1/exp2).

## Success criteria

Stated in advance, and deliberately **gates, not findings** — at n=5 none of this is a statistically meaningful comparison (`R4`).

1. **Primary gate: `astropy-14182` resolves again.** `14365` has failed identically in exp0, exp1 and exp2, so 5/5 is not realistically reachable; exp1's 4/5 was exactly everything-but-`14365`. "At least 4/5" therefore reduces to this one instance — the one both `cce461c`'s pre-finish rule and the coverage receipts target.
2. **The harness completes 5/5 sessions without `RepeatedFormatError`.** 2 of 3 exp2-rerun attempts died there (`R17`); `think` is the intended fix.
3. **Every trajectory pulled before any `vastai destroy`.** The trajectories *are* the data for the delegation analysis — exp2 lost 4 of 5 and it cannot be redone.

## Procedure

Full operational detail, including every known infra gotcha, is in [RUNBOOK.md](./RUNBOOK.md). Condensed:

```bash
# GPU instance:
ollama pull qwen3.8:27b

# harness VM, from the repo root, venv active:
export OLLAMA_API_BASE=http://<gpu-ip>:<mapped-port>
nohup scripts/run_arm.sh B ollama_chat/qwen3.8:27b "$OLLAMA_API_BASE" > run_B.log 2>&1 &

# locally, once it finishes — the gate must exit 0 before any vastai destroy:
scripts/pull_artifacts.sh root@<ip> <ssh-port> B
.venv/bin/python scripts/verify_artifacts.py experiments/exp3/results/B

# Docker-capable machine — evaluates exp3, re-verifies exp2, builds the table:
scripts/evaluate.sh B ollama_chat/qwen3.8:27b
```

exp2's `predictions_all5.json` is re-evaluated in the same pass: same five instances, so the image pulls are shared, both verdicts come from one harness version, and it closes [`R3`](../../review.md) (exp2's verdict is transcribed for 4 of 5 instances). **If it disagrees with the transcribed 3/5, that changes exp3's own baseline** — the gate below is defined against it.

## Results

Both criteria below are machine-generated: `experiments/exp3/reports/ollama_chat__qwen3.8:27b.exp3_B.json` (arm B) and `.exp2_reverify.json` (exp2's `predictions_all5.json` re-run on the same harness). Neither was hand-filled.

**Arm B: 3/5 resolved** — `astropy-12907` ✅, `astropy-14182` ❌, `astropy-14365` ✅, `astropy-14995` ✅, `astropy-6938` ❌.

**exp2 re-verify: 3/5 resolved**, exactly matching the previously-transcribed verdict (`astropy-12907`/`14995`/`6938` ✅, `14182`/`14365` ❌) — closes [`R3`](../../review.md): the 4 transcribed-not-machine-verified verdicts were correct.

| Instance | Resolved | Gru turns | think | run_check | Delegations | oneshot | Gru tok | Minion tok | Est. cache-hit% | Cov (files) | Cov (symbols) | First hit | Wall-clock |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| astropy-12907 | ✅ | 17 | 0 | 15 | 1 | 0 | 323,276 | 139,912 | 94.61 | 1/1 | 0.5 | t1 | 931s |
| astropy-14182 | ❌ | 31 | 0 | 19 | 1 | 0 | 690,906 | 467,573 | 96.35 | 0/1 | 0.0 | None | 931s |
| astropy-14365 | ✅ | 35 | 0 | 23 | 1 | 1 | 741,763 | 17,787 | 96.78 | 0/1 | 0.0 | None | 798s |
| astropy-14995 | ✅ | 28 | 0 | 17 | 1 | 1 | 651,306 | 11,331 | 96.65 | 1/1 | 1.0 | t1 | 680s |
| astropy-6938 | ❌ | 36 | 0 | 30 | 0 | 0 | 750,648 | 0 | 97.78 | 0/1 | 0.0 | None | 466s |
| **Total** | 3/5 | 147 | 0 | 104 | 4 | 2 | 3,157,899 | 636,603 | | | | | ~63m |

**Gate 1 (primary): `astropy-14182` resolves again — MISSED.** Same outcome as exp2.

**Gate 2 (`think` fixes `RepeatedFormatError`): MISSED.** `think` was called **zero times across all 147 Gru turns**, and **0 of 5 sessions reached a clean `finish()`** — 4 ended in `RepeatedFormatError` (prose instead of a tool call), 1 (`astropy-12907`) in an Ollama-side exception (below). Giving Gru an explicit "think" action did not stop it from writing free-text musing instead of calling any tool; every non-empty patch in this batch came from the git-diff fallback, not a clean submission.

**Gate 3: met.** All 5 trajectory sets pulled and `verify_artifacts.py`-checked before `vastai destroy` (see Issues on the one flagged item).

## Issues encountered

- **Real code bug, killed 100% of the first pass**: `run_exp2_single.py` did `sum(m["cost"] for m in gru_env.minion_records)`, but exp3's rewritten `minion_records` schema (oneshot delegations call `litellm.completion()` directly) never populates a `"cost"` key. Every instance crashed at final bookkeeping, *after* all real work was done — this pre-dates this run, was never exercised end-to-end before being called ready. Fixed by dropping the field (nothing downstream reads it; RUNBOOK already treats token totals, not cost, as the readable metric here).
- **Real code bug, second pass**: `run_exp2_single.py` had no `except` around `gru_agent.run()`. An uncaught exception (see next item) crashed the whole script and lost the session outright — no patch, no salvage — unlike the existing graceful `RepeatedFormatError` handling. Fixed by routing any uncaught exception through the same git-diff-on-the-shared-testbed fallback already used for non-`Submitted` exits (`gru_agent.messages`/`n_calls`/`cost` are updated incrementally through the loop, so they're still valid after a mid-session crash).
- **Real code bug**: `orchestrator/analyze_run.py` defined `main()` but had no `if __name__ == "__main__": main()` guard, so `python -m orchestrator.analyze_run` silently did nothing (no output, no `predictions_B.json`, exit 0) — `evaluate.sh` step 1 appeared to succeed and step 2 then failed on a missing file. Fixed by adding the guard. This script was apparently never actually invoked before this run.
- **Pre-existing, not new**: `litellm.APIConnectionError: Ollama_chatException - {"error":"no user query found in messages"}` hit `astropy-12907` (recovered via the new crash-safety fallback above) and separately killed 2 other in-progress instances outright before the fix landed. Already documented in `experiments/exp2-rerun/LOG.md` (`unfixed-attempt2`, deep in a long tool-calling session) as an Ollama/litellm-side quirk, not a bug in this project's code. Worth trying a newer Ollama version in a future experiment; the crash-safety fix above is the correct mitigation for now.
- `astropy-6938`'s empty patch was verified genuine, not lost data: Gru correctly diagnosed the bug via 30 read-only `run_check` turns but never delegated the actual fix to a minion, then hit `RepeatedFormatError` mid-investigation. The testbed container was already torn down by the time this was checked, so there was nothing further to pull — accepted as real data (`verify_artifacts.py` flags this by design; see RUNBOOK).
- Two provisioning gotchas not yet in RUNBOOK's index: `docker.io/vastai/kvm:latest` no longer exists (Docker Hub has no `latest` tag for that image) — use a dated tag like `ubuntu_cli_22.04-2025-11-21`. And the `ollama/ollama` image's default `ollama serve` entrypoint doesn't start under `--ssh` launch mode (vast.ai's ssh wrapper replaces it) — start it manually (`nohup ollama serve &`) after the instance comes up.

## Findings

- **`run_check` was used as an unrestricted bash tool, not for verification — the delegation architecture was barely exercised.** Its own tool description says *"This is for verifying, not for exploring the repository — delegate exploration"* (`gru_toolcall.py`), but `_run_check_action` executes any shell command with zero enforcement of that rule. Inspecting all 4 non-empty-patch trajectories: every single instance did exactly **1** delegation (0 for `astropy-6938`) — always an initial read-only "map/find" investigation — then Gru did **everything else itself** through `run_check`: `sed`/`cat`/`grep` exploration, writing reproduction scripts, editing source files directly (Python string-replace scripts, `sed -i`, `cat >>` heredocs adding whole test functions), and running pytest. 104 of 147 total Gru turns were `run_check`; only 4 were delegations. Since `run_check` is a harness-level tool available to both arms (not something `gru-taxonomy.yaml` changes), this isn't specific to policy B — arm A would very likely show the identical pattern. This is the primary reason coverage/`first_hit_delegation` numbers above should be read cautiously: they describe one investigation delegation per instance, not the delegation behavior the architecture is meant to produce. **Root cause, not just model non-compliance**: `gru.yaml`'s system prompt contradicts itself. The "before delegating" checklist (line 18) says *"Could a deterministic tool do this exactly? If the answer is a plain shell command — a formatter, a linter, **an exact search** — then it is a check, not a delegation. Use `run_check`."* The action list and the tool's own description (line 29 / `gru_toolcall.py`) say the opposite: *"It is not for exploring the repository; exploration is delegated work."* `grep`/`sed` exploration genuinely is "a plain shell command" doing "an exact search," so the first rule explicitly licenses what the second forbids — and the same "deterministic tool doing this exactly" wording covers a `sed -i`/Python-replace edit just as well once Gru has already decided the exact old/new string, which is why editing fell to `run_check` too. Compounding this: only delegations get an explicit `[t1 cost: N tokens...]` feedback line (`gru_environment.py`'s `_delegate`) — `run_check`/`think` show no cost at all — so alongside the prompt's own *"a delegation that costs more than the work it saved you is a bad trade"* framing, self-directed `run_check` reads as the free option. The one delegation each instance did make fits the "What to delegate" examples exactly (a broad, judgement-light "find every place X is used" search); everything narrower fell to the `run_check` carve-out.

  **Fixed 2026-08-23** (before any further batch was run): the prompt contradiction is resolved (`gru.yaml`/`prompts/gru-loop.md` — dropped the "exact search... use `run_check`" carve-out), `run_check` now rejects commands that look like a repository write (`orchestrator/gru_environment.py`'s `_looks_like_repo_write` — validated against this run's own 106 real check commands: all 7 genuine edits caught, 0 false positives on the other 99), and `run_check`/`think` now surface a per-turn token-cost line so delegation isn't the only visibly-priced action (`_turn_cost_line`, wired from `run_exp2_single.py`). Read-only exploration via `run_check` (`grep`/`sed`/`cat`) is deliberately left unenforced — see next steps below. Not yet re-run against live infra to confirm the fix changes behavior.
- **`astropy-14365` resolved for the first time across four experiments.** It failed identically in exp0 (Haiku), exp1 (solo Qwen), and exp2 (Gru/minion) — LOG.md for those runs treats it as a near-certain miss. This run's patch (2,525 chars, via git-diff fallback after a `RepeatedFormatError`, not a clean finish) resolved it. Worth a patch-level look at what changed before reading too much into it, given the abnormal termination.
- **`think` being available did not stop prose-without-tool-call.** It was added specifically to give Gru a way to "reason out loud" via a real tool call instead of drifting into free text; it was never used once. The failure mode it targeted (a passing check followed by unstructured musing, compounding into `RepeatedFormatError`) still dominates — 4 of 5 sessions ended there. This suggests the fix needs to be a harder constraint (e.g. penalize/retry differently) rather than an optional escape hatch, or that Qwen3.8:27b specifically doesn't reach for tools when it's "confident."
- **Every non-empty patch this run came from the fallback, not a clean submission** — the delegation-outputs-and-coverage machinery (built for measuring *how* Gru delegates) never got to observe a normal-terminating session in this batch, so `first_hit_delegation`/coverage numbers above should be read as "what happened before the session went abnormal," not as characterizing a completed run.
- exp2's transcribed verdict now being machine-confirmed (Results) means the exp1→exp2 comparison in `exp2/LOG.md` no longer carries the "unverified" caveat.

## Conclusion & next steps

Both primary gates missed: `astropy-14182` did not resolve, and the harness did not complete sessions cleanly (0/5, not 5/5). Per [RUNBOOK.md](./RUNBOOK.md) step 3's decision table, **arm A (the taxonomy control) is not worth running yet** — it tests policy vs. this run's fixed harness, and won't explain *why* B missed, and the `run_check`-as-bash-tool gap it would inherit unchanged makes any A-vs-B delegation comparison uninformative regardless.

Two things needed fixing before any further batch, in priority order:
1. **`run_check` needed actual enforcement**, not just a description asking Gru to delegate exploration — this run shows the model won't self-police it, and it's the reason exp3's own hypothesis (what delegation costs once oneshot mode is in place) wasn't really testable from this data: there was almost no delegation to measure. **Done** — see Findings above.
2. **The `think`/`RepeatedFormatError` prose-instead-of-tool-call pattern** — real, but secondary to (1); fixing `run_check` first may also reduce how often Gru drifts into narration, since it currently has no delegation cadence forcing a decision point. **Addressed 2026-08-23** (still unvalidated against live infra), after the diagnostic re-run below confirmed (1)'s fix works but this pattern is a genuinely separate problem — see next section.

**Next**: a small diagnostic re-run (not necessarily a full 5-instance batch) to confirm (1) actually restores delegation and doesn't just shift `run_check` usage to commands that dodge the heuristic, before committing to a full arm B rerun or arm A.

### `RepeatedFormatError` fix (2026-08-23)

Considered and ruled out API-level enforcement first: `tool_choice: "required"` via `model_kwargs`, which would make a tool call structurally mandatory rather than requested. Checked directly against the installed `litellm==1.90.0` source rather than assuming it works — `litellm/llms/ollama/chat/transformation.py`'s `map_openai_params` lists `tool_choice` in `get_supported_openai_params` but then unconditionally discards it (`non_default_params.pop("tool_choice", None)  # causes ollama requests to hang`) before ever building the Ollama request. Same dead end as `parallel_tool_calls` in exp2, this time confirmed in the library source rather than inferred from behavior: `ollama_chat` never sees `tool_choice` regardless of what's passed. Not worth another live-infra cycle to rediscover this.

Landed a harness-level fix instead, on the diagnosis that a static, repeated correction message doesn't work on this model — `think` was added as a legal way to reason-in-text-via-a-tool-call and was used 0/147 times in arm B, so the problem isn't the absence of an escape hatch. `GruModel` (`orchestrator/gru_model.py`) now tracks its own consecutive-FormatError count across the session (reset on any clean parse) and passes it into `parse_gru_actions` (`orchestrator/gru_toolcall.py`), which escalates the correction text itself as failures pile up: 2nd consecutive failure gets a one-line flag, 3rd+ gets an explicit warning that continuing discards all work with no partial credit, plus a blunter instruction to call `finish` directly instead of narrating that the task is done. Applies to all three `FormatError` sites in `parse_gru_actions` (no tool call, multiple tool calls, malformed/invalid tool call), not just the no-tool-call case that dominated this run.

Not yet re-run against live infra — same status as the `run_check` fix before its diagnostic re-run.

### Diagnostic re-run (2026-08-23, single instance, `astropy-14182`, fixes in place)

Not part of arm B's data — a single-instance check of whether the `run_check` fix actually changes behavior before committing to a full rerun. Fresh instances, fixed code, same instance as the primary gate.

**Result: delegation is restored.** Gru delegated the actual fix (`t2`, `mode=agentic`, `returns=verdict`, description *"Add header_rows support to the RST table writer... Make exactly these two edits..."*) instead of self-editing through `run_check` — the exact behavior the fix targeted. `t2` completed with a clean `Submitted` and produced essentially the same RST fix as the original run's self-written edit, but genuinely delegated this time. Delegation:`run_check` ratio went from 1:19 to 2:5 (small n, but a real qualitative shift, not noise) — 6 of 8 valid actions carried a `[this turn cost: N tokens]` line (turn-cost surfacing confirmed working), and `think` was used once (vs. zero times across all 147 turns in the full batch). Zero write-rejections fired — Gru delegated the edit outright rather than attempting it and getting bounced, which is the better outcome.

**Still hit `RepeatedFormatError`** (6 consecutive no-tool-call turns, right after the second delegation, during repro/verification) — confirming fix (2) is a genuinely separate problem, not something fix (1) incidentally resolves. Patch recovered via the existing fallback (1194 chars, similar to the original run's).

**Read as**: fix (1) worked as intended on this one instance. Not proof it holds at n=5, but the qualitative story (minion did the edit, not Gru) rather than just count-shuffling; worth a full arm B rerun once (2) is also addressed, rather than spending a second full batch on (1) alone.

## Artifacts

Under `experiments/exp3/`: `results/<arm>/<instance>/` (`prediction.json`, `cost_summary.json` incl. per-role `cache`, `delegations/*.txt`, `minions/*.traj.json`), `gru.traj.json` per run, plus the machine-generated evaluation report.
