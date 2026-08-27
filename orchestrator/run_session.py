#!/usr/bin/env python3
"""Run the Gru/minion architecture on a single benchmark instance.

Renamed 2026-08-26 from run_gru_session.py (which was itself renamed from
run_exp2_single.py; git history preserved via `git mv` both times), and merged with
run_gaia_session.py. The two were the same script apart from which dataset they loaded
and what they did with the result — both now come from the benchmark named by
`--benchmark`, resolved through a spec under orchestrator/config/<benchmark>/ and the
registry in orchestrator/benchmarks/. Adding a third dataset needs no change here.

Originally one shared `--model` for both roles (Phase 1 framework validation, see
design/infra/04-machine-config.md and memory project-machine-config) — using the same
model Gru/minion isolates the architecture's effect from model-capability differences,
directly comparable against exp1's solo-minion baseline on the same instances.

Revised 2026-08-24: `--gru-model`/`--minion-model` let the two roles use genuinely
different models (e.g. a frontier planner + a cheap executor over a hosted API), which
is what actually makes a cost comparison meaningful — Phase 1 held cost constant by
construction. `--api-base` is now optional: self-hosted Ollama needs it (point at the
serving instance); a hosted-API model (e.g. `openrouter/...`, routed by litellm via an
API key env var, not a custom endpoint) doesn't.

Revised 2026-08-25 (exp5 start): every call now carries an OpenRouter `session_id`
(via `extra_body`) — one per Gru session, one per minion delegation. Diagnosed from
exp4's cost data: real, provider-reported `cached_tokens` showed a handful of calls per
run (up to 10 of 41) with near-0% cache hit despite a warm cache existing moments
earlier, uncorrelated with wall-clock gaps between calls. OpenRouter's own docs explain
why: without an explicit `session_id`, sticky routing is derived by hashing the opening
messages, and any drift there (which a growing agent conversation causes constantly)
can land a request on a different backend replica than the one holding the cache. This
is a routing fix, not a prompt-content fix — see experiments/exp5/NOTES.md.

Usage:
    # SWE-bench, self-hosted, one model both roles (original Phase 1 usage):
    python -m orchestrator.run_session \\
        --benchmark swe_bench --instance astropy__astropy-12907 \\
        --model ollama_chat/qwen3.8:27b \\
        --api-base http://<gpu-instance-ip>:<mapped-port> \\
        --output-dir experiments/exp2/results/astropy-12907

    # SWE-bench, hosted API, different model per role:
    OPENROUTER_API_KEY=... python -m orchestrator.run_session \\
        --benchmark swe_bench --instance astropy__astropy-14182 \\
        --gru-model openrouter/deepseek/deepseek-v4-pro-0813 \\
        --minion-model openrouter/deepseek/deepseek-v4-flash-0731 \\
        --output-dir experiments/exp4/results/astropy-14182

    # GAIA (no evaluation pass afterwards — scoring is an inline exact match against the
    # dataset's own "Final answer", see orchestrator/benchmarks/gaia_scorer.py):
    OPENROUTER_API_KEY=... HF_TOKEN=... TAVILY_API_KEY=... python -m orchestrator.run_session \\
        --benchmark gaia --instance c61d22de-5f6c-4958-a7f6-5e9707bd3466 \\
        --gru-model openrouter/z-ai/glm-4.6 \\
        --minion-model openrouter/z-ai/glm-4.5-air \\
        --output-dir experiments/exp6/results/glm-paired/c61d22de
"""

import argparse
import json
import logging
import os
import uuid
from pathlib import Path

# Ollama (and any self-hosted model litellm has no pricing entry for) crashes
# mini-swe-agent's cost calculator otherwise — see experiments/exp1/LOG.md Issues.
os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

# Cache stats ARE captured (they were deliberately skipped for exp2 as a Phase 2
# concern). They stopped being optional once mode="oneshot" landed: it removes history
# resend that prefix caching was already partly absorbing, so a token delta between runs
# is not readable as a cost delta without knowing how much of the old resend was cached.
# See orchestrator/metrics/cache_stats.py and review.md R12/R16.

from orchestrator.benchmarks import get_benchmark  # noqa: E402
from orchestrator.session import build_session, summarize, timed_run  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("run_session")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--benchmark",
        default="swe_bench",
        help="Which benchmark spec to run. A bare name is that benchmark's default spec "
        "(swe_bench -> orchestrator/config/swe_bench/default.yaml); a variant is named with a slash "
        "(swe_bench/solo, gaia/solo -> .../solo.yaml). Any spec file added to a benchmark's config "
        "directory is selectable this way.",
    )
    parser.add_argument("--instance", required=True, help="Instance id within the benchmark (SWE-bench instance_id, GAIA task_id)")
    parser.add_argument("--subset", help="Override the benchmark spec's dataset subset (SWE-bench: lite/verified/...)")
    parser.add_argument("--split", help="Override the benchmark spec's dataset split")
    parser.add_argument("--model", help="litellm model string for BOTH roles (fallback when --gru-model/--minion-model aren't given)")
    parser.add_argument("--gru-model", help="litellm model string for Gru specifically; overrides --model for Gru")
    parser.add_argument("--minion-model", help="litellm model string for the minion specifically; overrides --model for the minion")
    parser.add_argument("--api-base", help="Ollama/OpenAI-compatible API base URL — needed for self-hosted serving, not for a hosted-API model routed by litellm's provider prefix (e.g. openrouter/...)")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gru-config", help="Override the benchmark spec's Gru config, as a path under orchestrator/config/ (e.g. swe_bench/gru-solo.yaml) — for A/B comparisons against an alternate prompt")
    parser.add_argument("--minion-config", help="Override the benchmark spec's minion config, as a path under orchestrator/config/ (e.g. gaia/minion.yaml)")
    parser.add_argument(
        "--cost-limit",
        type=float,
        default=0.0,
        help="Hard dollar cap on Gru's own session (mini-swe-agent's own enforcement, raises LimitsExceeded and "
        "stops the session — real, not advisory). 0 (default) leaves the config's own cost_limit as-is. Does not "
        "cap the minion — see --minion-cost-limit for that.",
    )
    parser.add_argument(
        "--minion-cost-limit",
        type=float,
        default=0.0,
        help="Hard dollar cap on each individual delegation's own agentic-mode session (same mini-swe-agent "
        "enforcement as --cost-limit, applied per delegation, not summed across a session's delegations — exp5's "
        "run 3 showed the minion can end up costing more in aggregate than Gru, and nothing currently caps the "
        "running total across delegations in one Gru session, only each delegation's own spend and Gru's own "
        "step_limit on how many it can issue). 0 (default) leaves the minion config's own cost_limit as-is.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    gru_model_name = args.gru_model or args.model
    minion_model_name = args.minion_model or args.model
    if not gru_model_name or not minion_model_name:
        parser.error("need a model for both roles: pass --model, or both --gru-model and --minion-model")
    model_name = (
        gru_model_name
        if gru_model_name == minion_model_name
        else f"gru={gru_model_name}+minion={minion_model_name}"
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    benchmark = get_benchmark(args.benchmark)
    logger.info(f"Loading {benchmark.name} instance {args.instance}")
    task = benchmark.load_task(args.instance, subset=args.subset, split=args.split)

    # OpenRouter sticky-routing key — unique per run (not just per instance, since the
    # same instance is re-run repeatedly across a day) so two runs never share a pin.
    # See this file's 2026-08-25 revision note.
    run_id = f"{args.instance[:32]}-{uuid.uuid4().hex[:8]}"
    logger.info(f"Run session id: {run_id}")

    logger.info("Starting shared session container")
    shell_env = benchmark.open_environment(task)

    try:
        session = build_session(
            benchmark=benchmark,
            shell_env=shell_env,
            gru_model_name=gru_model_name,
            minion_model_name=minion_model_name,
            api_base=args.api_base,
            gru_config_name=args.gru_config,
            minion_config_name=args.minion_config,
            output_dir=args.output_dir,
            cost_limit=args.cost_limit,
            minion_cost_limit=args.minion_cost_limit,
            run_id=run_id,
        )
        if session.cost_context:
            logger.info(f"Cost context given to Gru:{session.cost_context}")
        else:
            logger.info("No real pricing found for one or both models — cost_context omitted")

        logger.info("Starting Gru session")
        result, start_time, end_time = timed_run(session, task)

        outcome = benchmark.finalize(task=task, result=result, env=session.gru_env, model_name=model_name)
        (args.output_dir / "prediction.json").write_text(
            json.dumps({task.instance_id: outcome.prediction}, indent=2)
        )
        cost_summary = summarize(
            session,
            result=result,
            gru_model_name=gru_model_name,
            minion_model_name=minion_model_name,
            start_time=start_time,
            end_time=end_time,
            extra=outcome.summary_fields,
        )
        (args.output_dir / "cost_summary.json").write_text(json.dumps(cost_summary, indent=2))

        logger.info(
            f"Done in {end_time - start_time:.0f}s. exit_status={cost_summary['exit_status']} "
            f"final_verification_passed={cost_summary['final_verification_passed']} "
            f"gru_calls={session.gru_agent.n_calls} minions={len(session.gru_env.minion_records)}"
        )
        if outcome.log_line:
            logger.info(outcome.log_line)

    finally:
        logger.info("Cleaning up shared session container")
        shell_env.cleanup()


if __name__ == "__main__":
    main()
