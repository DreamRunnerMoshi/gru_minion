"""GAIA-shaped entry into tests/harness.py: the same scripted-model, LocalEnvironment
wiring, pointed at the `gaia` benchmark instead of `swe_bench` — a scratch workspace
instead of a git repo (GAIA has no repository to check out) and a question instead of a
PR description. Nothing GAIA-specific about the *architecture* is set up here, because
there isn't any: one architecture, one prompt, only the benchmark underneath changes
(see orchestrator/benchmarks/gaia.py).

A fake `websearch.py` is dropped into a bin/ dir under tmp_path so a scripted
`run_check` that shells out to it (exactly as the real gaia-sandbox image's run_check
calls would) resolves to deterministic canned output instead of a real Tavily call.
"""

import os
import stat
from pathlib import Path

from orchestrator.benchmarks.base import Task
from tests.harness import ScratchEnvironment, Session, run_benchmark_session
from tests.mock_llm import Step

_FAKE_WEBSEARCH = """#!/usr/bin/env python3
import json, sys
print(json.dumps({"query": " ".join(sys.argv[1:]), "results": [
    {"title": "Fake result", "url": "https://example.com/fake", "snippet": "canned test snippet"}
]}))
"""


def make_scratch_dir(tmp_path: Path) -> tuple[Path, Path]:
    """A plain scratch directory, plus a bin/ dir holding a fake websearch.py — the real
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


def run_session(
    *,
    tmp_path: Path,
    steps: list[Step],
    task_description: str = "What is 2 + 2?",
    gru_config: str | None = None,
    output_dir: Path | None = None,
) -> Session:
    workdir, bin_dir = make_scratch_dir(tmp_path)
    return run_benchmark_session(
        benchmark_name="gaia",
        shell_env=ScratchEnvironment(
            cwd=str(workdir), env={"PATH": f"{bin_dir}:" + os.environ.get("PATH", "")}
        ),
        workdir=workdir,
        steps=steps,
        task=Task(
            instance_id="mock-task-1",
            prompt_vars={"task_description": task_description},
            raw={"Question": task_description, "Final answer": "4", "Level": "2", "file_name": ""},
        ),
        gru_config=gru_config,
        output_dir=output_dir,
    )
