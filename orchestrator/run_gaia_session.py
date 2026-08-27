#!/usr/bin/env python3
"""Run the Gru/minion architecture on a single GAIA instance. Sibling of
run_gru_session.py (SWE-bench) — same CLI shape, same GruModel/gru_toolcall/
gru_config (unchanged imports, not GAIA-specific copies — see
orchestrator/gaia_environment.py's module docstring for why: one architecture, one
prompt, only the benchmark underneath changes), pointed at orchestrator.gaia_environment
instead of orchestrator.gru_environment.

No swebench.harness evaluation step needed after the run: GAIA scoring is an inline
exact-match against the dataset's own "Final answer" field (orchestrator.gaia_scorer),
not a separate hidden test suite run in a second pass.

Usage:
    OPENROUTER_API_KEY=... HF_TOKEN=... TAVILY_API_KEY=... python -m orchestrator.run_gaia_session \\
        --task-id c61d22de-5f6c-4958-a7f6-5e9707bd3466 \\
        --gru-model openrouter/z-ai/glm-4.6 \\
        --minion-model openrouter/z-ai/glm-4.5-air \\
        --output-dir experiments/exp6/results/glm-paired/c61d22de
"""

import argparse
import json
import logging
import os
import time
import uuid
from pathlib import Path

import yaml

os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

from minisweagent.agents.default import DefaultAgent  # noqa: E402
from minisweagent.environments.docker import DockerEnvironment  # noqa: E402

from orchestrator.cache_stats import extract_cache_stats, merge_cache_stats  # noqa: E402
from orchestrator.cost_context import describe_cost_ratio  # noqa: E402
from orchestrator.gru_config import load_gru_config  # noqa: E402
from orchestrator.gru_model import GruModel  # noqa: E402
from orchestrator.gaia_dataset import load_gaia  # noqa: E402
from orchestrator.gaia_environment import GaiaEnvironment  # noqa: E402
from orchestrator.gaia_scorer import question_scorer  # noqa: E402
from orchestrator.token_usage import extract_token_usage  # noqa: E402

CONFIG_DIR = Path(__file__).parent / "config"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("run_gaia_session")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", default="validation")
    parser.add_argument("--task-id", required=True, help="GAIA task_id")
    parser.add_argument("--model", help="litellm model string for BOTH roles")
    parser.add_argument("--gru-model", help="litellm model string for Gru specifically")
    parser.add_argument("--minion-model", help="litellm model string for the minion specifically")
    parser.add_argument("--api-base", help="Ollama/OpenAI-compatible API base URL — not needed for openrouter/...")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gru-config", default="gaia.yaml", help="Config filename under orchestrator/config/")
    parser.add_argument("--cost-limit", type=float, default=0.0)
    parser.add_argument("--minion-cost-limit", type=float, default=0.0)
    args = parser.parse_args()

    gru_model_name = args.gru_model or args.model
    minion_model_name = args.minion_model or args.model
    if not gru_model_name or not minion_model_name:
        parser.error("need a model for both roles: pass --model, or both --gru-model and --minion-model")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Loading GAIA {args.split}, task {args.task_id}")
    ds = load_gaia(split=args.split)
    instances = {r["task_id"]: r for r in ds}
    instance = instances[args.task_id]
    if instance["file_name"]:
        logger.warning(
            f"task {args.task_id} has an attached file ({instance['file_name']!r}) — this pilot's toolset "
            "(a bash-capable sandbox with no file/image/audio parsing library wired to a tool) cannot use it; "
            "expect this run to fail on that basis alone."
        )

    session_config = load_yaml(CONFIG_DIR / "gaia-session.yaml")
    gru_config = load_gru_config(args.gru_config)
    logger.info(f"Using Gru config: {args.gru_config}")
    minion_config = load_yaml(CONFIG_DIR / "gaia-minion.yaml")

    run_id = f"{args.task_id[:8]}-{uuid.uuid4().hex[:8]}"
    logger.info(f"Run session id: {run_id}")

    logger.info("Starting shared sandbox container")
    docker_env = DockerEnvironment(**session_config["environment"])

    try:
        gru_model = GruModel(
            model_name=gru_model_name,
            model_kwargs={**gru_config["model"]["model_kwargs"], **({"api_base": args.api_base} if args.api_base else {})},
            policy=gru_config["tool_policy"],
            run_id=run_id,
        )
        minion_model_kwargs = {
            "model_name": minion_model_name,
            "model_kwargs": {**minion_config["model"]["model_kwargs"], **({"api_base": args.api_base} if args.api_base else {})},
        }
        minion_agent_kwargs = {
            k: v for k, v in minion_config["agent"].items() if k not in ("system_template", "instance_template")
        }
        if args.minion_cost_limit > 0:
            minion_agent_kwargs["cost_limit"] = args.minion_cost_limit

        gaia_env = GaiaEnvironment(
            docker_env=docker_env,
            minion_model_kwargs=minion_model_kwargs,
            minion_agent_kwargs=minion_agent_kwargs,
            minion_system_template=minion_config["agent"]["system_template"],
            minion_instance_template=minion_config["agent"]["instance_template"],
            output_dir=args.output_dir,
            logger=logging.getLogger("gaia.environment"),
            run_id=run_id,
        )

        gru_agent_kwargs = {
            k: v for k, v in gru_config["agent"].items() if k not in ("system_template", "instance_template")
        }
        if args.cost_limit > 0:
            gru_agent_kwargs["cost_limit"] = args.cost_limit
        gru_agent = DefaultAgent(
            gru_model,
            gaia_env,
            system_template=gru_config["agent"]["system_template"],
            instance_template=gru_config["agent"]["instance_template"],
            output_path=args.output_dir / "gru.traj.json",
            **gru_agent_kwargs,
        )
        gaia_env.gru_agent = gru_agent

        cost_context = describe_cost_ratio(gru_model_name, minion_model_name)
        if cost_context:
            logger.info(f"Cost context given to Gru:{cost_context}")

        logger.info("Starting Gru session")
        start_time = time.time()
        try:
            result = gru_agent.run(task_description=instance["Question"], cost_context=cost_context)
        except Exception as e:
            logger.warning(f"Gru session raised {type(e).__name__}: {e}")
            result = {"submission": "", "exit_status": f"Crashed:{type(e).__name__}"}
        end_time = time.time()

        answer = result.get("submission", "") or gaia_env.final_answer or ""
        exit_status = result.get("exit_status", "")
        gold_answer = instance["Final answer"]
        resolved = question_scorer(answer, gold_answer) if answer else False

        prediction = {
            args.task_id: {
                "model_name_or_path": gru_model_name if gru_model_name == minion_model_name else f"gru={gru_model_name}+minion={minion_model_name}",
                "task_id": args.task_id,
                "question": instance["Question"],
                "level": instance["Level"],
                "answer": answer,
                "gold_answer": gold_answer,
                "resolved": resolved,
                "exit_status": exit_status,
            }
        }
        (args.output_dir / "prediction.json").write_text(json.dumps(prediction, indent=2))

        gru_tokens = extract_token_usage(gru_agent.messages)
        minions_tokens = {
            "prompt_tokens": sum(m["prompt_tokens"] for m in gaia_env.minion_records),
            "completion_tokens": sum(m["completion_tokens"] for m in gaia_env.minion_records),
            "total_tokens": sum(m["total_tokens"] for m in gaia_env.minion_records),
        }
        cost_summary = {
            "task_id": args.task_id,
            "gru_model": gru_model_name,
            "minion_model": minion_model_name,
            "start_time": start_time,
            "end_time": end_time,
            "wall_clock_seconds": end_time - start_time,
            "exit_status": exit_status,
            "answer": answer,
            "gold_answer": gold_answer,
            "resolved": resolved,
            "gru_action_log": gaia_env.gru_action_log,
            "gru": {
                "api_calls": gru_agent.n_calls,
                "cost": gru_agent.cost,
                **gru_tokens,
                "cache": extract_cache_stats(gru_agent.messages),
            },
            "minions": gaia_env.minion_records,
            "minions_total": {
                "count": len(gaia_env.minion_records),
                "api_calls": sum(m["api_calls"] for m in gaia_env.minion_records),
                **minions_tokens,
            },
            "cache_totals": merge_cache_stats(
                [extract_cache_stats(gru_agent.messages)]
                + [m["cache"] for m in gaia_env.minion_records if m.get("cache")]
            ),
        }
        (args.output_dir / "cost_summary.json").write_text(json.dumps(cost_summary, indent=2))

        logger.info(
            f"Done in {end_time - start_time:.0f}s. exit_status={exit_status} "
            f"resolved={resolved} answer={answer!r} gold={gold_answer!r} "
            f"gru_calls={gru_agent.n_calls} minions={len(gaia_env.minion_records)}"
        )

    finally:
        logger.info("Cleaning up shared sandbox container")
        docker_env.cleanup()


if __name__ == "__main__":
    main()
