"""GAIA sibling of tests/harness.py — same wiring (GruModel + gru_config, a ScriptedLLM
instead of a real model), swapped to LocalEnvironment instead of Docker (no sandbox
image needed for these tests) and a scratch directory instead of a git repo (GAIA has
no repository to check out). Deliberately reuses GruModel/load_gru_config UNCHANGED,
not a GAIA-specific model/config class — see orchestrator/gaia_environment.py's module
docstring: one architecture, one prompt, only the benchmark underneath changes.

A fake `websearch.py` is dropped into a bin/ dir under tmp_path so a scripted
`run_check` that shells out to it (exactly as the real gaia-sandbox image's run_check
calls would) resolves to deterministic canned output instead of a real Tavily call.
"""

import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment

from orchestrator.cost_context import describe_cost_ratio
from orchestrator.gru_config import load_gru_config
from orchestrator.gaia_environment import GaiaEnvironment
from orchestrator.gru_model import GruModel
from tests.mock_llm import ScriptedLLM, Step

CONFIG_DIR = Path(__file__).parent.parent / "orchestrator" / "config"

_FAKE_WEBSEARCH = """#!/usr/bin/env python3
import json, sys
print(json.dumps({"query": " ".join(sys.argv[1:]), "results": [
    {"title": "Fake result", "url": "https://example.com/fake", "snippet": "canned test snippet"}
]}))
"""


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())


class ScratchEnvironment(LocalEnvironment):
    def cleanup(self) -> None:
        pass


def make_scratch_dir(tmp_path: Path) -> tuple[Path, Path]:
    """A plain scratch directory, plus a bin/ dir on a fake websearch.py — the real
    gaia-sandbox image has this at /usr/local/bin/websearch.py; a scripted run_check
    here points at the tmp_path copy instead via PATH, so `run_check` calling
    `websearch.py ...` (not the absolute path) resolves without a real Tavily call."""
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "websearch.py"
    script.write_text(_FAKE_WEBSEARCH)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return workdir, bin_dir


@dataclass
class Session:
    result: dict[str, Any]
    gru_agent: DefaultAgent
    gaia_env: GaiaEnvironment
    llm: ScriptedLLM
    workdir: Path


def run_session(
    *,
    tmp_path: Path,
    steps: list[Step],
    task_description: str = "What is 2 + 2?",
    gru_config: str = "gaia.yaml",
    output_dir: Path | None = None,
) -> Session:
    workdir, bin_dir = make_scratch_dir(tmp_path)
    env = ScratchEnvironment(cwd=str(workdir), env={"PATH": f"{bin_dir}:" + os.environ.get("PATH", "")})

    gaia_cfg = load_gru_config(gru_config)
    minion_cfg = load_yaml("gaia-minion.yaml")

    llm = ScriptedLLM(steps)
    with patch("litellm.completion", llm):
        gru_model = GruModel(
            model_name="mock/gru", model_kwargs=gaia_cfg["model"]["model_kwargs"], policy=gaia_cfg["tool_policy"]
        )
        minion_model_kwargs = {"model_name": "mock/minion", "model_kwargs": minion_cfg["model"]["model_kwargs"]}
        minion_agent_kwargs = {
            k: v for k, v in minion_cfg["agent"].items() if k not in ("system_template", "instance_template")
        }
        gaia_env = GaiaEnvironment(
            docker_env=env,
            minion_model_kwargs=minion_model_kwargs,
            minion_agent_kwargs=minion_agent_kwargs,
            minion_system_template=minion_cfg["agent"]["system_template"],
            minion_instance_template=minion_cfg["agent"]["instance_template"],
            output_dir=output_dir,
        )
        gru_agent_kwargs = {
            k: v for k, v in gaia_cfg["agent"].items() if k not in ("system_template", "instance_template")
        }
        gru_agent = DefaultAgent(
            gru_model,
            gaia_env,
            system_template=gaia_cfg["agent"]["system_template"],
            instance_template=gaia_cfg["agent"]["instance_template"],
            output_path=(output_dir / "gru.traj.json") if output_dir else None,
            **gru_agent_kwargs,
        )
        gaia_env.gru_agent = gru_agent

        start = time.time()
        try:
            result = gru_agent.run(
                task_description=task_description,
                cost_context=describe_cost_ratio("mock/gru", "mock/minion"),
            )
        except Exception as e:
            result = {"submission": "", "exit_status": f"Crashed:{type(e).__name__}:{e}"}
        result.setdefault("_wall_clock", time.time() - start)

    return Session(result=result, gru_agent=gru_agent, gaia_env=gaia_env, llm=llm, workdir=workdir)
