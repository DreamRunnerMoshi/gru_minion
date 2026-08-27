"""GAIA: a question, a network-enabled sandbox, and an exact-match score against the
dataset's own "Final answer" — no hidden test suite, no second evaluation pass.

Deliberately NOT a divergent copy of Gru's prompt or tool schema. The whole point of this
experiment (explicit user instruction, 2026-08-25): Gru/minion is one architecture with
one prompt; only the benchmark underneath changes. So there is no `web_search`/
`python_exec` tool here. `run_check` (unchanged: "run shell commands yourself and see the
result") is how Gru touches GAIA too — it just runs against a sandbox that happens to
have python3 and a websearch.py helper on it (see gaia_sandbox/), the same way SWE-bench's
run_check runs against a testbed that happens to have a git repo. The minion's own loop is
likewise unmodified.

`finish()` keeps the SAME schema too: `summary` + `final_verification.checks` (shell
commands, exit 0 = pass), no `answer` field — that field doesn't exist in the shared tool
schema and adding one would be exactly the divergence this avoids. GAIA needs an extracted
answer string, so the harness takes it from the checks themselves: GAIA's instance_template
(legitimately per-benchmark plumbing, not shared prompt content) asks Gru to make its last
verification check literally print the final answer, the same way SWE-bench's asks for a
reproduction case. The independent extraction is that last check's own captured stdout,
used only once every check has genuinely passed — never Gru's own summary, mirroring
SWE-bench's git-diff-not-self-report patch extraction.
"""

import logging
from typing import Any

from minisweagent.environments.docker import DockerEnvironment

from orchestrator.benchmarks.base import Benchmark, Outcome, Task
from orchestrator.benchmarks.gaia_dataset import load_gaia
from orchestrator.benchmarks.gaia_scorer import question_scorer
from orchestrator.gru.environment import CheckResult, GruEnvironment

logger = logging.getLogger("gaia.benchmark")


class GaiaEnvironment(GruEnvironment):
    final_answer: str | None = None

    def build_submission(self, final_checks: CheckResult) -> str:
        self.final_answer = final_checks.last_stdout
        return self.final_answer


class GaiaBenchmark(Benchmark):
    environment_class = GaiaEnvironment

    def load_task(self, instance_id: str, **overrides) -> Task:
        dataset = {**self.spec.dataset, **{k: v for k, v in overrides.items() if v}}
        instances = {r["task_id"]: r for r in load_gaia(split=dataset.get("split", "validation"))}
        if instance_id not in instances:
            raise SystemExit(f"task {instance_id!r} not in GAIA {dataset.get('split', 'validation')}")
        instance = instances[instance_id]
        if instance["file_name"]:
            # The pilot's toolset is search + code execution; nothing parses an attached
            # file, so such an instance is unanswerable by construction. Still worth
            # running (it's a real trajectory) but not worth mistaking for a capability
            # finding — see experiments/exp6/NOTES.md.
            logger.warning(
                f"task {instance_id} has an attached file ({instance['file_name']!r}) — this pilot's toolset "
                "(a bash-capable sandbox with no file/image/audio parsing library wired to a tool) cannot use "
                "it; expect this run to fail on that basis alone."
            )
        return Task(
            instance_id=instance_id,
            prompt_vars={"task_description": instance["Question"]},
            raw=instance,
        )

    def open_environment(self, task: Task) -> Any:
        return DockerEnvironment(**self.session_config["environment"])

    def finalize(self, *, task: Task, result: dict, env: GaiaEnvironment, model_name: str) -> Outcome:
        answer = result.get("submission", "") or env.final_answer or ""
        gold = task.raw["Final answer"]
        resolved = question_scorer(answer, gold) if answer else False
        record = {
            "model_name_or_path": model_name,
            "task_id": task.instance_id,
            "question": task.raw["Question"],
            "level": task.raw["Level"],
            "answer": answer,
            "gold_answer": gold,
            "resolved": resolved,
            "exit_status": result.get("exit_status", ""),
        }
        return Outcome(
            submission=answer,
            prediction=record,
            summary_fields={
                "task_id": task.instance_id,
                "answer": answer,
                "gold_answer": gold,
                "resolved": resolved,
            },
            log_line=f"resolved={resolved} answer={answer!r} gold={gold!r}",
        )
