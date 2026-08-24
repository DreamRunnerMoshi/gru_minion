"""Wires up one Gru session against a disposable local git repo instead of a real
SWE-bench Docker container, and against a ScriptedLLM instead of real Ollama. This is
the same wiring orchestrator/run_gru_session.py does (GruModel + GruEnvironment +
DefaultAgent), minus the SWE-bench dataset load and Docker container — those are the
two things that cost real time/infra and aren't what's under test when the question is
"does the harness's own control flow do the right thing."

Swapping DockerEnvironment for mini-swe-agent's own LocalEnvironment is not a stand-in
implementation: it is the library's other supported environment, running real shell
commands (git, sed, cat, ...) against a real (temporary, disposable) directory — so
run_check's write-rejection, the minion's actual bash tool loop, and `git diff` patch
extraction are all exercised for real. Only the model call is fake.
"""

import subprocess
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
from orchestrator.gru_environment import GruEnvironment
from orchestrator.gru_model import GruModel
from tests.mock_llm import ScriptedLLM, Step

CONFIG_DIR = Path(__file__).parent.parent / "orchestrator" / "config"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())


class ScratchEnvironment(LocalEnvironment):
    """LocalEnvironment plus the no-op `cleanup()` GruEnvironment's caller expects from
    a DockerEnvironment-shaped object; nothing to tear down for a plain directory."""

    def cleanup(self) -> None:
        pass


def make_scratch_repo(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """A real git repo with an initial commit, so `git diff` (finish()'s patch source)
    and file-editing commands behave exactly as they do against the real testbed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for relpath, content in (files or {"README.md": "placeholder\n"}).items():
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    run = lambda *args: subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)  # noqa: E731
    run("git", "init", "-q")
    run("git", "config", "user.email", "test@example.com")
    run("git", "config", "user.name", "test")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "initial")
    return repo


@dataclass
class Session:
    result: dict[str, Any]
    gru_agent: DefaultAgent
    gru_env: GruEnvironment
    llm: ScriptedLLM
    repo: Path


def run_session(
    *,
    tmp_path: Path,
    steps: list[Step],
    task_description: str = "Fix the bug described in the task.",
    repo_files: dict[str, str] | None = None,
    gru_config: str = "gru.yaml",
    output_dir: Path | None = None,
) -> Session:
    """Runs one full Gru session (real config, real prompts, real DefaultAgent loop)
    against a scratch repo and a scripted model, and returns everything a test would
    want to inspect: the DefaultAgent's own result dict (exit_status/submission), the
    trajectory, the GruEnvironment (minion_records, gru_action_log), and the raw
    ScriptedLLM (every call it received, for asserting on what the model was actually
    told — e.g. that an escalation warning reached it)."""
    repo = make_scratch_repo(tmp_path, repo_files)
    env = ScratchEnvironment(cwd=str(repo))

    gru_cfg = load_gru_config(gru_config)
    minion_cfg = load_yaml("minion.yaml")

    llm = ScriptedLLM(steps)
    with patch("litellm.completion", llm):
        gru_model = GruModel(
            model_name="mock/gru", model_kwargs=gru_cfg["model"]["model_kwargs"], policy=gru_cfg["tool_policy"]
        )
        minion_model_kwargs = {"model_name": "mock/minion", "model_kwargs": minion_cfg["model"]["model_kwargs"]}
        minion_agent_kwargs = {
            k: v for k, v in minion_cfg["agent"].items() if k not in ("system_template", "instance_template")
        }
        gru_env = GruEnvironment(
            docker_env=env,
            minion_model_kwargs=minion_model_kwargs,
            minion_agent_kwargs=minion_agent_kwargs,
            minion_system_template=minion_cfg["agent"]["system_template"],
            minion_instance_template=minion_cfg["agent"]["instance_template"],
            output_dir=output_dir,
        )
        gru_agent_kwargs = {
            k: v for k, v in gru_cfg["agent"].items() if k not in ("system_template", "instance_template")
        }
        gru_agent = DefaultAgent(
            gru_model,
            gru_env,
            system_template=gru_cfg["agent"]["system_template"],
            instance_template=gru_cfg["agent"]["instance_template"],
            output_path=(output_dir / "gru.traj.json") if output_dir else None,
            **gru_agent_kwargs,
        )
        gru_env.gru_agent = gru_agent

        start = time.time()
        try:
            result = gru_agent.run(
                task_description=task_description,
                repo_name="mock-repo",
                repo_path_or_access_instructions=str(repo),
                # role.md's {{ cost_context }} needs a value (StrictUndefined) — "mock/gru"
                # and "mock/minion" have no real pricing, so this always resolves to "".
                cost_context=describe_cost_ratio("mock/gru", "mock/minion"),
            )
        except Exception as e:
            # Same crash-safety fallback run_gru_session.py uses, so a scripted test can
            # assert on exit_status without needing to catch the harness's own exceptions.
            result = {"submission": "", "exit_status": f"Crashed:{type(e).__name__}:{e}"}
        result.setdefault("_wall_clock", time.time() - start)

    return Session(result=result, gru_agent=gru_agent, gru_env=gru_env, llm=llm, repo=repo)
