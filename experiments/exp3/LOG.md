# Experiment 3: rewritten delegation architecture, same model both roles

- **Status**: planned
- **Date**: —
- **Hypothesis under test**: does the rewritten architecture ([review.md](../../review.md) `R5`/`R6`/`R13`/`R15`/`R16`/`R17`) recover [exp1](../exp1/LOG.md)'s solo-Qwen baseline of 4/5, and what does delegation cost once `mode="oneshot"` and one-action-per-turn are in place? Same model in both roles again, so this is **not** a test of the cost hypothesis — Phase 1 framework validation per [[project-machine-config]].

## Setup

- **Model**: `ollama_chat/qwen3.8:27b` for **both** Gru and minion — deliberate. Holding the model fixed makes this directly comparable to exp1 (solo) and exp2 (Gru/minion, old design) on the identical instances. Frontier-Gru is deferred; the runner still uses one `--model` for both roles and cannot split them.
- **Dataset**: `SWE-bench/SWE-bench_Lite`, split=`test`, same 5 instances as exp0/exp1/exp2: `astropy__astropy-{12907,14182,14365,14995,6938}`.
- **Arms**: **B** (`gru.yaml`, no taxonomy — the change under test) and, if run, **A** (`gru-taxonomy.yaml`, exp2's policy on the fixed harness). A exists to separate the harness fixes from the policy change; see that file's header.
- **Infra**: two vast.ai instances, same pattern as exp1/exp2 (RTX 3090 serving Ollama; harness VM for nested Docker), plus a GPU-less VM for evaluation.
- **Harness**: `orchestrator/` as of `exp3_*` commits. New since exp2: one action per turn enforced in the parser, `think`, `run_check`, `mode` (`oneshot`/`agentic`), `returns` (`findings`/`verdict`) replacing the `type` taxonomy, per-delegation token cost fed back to Gru, coverage receipts on findings delegations, live cache capture, persisted delegation outputs.
- **Pinned**: `litellm==1.90.0`; `MSWEA_COST_TRACKING=ignore_errors` (both same reasons as exp1/exp2).

## Success criteria

Stated in advance, and deliberately **gates, not findings** — at n=5 none of this is a statistically meaningful comparison (`R4`).

1. **Primary gate: `astropy-14182` resolves again.** `14365` has failed identically in exp0, exp1 and exp2, so 5/5 is not realistically reachable; exp1's 4/5 was exactly everything-but-`14365`. "At least 4/5" therefore reduces to this one instance — the one both `cce461c`'s pre-finish rule and the coverage receipts target.
2. **The harness completes 5/5 sessions without `RepeatedFormatError`.** 2 of 3 exp2-rerun attempts died there (`R17`); `think` is the intended fix.
3. **Every trajectory pulled before any `vastai destroy`.** The trajectories *are* the data for the delegation analysis — exp2 lost 4 of 5 and it cannot be redone.

## Procedure

```bash
# GPU instance (ollama/ollama image):
ollama pull qwen3.8:27b

# harness VM, venv with mini-swe-agent==2.4.6 litellm==1.90.0 swebench datasets pyyaml:
export OLLAMA_API_BASE=http://<gpu-ip>:<mapped-port>
export MSWEA_COST_TRACKING=ignore_errors

# arm B (default config), per instance:
python3 -m orchestrator.run_exp2_single \
  --instance astropy__astropy-12907 \
  --model ollama_chat/qwen3.8:27b \
  --api-base http://<gpu-ip>:<mapped-port> \
  --output-dir results/B/astropy-12907

# arm A (taxonomy control), same instances:
python3 -m orchestrator.run_exp2_single ... --gru-config gru-taxonomy.yaml --output-dir results/A/...

# PULL ARTIFACTS BEFORE DESTROYING ANYTHING (see success criterion 3)

# evaluation, same as every prior experiment:
python3 -m swebench.harness.run_evaluation --predictions_path predictions_all5.json \
  --dataset_name SWE-bench/SWE-bench_Lite --split test \
  --instance_ids astropy__astropy-{12907,14182,14365,14995,6938} --max_workers 4 --run_id exp3_all5

# localization coverage, post-hoc (gold patch never visible at inference time):
python3 -c "from orchestrator.coverage import score_run; ..."
```

## Results

_Not yet run._ Keep the harness report as machine-generated output this time — exp2's was transcribed for 4 of 5 instances and is still unverified (`R3`, [exp2/NOTES.md#verdict-provenance](../exp2/NOTES.md#verdict-provenance)).

| Instance | Resolved | Gru turns | think | run_check | Delegations | oneshot | Gru tok | Minion tok | Est. cache-hit% | Coverage | Wall-clock |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | |

## Issues encountered

_—_

## Findings

_—_

## Conclusion & next steps

_—_

## Artifacts

Under `experiments/exp3/`: `results/<arm>/<instance>/` (`prediction.json`, `cost_summary.json` incl. per-role `cache`, `delegations/*.txt`, `minions/*.traj.json`), `gru.traj.json` per run, plus the machine-generated evaluation report.
