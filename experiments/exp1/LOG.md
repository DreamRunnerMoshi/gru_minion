# Experiment 1: cheap model alone, no plan, no verification — self-hosted Qwen3.8-27B

- **Status**: complete
- **Date**: 2026-08-20/21
- **Hypothesis under test**: same sanity check as [Experiment 0](../exp0/LOG.md), same instances, model swapped from Haiku 4.5 (API) to Qwen3.8-27B (self-hosted) — does the resolve pattern hold, and does self-hosted infra work end-to-end for the Gru/minion candidate model? (Still not a test of Gru/minion itself — that's a later experiment. Also not Phase 2's cost ablation, see [[project-machine-config]] — this is plumbing + a first capability data point only.)

## Setup

- **Model**: `ollama_chat/qwen3.8:27b` (Q4_K_M, 17GB), self-hosted via Ollama on a rented vast.ai RTX 3090
- **Dataset**: `SWE-bench/SWE-bench_Lite`, split=`test` (mini-swe-agent's own runner loads `princeton-nlp/SWE-Bench_Lite` internally and that's fine for it — the `SWE-bench/SWE-bench_Lite` mirror is only required for the separate `swebench.harness.run_evaluation` step, same distinction exp0 found)
- **Instances**: identical to exp0 for direct comparability: `astropy__astropy-{12907,14182,14365,14995,6938}`
- **Infra**: two vast.ai instances (GPU inference is a categorically different setup from exp0 — see [design/infra/04-machine-config.md](../../design/infra/04-machine-config.md))
  - **Inference**: RTX 3090, 24GB, container instance (image `ollama/ollama`), $0.1548/hr, label `qwen-minion`, id `48252155`
  - **Harness**: Quadro P4000 VM (`docker.io/vastai/kvm` template, real KVM — nested Docker needed for SWE-bench's per-instance images, same requirement exp0 hit), $0.0767/hr, label `swe-exp1-vm`, id `48256347`
- **Harness**: mini-swe-agent v2.4.6, default `swebench.yaml` config, unmodified except model/api_base
- **Pinned**: `litellm==1.90.0` (same pin as exp0, same reason — 1.97.0 breaks on pydantic)

## Procedure

```bash
# on the GPU instance (ollama/ollama image, port 11434 exposed):
ollama pull qwen3.8:27b

# on the harness VM, venv with mini-swe-agent==2.4.6 litellm==1.90.0 swebench:
export OLLAMA_API_BASE=http://<gpu-instance-ip>:<mapped-port>
export MSWEA_COST_TRACKING=ignore_errors   # see Issues

mini-extra swebench-single --subset lite --split test --instance astropy__astropy-12907 \
  --model ollama_chat/qwen3.8:27b -c swebench.yaml \
  -c model.model_kwargs.api_base=http://<gpu-instance-ip>:<mapped-port> \
  --cost-limit 0 --yolo --exit-immediately --output trajectories/astropy-12907.traj.json

mini-extra swebench --subset lite --split test \
  --filter "astropy__astropy-(14182|14365|14995|6938)" \
  --model ollama_chat/qwen3.8:27b -c swebench.yaml \
  -c model.model_kwargs.api_base=http://<gpu-instance-ip>:<mapped-port> \
  --workers 1 --output batch_results

# merge trajectories["info"]["submission"] for the single-run pilot into batch_results/preds.json
# (swebench-single doesn't write to preds.json the way the batch runner does)

python3 -m swebench.harness.run_evaluation --predictions_path predictions_all5.json \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --instance_ids astropy__astropy-{12907,14182,14365,14995,6938} --max_workers 4 --run_id exp1_qwen_all5
```

## Results

| Instance | Resolved | Prompt tok | Compl tok | Cache-hit% (est.) | API calls | Wall-clock |
|---|---|---|---|---|---|---|
| astropy-12907 | ✅ | 119,053 | 6,313 | 94.8% | 14 | n/a (pilot, untimed) |
| astropy-14182 | ✅ | 509,266 | 16,097 | 96.8% | 27 | 15m47s |
| astropy-14365 | ❌ | 38,684 | 1,393 | 90.2% | 11 | 3m26s |
| astropy-14995 | ✅ | 145,707 | 5,159 | 93.3% | 16 | 4m25s |
| astropy-6938 | ✅ | 346,147 | 7,783 | 97.6% | 40 | 7m43s |
| **Total** | 4/5 | 1,158,857 | 36,745 | 96.2% | 108 | ~45m |

4/5 resolved (80%) · ~$0.17 GPU+VM rental (~0.75hr combined) · 0 infra failures/empty patches/errors · no $ metered cost (self-hosted)

## Issues encountered

- **litellm cost-tracking crash on self-hosted models** → mini-swe-agent computes `cost` per call and raises `RuntimeError: Cost must be > 0.0, got 0.0` when litellm has no pricing table entry for the model string (expected for any self-hosted/Ollama model — there's no $/token to look up). Fix: `export MSWEA_COST_TRACKING=ignore_errors`. This disables mini-swe-agent's own `model_stats.instance_cost` (stays `0.0`), **but the raw token counts are not actually lost** — each saved trajectory's `messages[i]["extra"]["response"]["usage"]` still holds litellm's real `{prompt_tokens, completion_tokens, total_tokens}` per call, since that's set before the cost calculation that crashes. Pull real usage by summing that field across all assistant messages in the trajectory JSON rather than trusting `model_stats` — that's how the Results table's token columns were built after the fact.
- **vast.ai container port mapping isn't the container's literal port** → the Ollama instance exposed `11434/tcp` internally, but the public reachable port was a different NAT'd host port (found via `vastai show instance --raw` → `ports` field, e.g. `11434/tcp → HostPort 29637`). Same applies to SSH (`22/tcp` mapped to a different host port than the CLI's own `ssh-url` output implied for the VM instance — see next bullet). Always read the actual `ports` mapping from `show instance`, don't assume the container's declared port is externally reachable at that number.
- **`vastai ssh-url`'s proxy route (`sshN.vast.ai:<port>`) was unreachable for several minutes after the VM instance reported `running`** → the outer container (`docker.io/vastai/kvm`) reports running once it starts, but the *inner* KVM VM still needs to boot its own OS — SSH via the proxy route stayed refused through that window. The direct route (`public_ipaddr:<HostPort for 22/tcp from the `ports` field>`) came up and was usable earlier. When a freshly-created VM instance's SSH is refused, try the direct public IP + mapped port before assuming the instance is stuck.
- **`scp` hung indefinitely (no output, no error) against the vast.ai SSH proxy**, both for the GPU and VM instances, despite plain `ssh '<command>'` working reliably throughout. Likely the SFTP/SCP subsystem isn't cleanly proxied. Fix: use `ssh host 'cat remote_file' > local_file` for pulling artifacts instead of `scp`.
- **`mini-extra swebench-single` doesn't populate `preds.json`** the way the batch `mini-extra swebench` runner does — had to manually extract `trajectory["info"]["submission"]` from the single-run's saved trajectory JSON and merge it into the batch's `preds.json` before running `run_evaluation` on all 5 together. Same two-tool split existed in exp0 but wasn't called out explicitly there.

## Findings

- **`astropy-14365` failed with the exact same fix and root cause as exp0's Haiku run** (`re.IGNORECASE` on the QDP classifier regex, missing a downstream exact-case dispatch step). Strong signal the failure is about the *task*, not either model — reinforces exp0's "recoverable by verification, not a capability gap" finding, now across two models.
- **`astropy-14182` flipped from unresolved (Haiku) to resolved (Qwen)** — the one instance where the models diverge. Not investigated further (out of scope for Phase 1 plumbing validation, see [[project-machine-config]]), but worth a diff read before crediting "Qwen beat Haiku" to anything specific.
- **API calls vary 11–40 per instance with no correlation to resolution** (the failure used the *fewest* calls) — consistent with exp0: these are confident-but-wrong failures, not give-up-early ones.
- Self-hosted infra (separate GPU-inference + harness-VM instances talking over the public internet) worked end-to-end on the first real attempt — validates the Phase 1 infra sketch in [design/infra/04-machine-config.md](../../design/infra/04-machine-config.md) §9. Minion role only this run — no Gru/plan/verification loop yet.
- **Measured throughput ~16.2 completion-tok/s, effective ~$0.097/M tokens blended** — cheaper than every API comparator in the machine-config doc, but not yet the same-model-at-scale breakeven claim that doc's §6-8 actually tests. See [NOTES.md#throughput](./NOTES.md#throughput---measured-completion-tok-s) / [#effective-cost](./NOTES.md#effective-cost---measured-m-tokens).
- **83% of completion tokens are tool-call payload, but that's not "cheap boilerplate"** — 73% of that payload's character volume is embedded Python (repro scripts, fix attempts), genuine task-solving work a lesser executor couldn't skip. See [NOTES.md#tool-call-breakdown](./NOTES.md#tool-call-breakdown---what-completion-tokens-are-actually-spent-on).
- **Cache-hit ~96% (estimated, not measured — instances were destroyed before this gap was caught)** — real self-hosted cost lever, independent of model choice, and mostly disappears against a metered API that bills full prompt tokens per call. See [NOTES.md#cache-estimate](./NOTES.md#cache-estimate---cache-hit--and-why-its-estimated-not-measured).

## Conclusion & next steps

Qwen3.8-27B self-hosted on a single RTX 3090 resolved 4/5 (80%) on the same instance set Haiku 4.5 resolved 3/5 (60%) on in exp0, with the one shared failure instance showing an identical root-cause fix attempt across both models — a real, if small, capability data point, and a working self-hosted-inference plumbing validation. Does **not** yet test the Gru/minion framework (still just a solo agent, no plan/verification loop) — that's the next experiment, and per [[project-machine-config]] should reuse this same self-hosted qwen3.8:27b server for both the Gru and minion roles per Phase 1's plan. Also flags an open infra gap: token/cost capture for self-hosted models needs a real solution before Phase 2's A/B/C/D cost ablation can log meaningful numbers (see Issues).

## Artifacts

Under `experiments/exp1/`: trajectories (`trajectories/*.traj.json`), `results/predictions_all5.json`, `results/summary_report_5instances.json` (SWE-bench harness report), [`NOTES.md`](./NOTES.md) (token/cache methodology behind the Findings bullets above).
