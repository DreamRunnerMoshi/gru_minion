"""Gru's "environment": doesn't run bash, dispatches delegate_to_minion (spawns a
minion sub-session against the shared persistent testbed) and finish (independently
verifies + raises Submitted). See prompts/README.md and prompts/gru-loop.md for the
design this implements: Gru never re-verifies content a real check already
established (the "verifiability trap"), and delegation return shape depends on type
(findings for context_gather/locate, pass/fail-only for synthesize).
"""

import logging
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.exceptions import Submitted
from minisweagent.models.litellm_model import LitellmModel

from orchestrator.token_usage import extract_token_usage


class GruEnvironment:
    def __init__(
        self,
        *,
        docker_env: DockerEnvironment,
        minion_model_kwargs: dict[str, Any],
        minion_agent_kwargs: dict[str, Any],
        minion_system_template: str,
        minion_instance_template: str,
        output_dir: Path | None = None,
        logger: logging.Logger | None = None,
    ):
        self.docker_env = docker_env
        self.minion_model_kwargs = minion_model_kwargs
        self.minion_agent_kwargs = minion_agent_kwargs
        self.minion_system_template = minion_system_template
        self.minion_instance_template = minion_instance_template
        self.output_dir = output_dir
        self.logger = logger or logging.getLogger("gru.environment")

        self.delegation_outputs: dict[str, str] = {}  # id -> raw content, for inputs.from passthrough
        self.delegation_counter = 0
        # per-role cost accounting (see prompts/README.md "Cost attribution")
        self.minion_records: list[dict[str, Any]] = []

    # -- Environment protocol (mirrors DockerEnvironment's shape) --

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return kwargs

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            },
            "minion_records": self.minion_records,
        }

    # -- dispatch --

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        kind = action.get("kind")
        if kind == "delegate_to_minion":
            return self._delegate(action["args"])
        if kind == "finish":
            return self._finish(action["args"])
        raise ValueError(f"GruEnvironment cannot execute action of kind {kind!r}")

    def _next_id(self) -> str:
        self.delegation_counter += 1
        return f"t{self.delegation_counter}"

    def _run_checks(self, checks: list[str]) -> tuple[bool, str]:
        """Run check commands directly against the shared testbed. Real, independent
        pass/fail — never trusts a minion's own report. See prompts/README.md
        'Trust the mechanical signal, don't re-verify it'."""
        if not checks:
            return True, "(no checks specified)"
        outputs = []
        all_passed = True
        for check_cmd in checks:
            out = self.docker_env.execute({"command": check_cmd})
            ok = out["returncode"] == 0
            all_passed = all_passed and ok
            tail = out["output"][-2000:]
            outputs.append(f"$ {check_cmd}\n(exit {out['returncode']})\n{tail}")
        return all_passed, "\n\n".join(outputs)

    def _delegate(self, args: dict) -> dict[str, Any]:
        delegation_id = self._next_id()
        subtask_type = args["type"]

        # Normalize optional fields the tool schema allows to be omitted — Jinja's
        # StrictUndefined (same as mini-swe-agent's own templates use) errors on a
        # missing dict key, not just a falsy value, so `subtask.search_strategy` in
        # the minion template needs the key present even when Gru omitted it.
        args = {**args}
        args.setdefault("search_strategy", None)
        args.setdefault("verification", {})
        args["verification"] = {"checks": [], **args["verification"]}
        args.setdefault("inputs", {})
        args["inputs"] = {"from": [], **args["inputs"]}

        prior_refs = args.get("inputs", {}).get("from") or []
        if prior_refs:
            prior_context = "\n\n".join(
                f"--- {ref} ---\n{self.delegation_outputs.get(ref, '[no output recorded for this id]')}"
                for ref in prior_refs
            )
        else:
            prior_context = "(none)"

        minion_model = LitellmModel(**self.minion_model_kwargs)
        minion_output_path = None
        if self.output_dir is not None:
            minion_output_path = self.output_dir / "minions" / f"{delegation_id}.traj.json"
        minion_agent = DefaultAgent(
            minion_model,
            self.docker_env,
            system_template=self.minion_system_template,
            instance_template=self.minion_instance_template,
            output_path=minion_output_path,
            **self.minion_agent_kwargs,
        )

        self.logger.info(f"[{delegation_id}] delegating ({subtask_type}): {args['description'][:120]}")
        result = minion_agent.run(subtask=args, prior_delegation_outputs=prior_context)
        submission = result.get("submission", "")

        self.minion_records.append(
            {
                "delegation_id": delegation_id,
                "type": subtask_type,
                "description": args["description"],
                "api_calls": minion_agent.n_calls,
                "cost": minion_agent.cost,  # will be 0.0 for self-hosted models — see token counts below
                **extract_token_usage(minion_agent.messages),
                "exit_status": result.get("exit_status", ""),
                "trajectory_path": str(minion_output_path) if minion_output_path else None,
            }
        )

        if subtask_type == "synthesize":
            checks = args.get("verification", {}).get("checks", [])
            passed, check_output = self._run_checks(checks)
            self.delegation_outputs[delegation_id] = submission  # kept for a later inputs.from, not shown to Gru
            status = "PASS" if passed else "FAIL"
            observation = (
                f"Delegation {delegation_id} ({subtask_type}): {status}\n\n"
                f"{check_output}\n\n"
                "(This is the check result, not the diff — the content itself isn't shown to you; "
                "see prompts/README.md on why synthesize delegations return pass/fail only.)"
            )
            return {"output": observation, "returncode": 0 if passed else 1, "exception_info": ""}

        self.delegation_outputs[delegation_id] = submission
        observation = f"Delegation {delegation_id} ({subtask_type}) findings:\n\n{submission}"
        return {"output": observation, "returncode": 0, "exception_info": ""}

    def _finish(self, args: dict) -> dict[str, Any]:
        """A failing final_verification must NOT end the session — per prompts/gru-loop.md,
        that's the signal for Gru to reconsider its approach broadly and keep working, not a
        terminal state. Only a passing check actually raises Submitted."""
        checks = args.get("final_verification", {}).get("checks", [])
        passed, check_output = self._run_checks(checks)
        diff_out = self.docker_env.execute({"command": "git diff"})
        patch = diff_out["output"]

        self.logger.info(f"finish attempt: final_verification {'PASSED' if passed else 'FAILED'}")

        if passed:
            raise Submitted(
                {
                    "role": "exit",
                    "content": args.get("summary", ""),
                    "extra": {
                        "exit_status": "Submitted",
                        "submission": patch,
                        "final_verification_passed": True,
                        "final_verification_output": check_output,
                    },
                }
            )

        observation = (
            "finish() rejected: final_verification failed.\n\n"
            f"{check_output}\n\n"
            "This means the overall decomposition was wrong somewhere, not one isolated step — "
            "reconsider your approach broadly rather than patching the last delegation. "
            "You still have everything you've learned so far; this session continues."
        )
        return {"output": observation, "returncode": 1, "exception_info": ""}
