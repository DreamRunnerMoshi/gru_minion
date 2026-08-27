"""Wires up one Gru session against a disposable local directory instead of a real
benchmark container, and against a ScriptedLLM instead of a real model. This is the same
wiring orchestrator/run_session.py does — it calls the same
orchestrator.session.build_session — minus the dataset load and the Docker container:
the two things that cost real time/infra and aren't what's under test when the question
is "does the harness's own control flow do the right thing."

Swapping DockerEnvironment for mini-swe-agent's own LocalEnvironment is not a stand-in
implementation: it is the library's other supported environment, running real shell
commands (git, sed, cat, ...) against a real (temporary, disposable) directory — so
run_check, the minion's actual bash tool loop, and `git diff` patch extraction are all
exercised for real. Only the model call is fake.

Benchmark-parameterised (2026-08-26): the same function drives a SWE-bench session
against a scratch git repo and a GAIA session against a scratch workspace, since
`build_session` is now benchmark-agnostic and the benchmark supplies only its own
environment class and prompt variables. `tests/gaia_harness.py` is the GAIA-shaped entry
point into it.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment

from orchestrator.benchmarks import get_benchmark
from orchestrator.benchmarks.base import Task
from orchestrator.gru.environment import GruEnvironment
from orchestrator.session import build_session, run_task
from tests.mock_llm import ScriptedLLM, Step


class ScratchEnvironment(LocalEnvironment):
    """LocalEnvironment plus the no-op `cleanup()` a benchmark's caller expects from a
    DockerEnvironment-shaped object; nothing to tear down for a plain directory."""

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

    @property
    def gaia_env(self) -> GruEnvironment:
        """Alias for GAIA tests, which talk about the same object by its own name."""
        return self.gru_env

    @property
    def workdir(self) -> Path:
        return self.repo


def run_benchmark_session(
    *,
    benchmark_name: str,
    shell_env: ScratchEnvironment,
    workdir: Path,
    steps: list[Step],
    task: Task,
    gru_config: str | None = None,
    output_dir: Path | None = None,
) -> Session:
    """Runs one full Gru session (real config, real prompts, real DefaultAgent loop,
    real benchmark environment class) against a scratch directory and a scripted model,
    and returns everything a test would want to inspect: the agent's own result dict
    (exit_status/submission), the environment (minion_records, gru_action_log), and the
    raw ScriptedLLM (every call it received, for asserting on what the model was actually
    told — e.g. that an escalation warning reached it)."""
    benchmark = get_benchmark(benchmark_name)
    llm = ScriptedLLM(steps)
    with patch("litellm.completion", llm):
        session = build_session(
            benchmark=benchmark,
            shell_env=shell_env,
            gru_model_name="mock/gru",
            minion_model_name="mock/minion",
            gru_config_name=gru_config,
            output_dir=output_dir,
        )
        start = time.time()
        # run_task already turns a crash into a not-Submitted result, the same way a
        # real run does — so a scripted test can assert on exit_status without having to
        # catch the harness's own exceptions.
        result = run_task(session, task)
        result.setdefault("_wall_clock", time.time() - start)

    return Session(result=result, gru_agent=session.gru_agent, gru_env=session.gru_env, llm=llm, repo=workdir)


def run_session(
    *,
    tmp_path: Path,
    steps: list[Step],
    task_description: str = "Fix the bug described in the task.",
    repo_files: dict[str, str] | None = None,
    gru_config: str | None = None,
    output_dir: Path | None = None,
) -> Session:
    """SWE-bench-shaped session against a scratch git repo."""
    repo = make_scratch_repo(tmp_path, repo_files)
    return run_benchmark_session(
        benchmark_name="swe_bench",
        shell_env=ScratchEnvironment(cwd=str(repo)),
        workdir=repo,
        steps=steps,
        task=Task(
            instance_id="mock__instance-1",
            prompt_vars={
                "task_description": task_description,
                "repo_name": "mock-repo",
                "repo_path_or_access_instructions": str(repo),
            },
            raw={},
        ),
        gru_config=gru_config,
        output_dir=output_dir,
    )
