# Experiment 0: cheap model alone, no plan, no verification

- **Status**: complete
- **Date**: 2026-08-19
- **Hypothesis under test**: sanity check — does a cheap model actually fail on real SWE-bench tasks with no plan/verification? (Not a test of Gru/minion itself — that's Experiment 1.)

## Setup

- **Model**: `openrouter/anthropic/claude-haiku-4.5`
- **Dataset**: `SWE-bench/SWE-bench_Lite`, split=`test` (not `princeton-nlp/SWE-bench_Lite` — that mirror lacks the `image` field the eval harness needs)
- **Instances**: first 5 by dataset order (all astropy, coincidence of ordering — use a stratified/random sample next time): `astropy__astropy-{12907,14182,14365,14995,6938}`
- **Infra**: vast.ai VM (real KVM VM, not their container product), Ubuntu 22.04 VM template, ~$0.067/hr
- **Harness**: mini-swe-agent v2.4.6, default `swebench.yaml` config, unmodified
- **Pinned**: `litellm==1.90.0` (1.97.0 is broken, see Issues)

## Procedure

```bash
mini-extra swebench-single --subset lite --split test --instance astropy__astropy-12907 \
  --model openrouter/anthropic/claude-haiku-4.5 -c swebench.yaml --cost-limit 0.75 \
  --yolo --exit-immediately --output trajectories/astropy-12907.traj.json

mini-extra swebench --subset lite --split test \
  --filter "astropy__astropy-(14182|14365|14995|6938)" \
  --model openrouter/anthropic/claude-haiku-4.5 -c swebench.yaml --workers 1 --output batch_results

python3 -m swebench.harness.run_evaluation --predictions_path predictions_all5.json \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --instance_ids astropy__astropy-{12907,14182,14365,14995,6938} --max_workers 4 --run_id exp0_all5
```

Ran the pilot single first to shake out infra bugs before committing to the full batch.

## Results

| Instance | Resolved | Cost | Tokens | API calls |
|---|---|---|---|---|
| astropy-12907 | ✅ | $0.1235 | 515,046 | 32 |
| astropy-14182 | ❌ | $0.1488 | 635,298 | 36 |
| astropy-14365 | ❌ | $0.0763 | 325,656 | 24 |
| astropy-14995 | ✅ | $0.2207 | 978,081 | 44 |
| astropy-6938 | ✅ | $0.4301 | 2,164,959 | 75 |

**3/5 resolved (60%)**, 0 infra failures, 0 empty patches — $1.25 / 5.27M tokens actual billed total (vs. $1.00 tracked in saved trajectories; gap is a killed pilot attempt, see Issues).

## Issues encountered

- **vast.ai's default instance is a container, not a VM** → Docker-in-Docker is blocked at the kernel level (confirmed unsupported by vast.ai). Fix: filter offers on `vms_enabled=True` and launch the `docker.io/vastai/kvm` template — a real VM despite the image name.
- **litellm 1.97.0 breaks on pydantic 2.13.4** (`PydanticUserError: Message is not fully defined`, fails before any network call). Fix: pin `litellm==1.90.0`.
- **`--yolo` doesn't cover the finish prompt** — the agent's submit step hangs on an interactive "type new task or Enter to quit" prompt with no TTY. Fix: add `--exit-immediately`.
- **Wrong dataset mirror** — `princeton-nlp/SWE-bench_Lite` lacks the `image` field `run_evaluation` needs (`KeyError: 'image'`). Use `SWE-bench/SWE-bench_Lite`.
- OpenRouter's new-account rate limit (10 req/min) caused transient retries; absorbed fine by litellm's backoff. Ran batch with `--workers 1` to be safe.

## Findings

Both failures root-caused, neither is drift/hallucination — same signature both times: **correct diagnosis, on-target minimal patch, but incomplete fix, submitted with false confidence**. The agent verified its own work using a hand-rolled test based only on the PR description's literal example, which passed — but it never had access to the real hidden FAIL_TO_PASS test, so "my test passes" wasn't real confirmation.

- `astropy-14182` (RST `header_rows`): fix addresses the right mechanism, but the agent only checked the PR's exact example, not whatever `test_rst_with_header_rows` actually asserts.
- `astropy-14365` (QDP case-insensitivity): made the classifier regex `re.IGNORECASE`, enough for the PR's one example, but apparently a downstream command-dispatch step still does exact-case comparison — untouched.

This is a stronger case for the project's hypothesis than plain drift would be: the fix is on the right track both times, so external verification should recover these cheaply via retry, not require re-solving from scratch.

## Conclusion & next steps

Hypothesis confirmed. Proceed to Experiment 1 (Gru-plans + cheap-executes against ground-truth verification) — specifically test whether giving the executor a way to check against real criteria (not its own guess) turns these two failures into passes, and at what retry cost.

## Artifacts

All under `experiments/exp0/results/`: trajectories (`*.traj.json`), `predictions_all5.json`, per-instance `report_*.json`, `summary_report_5instances.json`.
