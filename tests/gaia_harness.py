"""GAIA sibling of tests/harness.py — same wiring (GaiaModel + GaiaEnvironment +
DefaultAgent, a ScriptedLLM instead of a real model), swapped to LocalEnvironment
instead of Docker (no sandbox image needed for these tests) and a scratch directory
instead of a git repo (GAIA has no repository to check out). GaiaEnvironment's
websearch_path is pointed at a fake local script instead of the real image's
/usr/local/bin/websearch.py, so a scripted web_search resolves to deterministic canned
output instead of a real Tavily call — see make_scratch_dir.
"""

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
from orchestrator.gaia_config import load_gaia_config
from orchestrator.gaia_environment import GaiaEnvironment
from orchestrator.gaia_model import GaiaModel
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
    """A plain scratch directory, plus a separate dir holding a fake websearch.py —
    GaiaEnvironment's `websearch_path` param (see gaia_environment.py) points at this
    instead of the real image's /usr/local/bin/websearch.py, so a scripted web_search
    resolves to deterministic canned output with no real network call."""
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
    env = ScratchEnvironment(cwd=str(workdir))

    gaia_cfg = load_gaia_config(gru_config)
    minion_cfg = load_yaml("gaia-minion.yaml")

    llm = ScriptedLLM(steps)
    with patch("litellm.completion", llm):
        gru_model = GaiaModel(
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
            websearch_path=str(bin_dir / "websearch.py"),
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
