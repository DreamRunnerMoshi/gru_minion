"""Assembles one Gru session and reports what it cost.

This is the wiring that used to be copy-pasted between run_gru_session.py,
run_gaia_session.py and both test harnesses: build Gru's model, build the minion runner,
build the benchmark's Gru environment, hand all three to mini-swe-agent's DefaultAgent,
and — afterwards — flatten the per-role token/cost/cache accounting into one summary. It
is deliberately free of both argparse and Docker: the CLI (run_session.py) owns those,
and the tests hand it a LocalEnvironment and a scripted model instead.
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent

from orchestrator.benchmarks.base import Benchmark, Task
from orchestrator.configs import load_yaml
from orchestrator.gru.config import load_gru_config
from orchestrator.gru.environment import GruEnvironment
from orchestrator.gru.model import GruModel
from orchestrator.metrics.cache_stats import extract_cache_stats, merge_cache_stats
from orchestrator.metrics.cost_context import describe_cost_ratio
from orchestrator.metrics.token_usage import extract_token_usage
from orchestrator.minion.runner import MinionRunner

logger = logging.getLogger("gru.session")


@dataclass
class Session:
    benchmark: Benchmark
    gru_model: GruModel
    gru_env: GruEnvironment
    gru_agent: DefaultAgent
    cost_context: str


def build_session(
    *,
    benchmark: Benchmark,
    shell_env: Any,
    gru_model_name: str,
    minion_model_name: str,
    api_base: str | None = None,
    gru_config_name: str | None = None,
    minion_config_name: str | None = None,
    output_dir: Path | None = None,
    cost_limit: float = 0.0,
    minion_cost_limit: float = 0.0,
    run_id: str = "test-session",
) -> Session:
    """`shell_env` is the one shared container (or, in tests, LocalEnvironment) that Gru's
    checks and every delegation run against. The config names default to the benchmark
    spec's; passing them explicitly is how an A/B against an alternate prompt is run."""
    gru_config = load_gru_config(gru_config_name or benchmark.spec.gru)
    minion_config = load_yaml(minion_config_name or benchmark.spec.minion)

    gru_model = GruModel(
        model_name=gru_model_name,
        model_kwargs={**gru_config["model"]["model_kwargs"], **({"api_base": api_base} if api_base else {})},
        policy=gru_config["tool_policy"],
        run_id=run_id,
    )
    minions = MinionRunner.from_config(
        minion_config,
        env=shell_env,
        model_name=minion_model_name,
        api_base=api_base,
        cost_limit=minion_cost_limit,
        output_dir=output_dir,
        run_id=run_id,
    )
    gru_env = benchmark.make_gru_environment(
        env=shell_env,
        minions=minions,
        output_dir=output_dir,
        logger=logging.getLogger(f"{benchmark.spec.benchmark}.environment"),
        run_id=run_id,
    )

    gru_agent_kwargs = {k: v for k, v in gru_config["agent"].items() if k not in ("system_template", "instance_template")}
    if cost_limit > 0:
        gru_agent_kwargs["cost_limit"] = cost_limit
    gru_agent = DefaultAgent(
        gru_model,
        gru_env,
        system_template=gru_config["agent"]["system_template"],
        instance_template=gru_config["agent"]["instance_template"],
        output_path=(output_dir / "gru.traj.json") if output_dir else None,
        **gru_agent_kwargs,
    )
    # Can only be wired after construction — gru_env._turn_cost_line() needs it to
    # surface each turn's own token cost, not just delegations' (see gru/environment.py).
    gru_env.gru_agent = gru_agent

    return Session(
        benchmark=benchmark,
        gru_model=gru_model,
        gru_env=gru_env,
        gru_agent=gru_agent,
        cost_context=describe_cost_ratio(gru_model_name, minion_model_name),
    )


def run_task(session: Session, task: Task) -> dict[str, Any]:
    """Run one task to completion. An uncaught exception (e.g. litellm exhausting retries)
    must not lose the session the way a bare crash would: gru_agent.messages/n_calls/cost
    are updated incrementally through the loop, so they still reflect real work up to the
    crash, and the shared container still holds whatever the last passing delegation left
    there. Route it through the same not-Submitted path the benchmark's finalize() already
    handles rather than propagating."""
    try:
        return session.gru_agent.run(**task.prompt_vars, cost_context=session.cost_context)
    except Exception as e:
        logger.warning(f"Gru session raised {type(e).__name__}: {e}")
        return {"submission": "", "exit_status": f"Crashed:{type(e).__name__}"}


def summarize(
    session: Session,
    *,
    result: dict,
    gru_model_name: str,
    minion_model_name: str,
    start_time: float,
    end_time: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Per-role cost accounting for one finished session (see prompts/README.md "Cost
    attribution"). `extra` is the benchmark's own half — an instance id, or an answer and
    whether it scored."""
    agent, env = session.gru_agent, session.gru_env
    gru_cache = extract_cache_stats(agent.messages)
    return {
        **(extra or {}),
        "gru_model": gru_model_name,
        "minion_model": minion_model_name,
        "start_time": start_time,
        "end_time": end_time,
        "wall_clock_seconds": end_time - start_time,
        "exit_status": result.get("exit_status", ""),
        # Whether Gru's own self-authored final_verification (necessarily blind to the real
        # hidden tests, see prompts/gru-loop.md) at least agreed with itself. The real
        # verdict still comes from the benchmark's own scoring; comparing the two after the
        # fact is the actual measurement of how good Gru's proxy check is.
        "final_verification_passed": result.get("final_verification_passed"),
        "final_verification_output": result.get("final_verification_output", ""),
        # Every Gru action in order — needed to count think/run_check turns and to see the
        # delegate-vs-decide choice, which is the thing this project is actually measuring.
        "gru_action_log": env.gru_action_log,
        "gru": {
            "api_calls": agent.n_calls,
            "cost": agent.cost,
            **extract_token_usage(agent.messages),
            "cache": gru_cache,
        },
        "minions": env.minion_records,
        "minions_total": {
            "count": len(env.minion_records),
            "api_calls": sum(m["api_calls"] for m in env.minion_records),
            "prompt_tokens": sum(m["prompt_tokens"] for m in env.minion_records),
            "completion_tokens": sum(m["completion_tokens"] for m in env.minion_records),
            "total_tokens": sum(m["total_tokens"] for m in env.minion_records),
        },
        "cache_totals": merge_cache_stats(
            [gru_cache] + [m["cache"] for m in env.minion_records if m.get("cache")]
        ),
    }


def timed_run(session: Session, task: Task) -> tuple[dict[str, Any], float, float]:
    """run_task plus the wall-clock bracket every cost summary records."""
    start = time.time()
    result = run_task(session, task)
    return result, start, time.time()
