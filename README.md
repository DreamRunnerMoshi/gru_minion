# Gru & Minion

A two-tier agent architecture: **Gru**, a frontier model, owns a task end to end
(diagnosis, decisions, verification) and delegates bounded, well-specified pieces of
work to **Minion**, a cheap model. Delegation is Gru's choice per step, never forced.
Tested against real evaluation harnesses — the actual SWE-bench test suite, exact-match
against GAIA's hidden gold answer — never the agent's own self-report.

Two things measured: how much of a session's real token/dollar cost moves to the minion
when that choice is left alone, and whether it moves without taking accuracy with it.

## Headline findings

| Vendor pair (Gru → minion) | Minion token share |
|---|---|
| Qwen: `qwen3-max` → `qwen3-coder-flash` | **78.6%** |
| GLM: `glm-4.6` → `glm-4.5-air` | **61.6%** (SWE-bench), **69.7%** (GAIA) |
| GPT: `gpt-5-mini` → `gpt-4.1-nano` | **92.3%** |

All three pairs matched or beat their own solo baseline on real SWE-bench evaluation.

| Metric | Result |
|---|---|
| GAIA resolve rate, same pair, vendor swap only | **14% → 52%** |
| Self-caught infra bugs, fixed pre-publish | **3** |
| Delegation driver (12-run prompt ablation) | task-fit, not wording forcefulness |

- **Delegation ablation**: persona framing, a negative constraint, and a "trust your
  peers" instruction all failed alone; a rule tied to the task's actual workflow worked.
  Details: [`exp4/NOTES.md`](experiments/exp4/NOTES.md),
  [`exp4/DELEGATION_FAILURE_MODES.md`](experiments/exp4/DELEGATION_FAILURE_MODES.md).
- **Bugs caught pre-publish**: a patch-extraction bug hiding correct sessions as
  failures, a cost-tracking gap making a dollar cap a no-op for some models, and a
  self-authored prompt divergence mid-experiment — each caught, and the confounded batch
  deleted and rerun rather than kept.

## Architecture

![architecture](docs/architecture.png)

Two tools drive everything: `delegate_to_minion` (hand off bounded work — "findings"
to investigate/report, or "verdict" to do-and-self-verify) and `run_check` (Gru's own
independently re-run verification — the "verifiability trap": once a real mechanical
check has settled a result, Gru trusts the check, not the report). The tool schema and
shared prompts (`orchestrator/gru/prompts/*.md`) are identical across every benchmark;
only the benchmark module (`orchestrator/benchmarks/`) and its `instance_template`
change — porting to a new benchmark holds the architecture and prompt fixed by design.

Built on [`mini-swe-agent`](https://github.com/SWE-agent/mini-swe-agent) and
[`litellm`](https://github.com/BerriAI/litellm).

## Use it in Claude Code

```
/plugin marketplace add DreamRunnerMoshi/gru_minion
/plugin install gru-minion@gru-minion
/gru-minion
```

**No API key, no install step.** The default path delegates through Claude Code's own
`Agent` tool to a cheaper model (`haiku`) in the same session — in the one head-to-head
run so far, a third of the tool calls and a quarter of the tokens of the alternative
below on an identical task (numbers in `orchestrator/config/presets.yaml`'s
`_native_task_delegation` entry — one comparison, not a settled verdict).

For a specific non-Claude minion (GLM, Qwen, DeepSeek, ...), an independently re-run
PASS/FAIL verdict, or a per-delegation dollar figure, the plugin also drives
`gru-delegate` (needs `OPENROUTER_API_KEY`):

```bash
uvx --from "git+https://github.com/DreamRunnerMoshi/gru_minion@v0.1.0" gru-delegate --help
# or: pip install git+https://github.com/DreamRunnerMoshi/gru_minion
```

```bash
gru-delegate --spec task.json --session .gru/s1
gru-delegate --session .gru/s1 --summary     # what it cost
```

**Caveat**: a `verdict` delegation reverts anything in the working tree beyond its own
changes — correct against a throwaway benchmark container, destructive against a real
checkout with uncommitted work. `gru-delegate` refuses a dirty tree for verdict
delegations and snapshots (`git stash create`) before every delegation regardless, but
commit first anyway.

## Repo layout

```
orchestrator/           Core harness: run_session.py (entrypoint), session.py (wiring +
                         cost accounting), configs.py.
orchestrator/gru/       Planning role: tool schema, model wrapper, action loop, prompts/.
orchestrator/minion/    Execution role: model wrapper + delegation runner (oneshot vs.
                         agentic bash loop).
orchestrator/benchmarks/    One module per dataset (base.py interface): swebench.py,
                         gaia.py, GAIA's loader/scorer, gaia_sandbox/.
orchestrator/metrics/   Token, cache, real-cost and localization-coverage accounting.
orchestrator/config/    One dir per benchmark (swe_bench/, gaia/): benchmark.yaml +
                         gru.yaml, gru-solo.yaml, minion.yaml, environment.yaml.
experiments/exp0–exp6/  One dir per experiment: NOTES.md, raw trajectories, real
                         evaluation reports.
plugins/gru-minion/     The Claude Code plugin (skill carrying the operating doctrine).
scripts/                Batch runner (run_batch.sh + specs under batches/), evaluation
                         and artifact-pull helpers.
tests/                  Unit + harness tests (fake environments, no live API calls).
literature-review/      Notes on prior art and related benchmarks.
docs/                   Architecture diagram.
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install litellm mini-swe-agent swebench pyyaml requests beautifulsoup4 lxml \
            pandas numpy sympy datasets huggingface_hub
```

Requires API keys for whichever provider you point at (this project runs everything
through [OpenRouter](https://openrouter.ai)) and, for GAIA, a [Tavily](https://tavily.com)
key and a Hugging Face token with approved GAIA dataset access. Copy `.env.example` to
`.env` (gitignored) or export directly:

```bash
export OPENROUTER_API_KEY=...
export TAVILY_API_KEY=...     # GAIA only
export HF_TOKEN=...           # GAIA only, needs approved dataset access
```

## Running a session

```bash
python -m orchestrator.run_session --benchmark swe_bench \
  --instance astropy__astropy-14182 \
  --gru-model openrouter/z-ai/glm-4.6 \
  --minion-model openrouter/z-ai/glm-4.5-air \
  --output-dir results/my-run
```

GAIA needs `orchestrator/benchmarks/gaia_sandbox` built as a local Docker image first:

```bash
python -m orchestrator.run_session --benchmark gaia \
  --instance <gaia-task-id> \
  --gru-model openrouter/google/gemini-3.7-flash \
  --minion-model openrouter/deepseek/deepseek-v3.2 \
  --output-dir results/my-gaia-run
```

`--benchmark` names a benchmark's own `benchmark.yaml` (dataset, container, configs); a
slash selects a declared `variant` — `swe_bench/solo` and `gaia/solo` run Gru with no
delegation, for a solo baseline. Adding a dataset means adding a module under
`orchestrator/benchmarks/` and a config directory — nothing in the runner changes.

A sweep runs through `scripts/run_batch.sh`, which takes a spec naming instances, model
pairs and arms (each arm is just a benchmark spec, so solo-vs-paired is a config choice):

```bash
nohup scripts/run_batch.sh scripts/batches/exp5-cross-vendor.sh > exp5_batch.log 2>&1 &
scripts/evaluate_batch.sh experiments/exp5/results experiments/exp5/reports exp5
```

`orchestrator/analyze_run.py` turns a batch of result directories into a results table
merged against a real evaluation report.

## Experiments

| # | What it tests |
|---|---|
| exp0 – exp1 | Sanity baseline: does a cheap model fail without a plan or verification, then a solo self-hosted model on real SWE-bench instances. |
| exp2 – exp3 | First Gru/minion split, then a full architecture rewrite: one action per turn, per-delegation cost visibility, a findings-vs-verdict return-type split. |
| exp4 | Twelve live runs, one instance, one evolving prompt — isolates what actually drives delegation. |
| exp5 | 30-run cross-vendor batch on real SWE-bench instances: three independent model pairs, solo vs. paired. |
| exp6 | Same architecture and prompt, ported to GAIA — a completely different task shape. |

Each has a `NOTES.md` documenting what changed, what the real evaluation said, and what
broke along the way — including failures, not just results that worked.

## Relation to [DecisionBench](https://arxiv.org/abs/2605.19099)

Not an answer to DecisionBench — a much smaller, single-lab effort that independently
hit three of its eight named limitations before that framing existed, with data that
speaks to them directly: isolating orchestration from system-prompt priming (exp4's
ablation, at small scale), pool-freeze-date pricing drift (hit independently; switched
the primary metric from dollar share to token share in response), and single-seed
variance (this project offers cross-*pair* replication, a narrower, different axis, not
a substitute). The other five limitations are untouched by anything here.
