# exp3 Runbook

Operational steps for running [LOG.md](./LOG.md)'s experiment. Every gotcha below cost real time in exp0/exp1/exp2 — none of it is hypothetical.

## 0. Provision

Two vast.ai instances (same shape as exp1/exp2):

| Role | Requirement | Why |
|---|---|---|
| **Inference** | RTX 3090 24GB, image `ollama/ollama`, ~$0.10–0.16/hr | Qwen3.8-27B Q4_K_M is ~17GB |
| **Harness** | `docker.io/vastai/kvm` template, `vms_enabled=True`, ~$0.05–0.08/hr, ≥80GB disk | SWE-bench needs **nested** Docker; vast.ai's default container instance blocks Docker-in-Docker at the kernel level |

```bash
vastai search offers 'gpu_name=RTX_3090 num_gpus=1 disk_space>60' -o dph
vastai search offers 'vms_enabled=True disk_space>80' -o dph
```

**Port mapping**: the container's declared port is *not* the reachable one. Always read the real mapping:
```bash
vastai show instance <id> --raw | python3 -c "import json,sys;print(json.load(sys.stdin)['ports'])"
# e.g. 11434/tcp -> HostPort 29637 ; 22/tcp -> some other host port
```

**SSH**: if `vastai ssh-url`'s proxy route (`sshN.vast.ai`) is refused, try the **direct** route (`public_ipaddr` + the mapped host port for `22/tcp`) — it comes up earlier while the inner KVM VM is still booting. If SSH is still refused, check whether `public_ipaddr` matches a host that already failed: exp2 hit a box (`137.175.76.24`) that rejected a correctly-registered key across two separate offers. Destroy and pick a **different IP** rather than retrying the same host.

## 1. Set up the inference instance

```bash
ollama pull qwen3.8:27b
curl http://localhost:11434/api/tags   # confirm it is served
```

## 2. Set up the harness VM

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install 'mini-swe-agent==2.4.6' 'litellm==1.90.0' swebench datasets pyyaml jinja2
# litellm 1.97.0 raises PydanticUserError on pydantic 2.13 before any network call — keep the pin.

git clone <this repo> && cd coding_agent_benchmark
docker --version && docker run --rm hello-world   # nested Docker must work here
```

Pre-pull the per-instance images — **Docker Hub is intermittently flaky** (`EOF`, `tls: handshake failure` mid-pull, in both exp1 and exp2). Retry 2–4 times; pulls resume where they stopped.

## 3. Run an arm

Always under `nohup`, redirecting **on the remote side**. A dropped SSH connection silently stops a local-side `ssh cmd > file` pipe while the remote process keeps running — that cost a run in exp2.

```bash
export OLLAMA_API_BASE=http://<gpu-ip>:<mapped-port>
nohup scripts/run_arm.sh B gru.yaml ollama_chat/qwen3.8:27b "$OLLAMA_API_BASE" > run_B.log 2>&1 &

# poll over fresh connections:
ssh -p <port> <host> 'tail -20 coding_agent_benchmark/run_B.log'
```

`run_arm.sh` is resumable — an instance with a `cost_summary.json` is skipped, so a crashed batch can be restarted without redoing work. It takes an explicit `<label> <gru-config.yaml>` pair (revised 2026-08-24) rather than a fixed A/B lookup — `B gru.yaml` above is this file's own gate; a different fragment-based variant (e.g. `gru-minimal.yaml`, see [prompts/gru-loop.md](../../prompts/gru-loop.md)) runs the same way with a different label and config name, no script change needed.

**Arm A / `gru-taxonomy.yaml` (the old type-taxonomy prompt, exp2's policy) was deleted 2026-08-24.** It was deferred per this experiment's own Conclusion (never run — B missed its gates, and A tests a different variable that wouldn't explain why) and superseded by the fragment/`ToolPolicy` ablation approach in [prompts/gru-loop.md](../../prompts/gru-loop.md). The decision table that used to be here is preserved in [LOG.md](./LOG.md) as historical record; it no longer describes a runnable option.

## 4. Pull artifacts — before destroying anything

```bash
# LOCAL:
scripts/pull_artifacts.sh root@<ip> <ssh-port> B
.venv/bin/python scripts/verify_artifacts.py experiments/exp3/results/B
```

`verify_artifacts.py` must exit **0**. It fails on: a missing instance directory, a missing `gru.traj.json`, a missing agentic minion trajectory, a missing delegation output, absent cache stats, or an empty patch. `tar`-over-`ssh` is used rather than `scp` because scp/sftp hangs indefinitely against vast.ai's SSH proxy while plain `ssh host 'cmd'` works.

**Only after exit 0**: `vastai destroy instance <id>`.

> exp2 destroyed both instances before pulling trajectories for 4 of 5 instances. That data is permanently gone. For exp3 the trajectories *are* the measurement, not a debugging aid.

## 5. Evaluate + analyze — one command

Needs Docker; run on the harness VM or a fresh GPU-less VM.

```bash
scripts/evaluate.sh B ollama_chat/qwen3.8:27b
```

That does four things in order: merges arm B's per-instance predictions, evaluates them, **re-evaluates exp2's intact `predictions_all5.json`**, and builds the results table. No other commands are needed.

**Why exp2 is bundled**: it grades the same five astropy instances, so the expensive part — pulling per-instance Docker images — is paid once and serves both. It also means both verdicts come from the same harness version, which matters because exp3's gate *is* a comparison against exp2. And exp2's own verdict is still transcribed for 4 of 5 instances ([R3](../../review.md), [exp2/NOTES.md#verdict-provenance](../exp2/NOTES.md#verdict-provenance)).

**Where the reports land.** swebench names its report `{model_name_or_path with / → __}.{run_id}.json` and writes it to `--report_dir` (default: the current directory). exp2 lost its report by not knowing that. `evaluate.sh` pins the directory, so expect:

```
experiments/exp3/reports/ollama_chat__qwen3.8:27b.exp3_B.json
experiments/exp3/reports/ollama_chat__qwen3.8:27b.exp2_reverify.json
```

Commit both. Per-instance detail also lands under `logs/run_evaluation/<run_id>/`.

Use the `SWE-bench/` mirror — `princeton-nlp/SWE-bench_Lite` lacks the `image` field and fails with `KeyError: 'image'`. `evaluate.sh` already does.

**If `exp2_reverify` disagrees with the transcribed 3/5**: that is a real finding, not a nuisance. Update `exp2/LOG.md`, `review.md` `R3`, and re-check `R15`/`R16` — both lean on "`14182` regressed" as the thing being explained.

## 6. Analyze separately (only if step 5 partially failed)

```bash
.venv/bin/python -m orchestrator.analyze_run \
  --results-dir experiments/exp3/results/B \
  --eval-report experiments/exp3/reports/ollama_chat__qwen3.8:27b.exp3_B.json
```

Writes `coverage.json` and `results_table.md`, and prints the table for [LOG.md](./LOG.md). The Resolved column is populated **only** from a real harness report — never fill it by hand.

## Reading the numbers

- **Token totals are not cost.** `mode="oneshot"` removes history resend that prefix caching was already partly absorbing, so an exp3-vs-exp2 token delta is not a cost delta. Use wall-clock and the captured cache-hit figures. Estimated cache-hit is an **upper bound**, not a measurement.
- **Resolve rate is a gate, not a finding.** n=5, one repo, single runs. See [LOG.md](./LOG.md)'s success criteria and `R4`.
- **Coverage saturates on tiny patches** — `astropy-12907`'s gold patch has two identifiers. `first_hit_delegation` is the robust signal there.

## Gotcha index

| Symptom | Fix | First seen |
|---|---|---|
| Docker-in-Docker blocked | `vms_enabled=True` + `docker.io/vastai/kvm` | exp0 |
| `PydanticUserError: Message is not fully defined` | pin `litellm==1.90.0` | exp0 |
| `KeyError: 'image'` in run_evaluation | use `SWE-bench/SWE-bench_Lite` | exp0 |
| `RuntimeError: Cost must be > 0.0` | `export MSWEA_COST_TRACKING=ignore_errors` | exp1 |
| Port unreachable at container's declared port | read `ports` from `show instance --raw` | exp1 |
| SSH refused right after "running" | use direct `public_ipaddr` + mapped port | exp1 |
| `scp` hangs forever | `tar` over `ssh`, or `ssh host 'cat f'` | exp1 |
| SSH key rejected on a specific host | check `public_ipaddr` against known-bad; pick a different IP | exp2 |
| `EOF` / `tls: handshake failure` mid-pull | retry `docker pull` 2–4× | exp1/exp2 |
| Local log capture stops, remote keeps running | `nohup` + remote-side redirect | exp2 |
| `RepeatedFormatError` kills a session | `think` action + `max_consecutive_format_errors: 6` (both new; unvalidated) | exp2-rerun |
| `docker.io/vastai/kvm:latest` — `manifest unknown` | no `latest` tag exists anymore; use a dated tag, e.g. `ubuntu_cli_22.04-2025-11-21` | exp3 |
| `ollama/ollama` image doesn't auto-`serve` under `--ssh` launch | vast.ai's ssh wrapper replaces the entrypoint; `nohup ollama serve &` manually after boot | exp3 |
| `pull_artifacts.sh` silently pulls from `~/` instead of the repo | non-interactive `ssh host 'cmd'` starts in `$HOME`, not the repo — script now `cd`s explicitly | exp3 |
| `KeyError: 'cost'` crashes every instance at the bookkeeping step | `minion_records` (exp3's rewritten schema) never has `"cost"`; field dropped from `run_gru_session.py` | exp3 |
| Uncaught exception (e.g. Ollama's `"no user query found in messages"`) loses the whole session | `run_gru_session.py` had no `except` around `gru_agent.run()`; now falls back to git-diff like the `RepeatedFormatError` path | exp3 |
| `python -m orchestrator.analyze_run` runs, prints nothing, writes nothing, exits 0 | missing `if __name__ == "__main__": main()` guard | exp3 |
