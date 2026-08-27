"""SWE-bench: a PR description plus a repository checkout, scored later by running the
instance's hidden FAIL_TO_PASS/PASS_TO_PASS suites against the submitted patch.

The submission is a `git diff` against the commit the testbed started on — not a bare
`git diff` (working tree only). Caught live 2026-08-25 (exp5): every one of gpt-solo's 5
runs had GPT-5-mini `git commit` its own fix as a normal part of its workflow, which made
a bare `git diff` show nothing. Gru's own final_verification still passed (it re-ran real
checks against the actual repo state, which genuinely had the fix), so it called finish()
believing it had submitted a real patch and the harness silently recorded an empty one.
All 5 were reported as real SWE-bench failures ("empty patch") that were actually a
patch-*extraction* bug — and by the time it was noticed the containers were torn down, so
the real patches were unrecoverable. `git diff <ref>` compares the working tree, staged
and unstaged, against `<ref>`: committed and uncommitted changes together, regardless of
who committed.
"""

from typing import Any

from minisweagent.run.benchmarks.swebench import DATASET_MAPPING, get_sb_environment

from orchestrator.benchmarks.base import Benchmark, Outcome, Task
from orchestrator.gru.environment import CheckResult, GruEnvironment


class SWEBenchEnvironment(GruEnvironment):
    def setup(self) -> None:
        # Captured before Gru's session runs any action, so the patch at finish() is
        # correct even if Gru (or a minion) runs `git commit` along the way.
        self.initial_commit = self.env.execute({"command": "git rev-parse HEAD"})["output"].strip()

    def build_submission(self, final_checks: CheckResult) -> str:
        return self.diff()

    def diff(self) -> str:
        """The patch as it stands right now. Also the crash-recovery path: a session that
        ended any way other than a clean Submitted still left the minions' real work in the
        shared testbed's working tree."""
        return self.env.execute({"command": f"git diff {self.initial_commit}"})["output"]


class SWEBenchBenchmark(Benchmark):
    environment_class = SWEBenchEnvironment

    def load_task(self, instance_id: str, **overrides) -> Task:
        from datasets import load_dataset

        dataset = {**self.spec.dataset, **{k: v for k, v in overrides.items() if v}}
        subset, split = dataset.get("subset", "lite"), dataset.get("split", "test")
        path = DATASET_MAPPING.get(subset, subset)
        instances = {inst["instance_id"]: inst for inst in load_dataset(path, split=split)}
        if instance_id not in instances:
            raise SystemExit(f"instance {instance_id!r} not in {subset}/{split}")
        instance = instances[instance_id]
        return Task(
            instance_id=instance_id,
            prompt_vars={
                "task_description": instance["problem_statement"],
                "repo_name": instance.get("repo", ""),
                "repo_path_or_access_instructions": self.environment_config["environment"]["cwd"],
            },
            raw=instance,
        )

    def open_environment(self, task: Task) -> Any:
        return get_sb_environment(self.environment_config, task.raw)

    def finalize(self, *, task: Task, result: dict, env: SWEBenchEnvironment, model_name: str) -> Outcome:
        patch = result.get("submission", "")
        recovered = False
        if not patch and result.get("exit_status") != "Submitted":
            # e.g. RepeatedFormatError from Gru writing prose instead of calling finish
            # after a real pass: the minions' actual work still sits in the shared
            # testbed's working tree — pull it rather than losing it. Found the hard way:
            # a run where every delegation succeeded still produced a 0-char patch
            # because Gru never phrased a valid finish() call.
            patch = env.diff()
            recovered = True
        return Outcome(
            submission=patch,
            prediction={
                "model_name_or_path": model_name,
                "instance_id": task.instance_id,
                "model_patch": patch,
            },
            summary_fields={"instance_id": task.instance_id},
            log_line=f"Patch length: {len(patch)} chars{' (recovered via git diff)' if recovered else ''}",
        )
