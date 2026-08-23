# Experiment 2: Gru/minion architecture, same model both roles

- **Status**: complete
- **Date**: 2026-08-21/22
- **Hypothesis under test**: first real run of the Gru/minion architecture ([prompts/gru-loop.md](../../prompts/gru-loop.md), [PLAN_FORMAT.md](../../PLAN_FORMAT.md)) — does the escalate-on-failure loop (delegate → independent verification → inline retry → whole-task `final_verification`) actually run end-to-end, and does the architecture itself preserve resolve rate against [exp1](../exp1/LOG.md)'s solo-minion baseline when the model is held fixed? Phase 1 framework validation per [[project-machine-config]] — same model in both roles, so this is *not* a test of the cost hypothesis (no cost asymmetry between roles to measure yet).

## Setup

- **Model**: `ollama_chat/qwen3.8:27b` for **both** Gru and minion roles — deliberate, per [[project-machine-config]]'s Phase 1 plan: using the same model isolates the architecture's own effect from model-capability differences, directly comparable to exp1's solo-Qwen run on the identical instances.
- **Dataset**: `SWE-bench/SWE-bench_Lite`, split=`test`, same 5 instances as exp0/exp1: `astropy__astropy-{12907,14182,14365,14995,6938}`.
- **Infra**: two vast.ai instances per run (GPU RTX 3090 serving Ollama, ~$0.10-0.13/hr; harness VM for nested Docker, ~$0.04-0.05/hr), same pattern as exp1 — plus a third, GPU-less VM used only for the final evaluation pass.
- **Harness**: new custom orchestrator (`orchestrator/`), built this session, reusing mini-swe-agent's `DefaultAgent`/`DockerEnvironment`/`LitellmModel` unmodified — only new pieces are `GruModel` (swaps mini-swe-agent's hardcoded `bash` tool for `delegate_to_minion`/`finish`) and `GruEnvironment` (dispatches those two actions instead of running bash: spawns a minion sub-session per delegation against the shared persistent testbed, independently re-runs verification checks rather than trusting minion self-report, lets a failing `final_verification` continue the session instead of ending it).
- **Pinned**: `litellm==1.90.0` (same reason as exp0/exp1 — 1.97.0 breaks on pydantic); `MSWEA_COST_TRACKING=ignore_errors` (same reason as exp1 — litellm has no pricing entry for a self-hosted model).

## Procedure

```bash
# on the GPU instance (ollama/ollama image):
ollama pull qwen3.8:27b

# on the harness VM, venv with mini-swe-agent==2.4.6 litellm==1.90.0 swebench datasets pyyaml,
# orchestrator/ code copied over:
export OLLAMA_API_BASE=http://<gpu-instance-ip>:<mapped-port>
export MSWEA_COST_TRACKING=ignore_errors

python3 -m orchestrator.run_exp2_single \
  --instance astropy__astropy-12907 \
  --model ollama_chat/qwen3.8:27b \
  --api-base http://<gpu-instance-ip>:<mapped-port> \
  --output-dir results/astropy-12907
# repeat per instance

# merge results/*/prediction.json into one file, then evaluate exactly as exp0/exp1:
python3 -m swebench.harness.run_evaluation --predictions_path predictions_all5.json \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --instance_ids astropy__astropy-{12907,14182,14365,14995,6938} --max_workers 4 --run_id exp2_all5
```

## Results

| Instance | Resolved† | Gru's own verdict | Gru calls | Gru tokens | Minions | Minion tokens | Total tokens | Wall-clock |
|---|---|---|---|---|---|---|---|---|
| astropy-12907 | ✅ | ✅ agrees | 5 | 87,226 | 6 | 340,579 | 427,805 | 1520s |
| astropy-14182 | ❌ | ✅ **wrong** | 4 | 64,307 | 4 | 601,023 | 665,330 | 1172s |
| astropy-14365 | ❌ | ✅ **wrong** | 8 | 79,276 | 6 | 460,071 | 539,347 | 1036s |
| astropy-14995 | ✅ | ✅ agrees | 8 | 76,062 | 6 | 663,954 | 740,016 | 1088s |
| astropy-6938 | ✅ | ✅ agrees | 12 | 172,015 | 7 | 1,636,159 | 1,808,174 | 2380s |
| **Total** | 3/5 | 3/5 agree | 37 | 478,886 | 29 | 3,701,786 | 4,180,672 | ~2h56m |

**3/5 resolved (60%)** · Gru 478,886 tok (11.5% of total) · Minions 3,701,786 tok (88.5%) · 0 infra failures/empty patches/errors · no $ metered cost (self-hosted) · ~2h56m combined GPU-active wall-clock across 5 sequential sessions.

† Machine-verified for `astropy-12907` only; the other four verdicts are transcribed, not harness output — see [NOTES.md#verdict-provenance](./NOTES.md#verdict-provenance).

## Issues encountered

- **Bad SSH key provisioning on one specific vast.ai host** (`137.175.76.24`) — reproducible across two separate offer IDs that happened to land on the same physical host (same `public_ipaddr`), both rejecting the correct, registered key on both the direct and proxy SSH routes. Not a timing issue — the container built cleanly and served its custom banner, so sshd was genuinely running. Fix: when a fresh instance's SSH is refused, check whether its `public_ipaddr` matches a previously-broken instance before assuming it's just slow to boot — if so, destroy and pick an offer with a **different** IP, don't just retry the same host.
- **Docker Hub registry flakiness recurred** (same as exp1) — `EOF` and, this time, `tls: handshake failure` errors mid-pull on two separate harness VMs, for both the SWE-bench per-instance images and (once) the Ollama base image layers. Basic connectivity (`curl`, `openssl s_client`) tested clean immediately after a failed pull, confirming it's transient, not a host network problem. Fix: retry `docker pull` 2-4 times; it resumes from where it stopped and typically succeeds within a few attempts.
- **Real code bug**: `parse_gru_actions` crashed the entire session with an uncaught `AttributeError: 'str' object has no attribute 'get'` when Qwen returned `final_verification` (or `inputs`/`verification`) as a plain string instead of a nested JSON object — killing the process with **zero output saved** (no trajectory, no `cost_summary.json`, no `prediction.json`) for that instance. Fixed by validating `isinstance(value, dict)` before calling `.get()` on any nested tool-call field in `orchestrator/gru_toolcall.py`, turning the malformed-shape case into a recoverable `FormatError` (mini-swe-agent's built-in retry-with-feedback already handles this) instead of an uncaught crash. Caught and fixed mid-run, via `astropy__astropy-14995`'s first attempt; re-run succeeded after the fix.
- **SSH connection drops silently break local log capture even though the remote process survives** — vast.ai's VM template wraps sessions in tmux, so a dropped SSH connection doesn't kill the remote command, but a local-side `ssh cmd > local_file` redirect stops receiving output the instant the connection drops, with no error. Fix: for anything expected to run more than a few minutes, use `nohup cmd > remote_file 2>&1 &` on the **remote** side and poll the remote file/process over fresh SSH connections, not a local-side pipe.
- **Process mistake, not a code bug**: destroyed both vast.ai instances immediately after the run completed, before pulling the full Gru/minion trajectories for 4 of the 5 instances. That data is permanently lost — only `prediction.json`/`cost_summary.json` survived for those 4 (enough for the quantitative results above and for patch-level inspection, not enough to see the actual delegation reasoning behind `14182`'s regression or `14365`'s failure in this run). **Lesson, no exceptions**: pull every artifact — trajectories included, not just summary files — before any `vastai destroy`, regardless of time or cost pressure at that moment.

## Findings

- **3/5 resolved (60%) against exp1's 4/5 on the identical model and instance set**, differing on one instance (`astropy-14182`) — no detectable difference at n=5 (Fisher exact p=1.0; McNemar p=1.0 paired). Phase 1's scoping rule says resolve rate here is not signal either way ([04-machine-config.md](../../design/infra/04-machine-config.md) §9), and with 4 of 5 verdicts transcribed rather than machine-verified, this is recorded rather than interpreted.
- **Gru's self-authored `final_verification` passed in all 5 runs but only agreed with the real evaluation in 3/5** — a direct, measured instance of the caveat already written into `prompts/gru-loop.md` (passing your own proxy check doesn't guarantee the hidden evaluation agrees). See [NOTES.md#verification-divergence](./NOTES.md#verification-divergence--gru-was-confidently-wrong-twice) for both disagreement cases in detail.
- **`astropy-14365` produced the identical `re.IGNORECASE` fix across three independent experiments** (exp0 Haiku, exp1 solo Qwen, this run's Gru+minion) — including this run's Gru explicitly delegating a context-gathering step aimed at finding every place case-sensitivity lives. Strongest evidence yet that this specific blind spot is a property of the task, not of any one model or architecture.
- **`astropy-14182` regressed from resolved (exp1) to unresolved (this run)**: Gru's own reproduction script and self-authored regression test both passed, but encoded the same narrow scope as the PR's literal example — the same blind spot exp0's Haiku had on this exact instance, recurring through a more elaborate plan-and-verify process that didn't catch it. See NOTES.md for the patch comparison.
- **`astropy-6938`'s test-value modification (updating hardcoded CHECKSUM/DATASUM constants) initially looked like the reward-hacking pattern `DESIGN.md` warns about** — the real evaluation passing confirms it was a legitimate consequence of a genuine upstream bug fix, not gaming. See [NOTES.md#reward-hacking-check](./NOTES.md#reward-hacking-check-on-astropy-6938s-test-modification) for the patch-level reasoning.
- **Total token spend was 3.5x exp1's** for the same 5 instances (4,180,672 vs. 1,195,602) — Gru itself stayed cheap (11.5% of total, consistent with the architecture's intent), but minion volume grew substantially per instance, and `astropy-14365` alone cost 13.5x exp1's solo run for the same failed outcome. See [NOTES.md#token-cost-breakdown](./NOTES.md#token-cost-breakdown) — some of this is plausibly fixable prompt inefficiency (verbatim-reproduction duplication, redundant re-verification delegations), identified but not yet fixed before this run.

## Conclusion & next steps

The harness runs end-to-end — delegation, independent verification, and inline retry after a failed check all fired for real during this batch (`astropy-12907`'s t3→t4→t6) and worked as designed, which was Phase 1's actual goal. The finish-rejection path did **not** fire: `final_verification` passed on the first `finish` attempt in all 5 runs, so that branch remains untested. Resolve rate and token spend are not Phase 1 signal (§9), so the exp1 comparison is recorded above rather than concluded from. Next: fix the two efficiency issues already identified this session (verbatim-reproduction duplication in `output_contract`, redundant re-verification delegations) before any further same-model runs, since some of this run's regression and cost story may be attributable to fixable prompt issues rather than an inherent property of the architecture — then proceed to Phase 2's actual frontier-Gru condition, which is the real test of the cost hypothesis this project exists to answer.

## Artifacts

Under `experiments/exp2/`: `trajectories/` (full Gru + minion trajectories for `astropy-12907` only — lost for the other 4 instances, see Issues), `results/<instance>/prediction.json` + `cost_summary.json` for all 5 instances, `results/predictions_all5.json`, `results/summary_report_5instances.json` (**transcribed** evaluation verdict for 4 of 5 instances — see [NOTES.md#verdict-provenance](./NOTES.md#verdict-provenance)), `results/astropy-12907/eval_report.json` (the one real harness report), [`NOTES.md`](./NOTES.md) (token/verification-divergence/reward-hacking methodology behind the Findings above).
