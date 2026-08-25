#!/usr/bin/env python3
"""Run the Gru/minion architecture on a single SWE-bench instance.

Renamed 2026-08-24 from run_exp2_single.py (git history preserved via `git mv`): it was
written for exp2 (the first experiment to introduce Gru/minion, vs. exp0/exp1's
solo-minion) but is generic per-instance orchestration — exp3's arm B, its diagnostic
runs, and any future orchestrator/config/gru-*.yaml variant all reuse it unchanged, so
the exp2-specific name was a misnomer.

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

Usage:
    # self-hosted, one model both roles (original Phase 1 usage):
    python -m orchestrator.run_gru_session \\
        --instance astropy__astropy-12907 \\
        --model ollama_chat/qwen3.8:27b \\
        --api-base http://<gpu-instance-ip>:<mapped-port> \\
        --output-dir experiments/exp2/results/astropy-12907

    # hosted API, different model per role:
    OPENROUTER_API_KEY=... python -m orchestrator.run_gru_session \\
        --instance astropy__astropy-14182 \\
        --gru-model openrouter/deepseek/deepseek-v4-pro-0813 \\
        --minion-model openrouter/deepseek/deepseek-v4-flash-0731 \\
        --output-dir experiments/exp4/results/astropy-14182
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml
from datasets import load_dataset

# Ollama (and any self-hosted model litellm has no pricing entry for) crashes
# mini-swe-agent's cost calculator otherwise — see experiments/exp1/LOG.md Issues.
os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

# Cache stats ARE captured now (they were deliberately skipped for exp2 as a Phase 2
# concern). They stopped being optional once mode="oneshot" landed: it removes history
# resend that prefix caching was already partly absorbing, so a token delta between runs
# is not readable as a cost delta without knowing how much of the old resend was cached.
# See orchestrator/cache_stats.py and review.md R12/R16.

from minisweagent.run.benchmarks.swebench import DATASET_MAPPING, get_sb_environment  # noqa: E402

from orchestrator.gru_environment import GruEnvironment  # noqa: E402
from orchestrator.gru_model import GruModel  # noqa: E402
from orchestrator.gru_config import load_gru_config  # noqa: E402
from orchestrator.cost_context import describe_cost_ratio  # noqa: E402
from orchestrator.cache_stats import extract_cache_stats, merge_cache_stats  # noqa: E402
from orchestrator.token_usage import extract_token_usage  # noqa: E402
from minisweagent.agents.default import DefaultAgent  # noqa: E402

CONFIG_DIR = Path(__file__).parent / "config"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("run_gru_session")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subset", default="lite", help="SWE-bench subset (lite/verified/...)")
    parser.add_argument("--split", default="test")
    parser.add_argument("--instance", required=True, help="SWE-bench instance_id")
    parser.add_argument("--model", help="litellm model string for BOTH roles (fallback when --gru-model/--minion-model aren't given)")
    parser.add_argument("--gru-model", help="litellm model string for Gru specifically; overrides --model for Gru")
    parser.add_argument("--minion-model", help="litellm model string for the minion specifically; overrides --model for the minion")
    parser.add_argument("--api-base", help="Ollama/OpenAI-compatible API base URL — needed for self-hosted serving, not for a hosted-API model routed by litellm's provider prefix (e.g. openrouter/...)")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gru-config", default="gru.yaml", help="Config filename under orchestrator/config/ for Gru's prompt (for A/B comparisons against an alternate prompt)")
    args = parser.parse_args()

    gru_model_name = args.gru_model or args.model
    minion_model_name = args.minion_model or args.model
    if not gru_model_name or not minion_model_name:
        parser.error("need a model for both roles: pass --model, or both --gru-model and --minion-model")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading {args.subset}/{args.split}, instance {args.instance}")
    dataset_path = DATASET_MAPPING.get(args.subset, args.subset)
    instances = {inst["instance_id"]: inst for inst in load_dataset(dataset_path, split=args.split)}
    instance = instances[args.instance]

    session_config = load_yaml(CONFIG_DIR / "session.yaml")
    gru_config = load_gru_config(args.gru_config)
    logger.info(f"Using Gru config: {args.gru_config}")
    minion_config = load_yaml(CONFIG_DIR / "minion.yaml")

    logger.info("Starting shared testbed container")
    docker_env = get_sb_environment(session_config, instance)

    try:
        gru_model = GruModel(
            model_name=gru_model_name,
            model_kwargs={**gru_config["model"]["model_kwargs"], **({"api_base": args.api_base} if args.api_base else {})},
            policy=gru_config["tool_policy"],
        )
        minion_model_kwargs = {
            "model_name": minion_model_name,
            "model_kwargs": {**minion_config["model"]["model_kwargs"], **({"api_base": args.api_base} if args.api_base else {})},
        }
        minion_agent_kwargs = {
            k: v for k, v in minion_config["agent"].items() if k not in ("system_template", "instance_template")
        }

        gru_env = GruEnvironment(
            docker_env=docker_env,
            minion_model_kwargs=minion_model_kwargs,
            minion_agent_kwargs=minion_agent_kwargs,
            minion_system_template=minion_config["agent"]["system_template"],
            minion_instance_template=minion_config["agent"]["instance_template"],
            output_dir=args.output_dir,
            logger=logging.getLogger("gru.environment"),
        )

        gru_agent_kwargs = {
            k: v for k, v in gru_config["agent"].items() if k not in ("system_template", "instance_template")
        }
        gru_agent = DefaultAgent(
            gru_model,
            gru_env,
            system_template=gru_config["agent"]["system_template"],
            instance_template=gru_config["agent"]["instance_template"],
            output_path=args.output_dir / "gru.traj.json",
            **gru_agent_kwargs,
        )
        # Can only be wired after construction — gru_env._turn_cost_line() needs it to
        # surface each turn's own token cost, not just delegations' (see gru_environment.py).
        gru_env.gru_agent = gru_agent

        cost_context = describe_cost_ratio(gru_model_name, minion_model_name)
        if cost_context:
            logger.info(f"Cost context given to Gru:{cost_context}")
        else:
            logger.info("No real pricing found for one or both models — cost_context omitted")

        logger.info("Starting Gru session")
        start_time = time.time()
        try:
            result = gru_agent.run(
                task_description=instance["problem_statement"],
                repo_name=instance.get("repo", ""),
                repo_path_or_access_instructions=session_config["environment"]["cwd"],
                cost_context=cost_context,
            )
        except Exception as e:
            # An uncaught exception (e.g. litellm exhausting retries) must not lose the
            # session the way a bare crash would: gru_agent.messages/n_calls/cost are
            # updated incrementally through the loop, so they still reflect real work up
            # to the crash, and the testbed's working tree still has whatever the last
            # passing delegation left there. Route through the same not-Submitted fallback
            # below rather than duplicating it.
            logger.warning(f"Gru session raised {type(e).__name__}: {e}")
            result = {"submission": "", "exit_status": f"Crashed:{type(e).__name__}"}
        end_time = time.time()

        patch = result.get("submission", "")
        exit_status = result.get("exit_status", "")
        # Fallback: if the session ended any way other than a clean Submitted (e.g.
        # RepeatedFormatError from Gru writing prose instead of calling finish after
        # a real pass), the minions' actual work still sits in the shared testbed's
        # working tree — pull it via git diff directly rather than losing it. Found
        # the hard way: a run where every delegation succeeded still produced a
        # 0-char patch because Gru never phrased a valid finish() call.
        if not patch and exit_status != "Submitted":
            logger.warning(f"Session ended via {exit_status!r}, not Submitted — falling back to git diff on the shared testbed")
            fallback_diff = docker_env.execute({"command": "git diff"})
            patch = fallback_diff.get("output", "")
            logger.info(f"Fallback git diff recovered {len(patch)} chars")
        # Whether Gru's own self-authored final_verification (necessarily blind to the
        # real hidden FAIL_TO_PASS/PASS_TO_PASS, see prompts/gru-loop.md) agreed with
        # itself at least — the real verdict still only comes from run_evaluation on
        # prediction.json below, same as exp0/exp1. Comparing the two after evaluation
        # is the actual measurement of how good Gru's proxy check is.
        final_verification_passed = result.get("final_verification_passed")
        final_verification_output = result.get("final_verification_output", "")

        prediction = {
            args.instance: {
                "model_name_or_path": gru_model_name if gru_model_name == minion_model_name else f"gru={gru_model_name}+minion={minion_model_name}",
                "instance_id": args.instance,
                "model_patch": patch,
            }
        }
        (args.output_dir / "prediction.json").write_text(json.dumps(prediction, indent=2))

        gru_tokens = extract_token_usage(gru_agent.messages)
        minions_tokens = {
            "prompt_tokens": sum(m["prompt_tokens"] for m in gru_env.minion_records),
            "completion_tokens": sum(m["completion_tokens"] for m in gru_env.minion_records),
            "total_tokens": sum(m["total_tokens"] for m in gru_env.minion_records),
        }
        cost_summary = {
            "instance_id": args.instance,
            "gru_model": gru_model_name,
            "minion_model": minion_model_name,
            "start_time": start_time,
            "end_time": end_time,
            "wall_clock_seconds": end_time - start_time,
            "exit_status": exit_status,
            "final_verification_passed": final_verification_passed,
            "final_verification_output": final_verification_output,
            # Every Gru action in order — needed to count think/run_check turns and to see
            # the delegate-vs-decide choice, which is the thing exp3 is actually measuring.
            "gru_action_log": gru_env.gru_action_log,
            "gru": {
                "api_calls": gru_agent.n_calls,
                "cost": gru_agent.cost,
                **gru_tokens,
                "cache": extract_cache_stats(gru_agent.messages),
            },
            "minions": gru_env.minion_records,
            "minions_total": {
                "count": len(gru_env.minion_records),
                "api_calls": sum(m["api_calls"] for m in gru_env.minion_records),
                **minions_tokens,
            },
            "cache_totals": merge_cache_stats(
                [extract_cache_stats(gru_agent.messages)]
                + [m["cache"] for m in gru_env.minion_records if m.get("cache")]
            ),
        }
        (args.output_dir / "cost_summary.json").write_text(json.dumps(cost_summary, indent=2))

        logger.info(
            f"Done in {end_time - start_time:.0f}s. exit_status={exit_status} "
            f"final_verification_passed={final_verification_passed} "
            f"gru_calls={gru_agent.n_calls} minions={len(gru_env.minion_records)}"
        )
        logger.info(f"Patch length: {len(patch)} chars")

    finally:
        logger.info("Cleaning up shared testbed container")
        docker_env.cleanup()


if __name__ == "__main__":
    main()
