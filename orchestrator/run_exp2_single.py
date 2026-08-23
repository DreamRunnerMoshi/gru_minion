#!/usr/bin/env python3
"""Run the Gru/minion architecture on a single SWE-bench instance.

Same model for both roles for this experiment (Phase 1 framework validation,
see design/infra/04-machine-config.md and memory project-machine-config) — using
the same model Gru/minion isolates the architecture's effect from model-capability
differences, directly comparable against exp1's solo-minion baseline on the same
instances.

Usage:
    python -m orchestrator.run_exp2_single \\
        --instance astropy__astropy-12907 \\
        --model ollama_chat/qwen3.8:27b \\
        --api-base http://<gpu-instance-ip>:<mapped-port> \\
        --output-dir experiments/exp2/results/astropy-12907
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

# NOTE: cache-hit stats (EXPERIMENT_LOG_FORMAT.md asks to capture these live) are
# deliberately NOT captured here. Decision 2026-08-21: exp2's own question (does the
# Gru/minion architecture preserve resolve rate vs. exp1's solo minion) doesn't need
# cache-hit rate — that's a Phase 2 cost-comparison concern. Building live capture
# (harness VM polling/tailing the GPU instance's Ollama logs mid-session) was judged
# real extra engineering not justified for this run. If curious, keep the GPU
# instance alive briefly after the run and spot-check ollama.log manually, same as
# exp1 did — but that's a manual step, not something this script does.

from minisweagent.run.benchmarks.swebench import DATASET_MAPPING, get_sb_environment  # noqa: E402

from orchestrator.gru_environment import GruEnvironment  # noqa: E402
from orchestrator.gru_model import GruModel  # noqa: E402
from orchestrator.token_usage import extract_token_usage  # noqa: E402
from minisweagent.agents.default import DefaultAgent  # noqa: E402

CONFIG_DIR = Path(__file__).parent / "config"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("run_exp2_single")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--subset", default="lite", help="SWE-bench subset (lite/verified/...)")
    parser.add_argument("--split", default="test")
    parser.add_argument("--instance", required=True, help="SWE-bench instance_id")
    parser.add_argument("--model", required=True, help="litellm model string, used for BOTH Gru and minion")
    parser.add_argument("--api-base", required=True, help="Ollama/OpenAI-compatible API base URL")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gru-config", default="gru.yaml", help="Config filename under orchestrator/config/ for Gru's prompt (for A/B comparisons against an alternate prompt)")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading {args.subset}/{args.split}, instance {args.instance}")
    dataset_path = DATASET_MAPPING.get(args.subset, args.subset)
    instances = {inst["instance_id"]: inst for inst in load_dataset(dataset_path, split=args.split)}
    instance = instances[args.instance]

    session_config = load_yaml(CONFIG_DIR / "session.yaml")
    gru_config = load_yaml(CONFIG_DIR / args.gru_config)
    logger.info(f"Using Gru config: {args.gru_config}")
    minion_config = load_yaml(CONFIG_DIR / "minion.yaml")

    logger.info("Starting shared testbed container")
    docker_env = get_sb_environment(session_config, instance)

    try:
        gru_model = GruModel(
            model_name=args.model,
            model_kwargs={**gru_config["model"]["model_kwargs"], "api_base": args.api_base},
        )
        minion_model_kwargs = {
            "model_name": args.model,
            "model_kwargs": {**minion_config["model"]["model_kwargs"], "api_base": args.api_base},
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

        logger.info("Starting Gru session")
        start_time = time.time()
        result = gru_agent.run(
            task_description=instance["problem_statement"],
            repo_name=instance.get("repo", ""),
            repo_path_or_access_instructions=session_config["environment"]["cwd"],
        )
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
                "model_name_or_path": args.model,
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
            "model": args.model,
            "start_time": start_time,
            "end_time": end_time,
            "wall_clock_seconds": end_time - start_time,
            "exit_status": exit_status,
            "final_verification_passed": final_verification_passed,
            "final_verification_output": final_verification_output,
            "gru": {"api_calls": gru_agent.n_calls, "cost": gru_agent.cost, **gru_tokens},
            "minions": gru_env.minion_records,
            "minions_total": {
                "count": len(gru_env.minion_records),
                "api_calls": sum(m["api_calls"] for m in gru_env.minion_records),
                "cost": sum(m["cost"] for m in gru_env.minion_records),
                **minions_tokens,
            },
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
