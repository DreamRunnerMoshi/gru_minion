"""Gru's "environment" for GAIA — sibling of orchestrator/gru_environment.py, but
deliberately NOT a divergent copy of Gru's prompt or tool schema. The whole point of
this experiment (explicit user instruction, 2026-08-25): Gru/minion is one
architecture with one prompt; only the benchmark underneath changes. So this dispatches
the exact same four actions gru_toolcall.py defines — delegate_to_minion, think,
run_check, finish — nothing added, nothing renamed.

There is no `web_search`/`python_exec` tool here. `run_check` (unchanged: "run shell
commands yourself and see the result") is how Gru touches GAIA too — it just runs
against a network-enabled sandbox that happens to have python3 and a websearch.py
helper on it (see gaia_sandbox/), the same way SWE-bench's run_check runs against a
testbed that happens to have a git repo. The minion's own agentic loop is likewise
unmodified from GruEnvironment's — mini-swe-agent's stock bash-tool loop, same as
always.

`finish()` keeps the SAME schema too: `summary` + `final_verification.checks` (shell
commands, exit 0 = pass), no `answer` field — that field doesn't exist in the shared
prompt/tool schema and adding one would be exactly the kind of divergence this file
exists to avoid. GAIA needs an extracted answer string, so the harness takes it from
the checks themselves: GAIA's instance_template (which, like SWE-bench's, is legitimately
per-benchmark plumbing, not shared prompt content) asks Gru to make its last
verification check literally print the final answer — the same way SWE-bench's
instance_template asks for a reproduction case, and the harness extracts the real
patch independently via git diff rather than trusting Gru's summary. Here the
independent extraction is: the last check's own captured stdout, only used once every
check has genuinely passed.
"""

import logging
from pathlib import Path
from typing import Any

import litellm

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.exceptions import Submitted

from orchestrator.cache_stats import extract_cache_stats
from orchestrator.minion_model import MinionModel
from orchestrator.token_usage import extract_token_usage

_VERDICT_SUMMARY_MARKER = "===PATCH==="


def _split_verdict_submission(submission: str) -> tuple[str, str]:
    if _VERDICT_SUMMARY_MARKER in submission:
        summary, _, patch = submission.partition(_VERDICT_SUMMARY_MARKER)
        return summary.strip(), patch.strip()
    return submission.strip(), ""


_ONESHOT_SYSTEM = (
    "You are a minion — the execution role in a two-tier coding-agent system. You were handed exactly "
    "one bounded piece of work by Gru, the planning role, along with all the material needed to do it. "
    "You have no shell and no repository access: work only from the material below. Do the work and "
    "return exactly what the output contract asks for, nothing else — no preamble, no commentary."
)


class GaiaEnvironment:
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
        run_id: str = "test-session",
    ):
        self.docker_env = docker_env
        self.minion_model_kwargs = minion_model_kwargs
        self.minion_agent_kwargs = minion_agent_kwargs
        self.minion_system_template = minion_system_template
        self.minion_instance_template = minion_instance_template
        self.output_dir = output_dir
        self.logger = logger or logging.getLogger("gaia.environment")
        self.run_id = run_id
        self.gru_agent: DefaultAgent | None = None

        self.delegation_outputs: dict[str, str] = {}
        self.delegation_counter = 0
        self.minion_records: list[dict[str, Any]] = []
        self.gru_action_log: list[dict[str, Any]] = []
        self.final_answer: str | None = None

    # -- Environment protocol --

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
            "gru_action_log": self.gru_action_log,
        }

    # -- dispatch: same four kinds as GruEnvironment, unchanged --

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        kind = action.get("kind")
        self.gru_action_log.append({"kind": kind, "args": action.get("args", {})})
        if kind == "delegate_to_minion":
            return self._delegate(action["args"])
        if kind == "think":
            return self._think(action["args"])
        if kind == "run_check":
            return self._run_check_action(action["args"])
        if kind == "finish":
            return self._finish(action["args"])
        raise ValueError(f"GaiaEnvironment cannot execute action of kind {kind!r}")

    def _next_id(self) -> str:
        self.delegation_counter += 1
        return f"t{self.delegation_counter}"

    def _run_checks(self, checks: list[str]) -> tuple[bool, str, str]:
        """Same primitive as GruEnvironment._run_checks, plus the last check's raw
        stdout — GAIA's finish() uses that as the extracted answer, see module
        docstring. Not part of the shared prompt; this is harness-internal."""
        if not checks:
            return True, "(no checks specified)", ""
        outputs = []
        all_passed = True
        last_stdout = ""
        for check_cmd in checks:
            out = self.docker_env.execute({"command": check_cmd})
            ok = out["returncode"] == 0
            all_passed = all_passed and ok
            tail = out["output"][-2000:]
            outputs.append(f"$ {check_cmd}\n(exit {out['returncode']})\n{tail}")
            last_stdout = out["output"].strip()
        return all_passed, "\n\n".join(outputs), last_stdout

    def _turn_cost_line(self) -> str:
        if self.gru_agent is None or not self.gru_agent.messages:
            return ""
        usage = (self.gru_agent.messages[-1].get("extra", {}).get("response", {}) or {}).get("usage") or {}
        total = usage.get("total_tokens")
        return f" [this turn cost: {total:,} tokens]" if total is not None else ""

    # -- non-delegating actions --

    def _think(self, args: dict) -> dict[str, Any]:
        return {
            "output": f"(noted — nothing was executed and no minion was charged.{self._turn_cost_line()})",
            "returncode": 0,
            "exception_info": "",
        }

    def _run_check_action(self, args: dict) -> dict[str, Any]:
        checks = args.get("checks", [])
        passed, check_output, _ = self._run_checks(checks)
        status = "PASS" if passed else "FAIL"
        return {
            "output": f"Checks: {status}{self._turn_cost_line()}\n\n{check_output}",
            "returncode": 0 if passed else 1,
            "exception_info": "",
        }

    # -- delegation (identical to GruEnvironment._delegate) --

    def _gather_inputs(self, inputs: dict) -> str:
        parts = []
        for ref in inputs.get("from") or []:
            parts.append(f"--- {ref} ---\n{self.delegation_outputs.get(ref, '[no output recorded for this id]')}")
        for path in inputs.get("read_paths") or []:
            out = self.docker_env.execute({"command": f"cat {path}"})
            body = out["output"] if out["returncode"] == 0 else f"[could not read: exit {out['returncode']}]"
            parts.append(f"--- {path} ---\n{body}")
        return "\n\n".join(parts) if parts else "(none)"

    def _run_oneshot(self, args: dict, material: str, delegation_id: str) -> tuple[str, dict[str, int], int, dict]:
        model_kwargs = {
            k: v for k, v in self.minion_model_kwargs.get("model_kwargs", {}).items() if k != "parallel_tool_calls"
        }
        model_kwargs["extra_body"] = {"session_id": f"minion-{self.run_id}-{delegation_id}"}
        prompt = (
            f"<task>\n{args['description']}\n</task>\n\n"
            f"<output_contract>\n{args['output_contract']}\n</output_contract>\n\n"
            f"<material>\n{material}\n</material>"
        )
        response = litellm.completion(
            model=self.minion_model_kwargs["model_name"],
            messages=[{"role": "system", "content": _ONESHOT_SYSTEM}, {"role": "user", "content": prompt}],
            **model_kwargs,
        )
        text = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        tokens = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }
        cache = {"n_calls": 1, "total_prompt_tokens": tokens["prompt_tokens"],
                 "reported_cached_tokens": None, "reported_cache_hit_pct": None,
                 "estimated_reused_tokens": 0, "estimated_cache_hit_pct": 0.0}
        return text, tokens, 1, cache

    def _run_agentic(
        self, args: dict, material: str, delegation_id: str
    ) -> tuple[str, dict[str, int], int, str, str, dict]:
        minion_model_kwargs = {
            **self.minion_model_kwargs,
            "model_kwargs": {
                **self.minion_model_kwargs.get("model_kwargs", {}),
                "extra_body": {"session_id": f"minion-{self.run_id}-{delegation_id}"},
            },
        }
        minion_model = MinionModel(**minion_model_kwargs)
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
        result = minion_agent.run(subtask=args, prior_delegation_outputs=material)
        return (
            result.get("submission", ""),
            extract_token_usage(minion_agent.messages),
            minion_agent.n_calls,
            result.get("exit_status", ""),
            str(minion_output_path) if minion_output_path else "",
            extract_cache_stats(minion_agent.messages),
        )

    def _delegate(self, args: dict) -> dict[str, Any]:
        delegation_id = self._next_id()

        args = {**args}
        args.setdefault("verification", {})
        args["verification"] = {"checks": [], **(args["verification"] if isinstance(args["verification"], dict) else {})}
        args.setdefault("inputs", {})
        args["inputs"] = {"from": [], "read_paths": [], **args["inputs"]}

        returns = args["returns"]
        mode = args["mode"]
        material = self._gather_inputs(args["inputs"])

        self.logger.info(f"[{delegation_id}] delegating ({mode}/{returns}): {args['description'][:120]}")

        exit_status, trajectory_path = "", ""
        if mode == "oneshot":
            submission, tokens, n_calls, cache = self._run_oneshot(args, material, delegation_id)
            exit_status = "Completed"
        else:
            submission, tokens, n_calls, exit_status, trajectory_path, cache = self._run_agentic(
                args, material, delegation_id
            )

        output_path = None
        if self.output_dir is not None:
            output_path = self.output_dir / "delegations" / f"{delegation_id}.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(submission or "")

        self.minion_records.append(
            {
                "delegation_id": delegation_id,
                "returns": returns,
                "mode": mode,
                "description": args["description"],
                "scope": args["inputs"].get("scope", ""),
                "api_calls": n_calls,
                **tokens,
                "exit_status": exit_status,
                "trajectory_path": trajectory_path or None,
                "output_path": str(output_path) if output_path else None,
                "cache": cache,
            }
        )

        cost_line = (
            f"[{delegation_id} cost: {tokens['total_tokens']:,} tokens, {n_calls} model call"
            f"{'' if n_calls == 1 else 's'}, mode={mode}]"
        )

        if returns == "verdict":
            passed, check_output, _ = self._run_checks(args["verification"]["checks"])
            self.delegation_outputs[delegation_id] = submission
            summary, _ = _split_verdict_submission(submission)
            status = "PASS" if passed else "FAIL"
            observation = (
                f"Delegation {delegation_id}: {status}\n{cost_line}\n\n"
                f"What the minion did:\n{summary}\n\n"
                f"{check_output}\n\n"
                "(The PASS/FAIL above comes from independently re-running your verification checks, not "
                "the minion's own claim — trust that, not the summary, for whether it actually worked.)"
            )
            return {"output": observation, "returncode": 0 if passed else 1, "exception_info": ""}

        self.delegation_outputs[delegation_id] = submission
        observation = f"Delegation {delegation_id} findings:\n{cost_line}\n\n{submission}"
        return {"output": observation, "returncode": 0, "exception_info": ""}

    def _finish(self, args: dict) -> dict[str, Any]:
        """Same finish() schema as GruEnvironment's: summary + final_verification.checks,
        no answer field. GAIA's instance_template asks Gru to make its last check print
        the final answer; that check's own re-run stdout (not Gru's summary) is what
        gets scored — see module docstring for why this mirrors SWE-bench's
        independent-of-self-report patch extraction."""
        checks = args.get("final_verification", {}).get("checks", [])
        passed, check_output, last_stdout = self._run_checks(checks)

        self.logger.info(f"finish attempt: final_verification {'PASSED' if passed else 'FAILED'}")

        if passed:
            self.final_answer = last_stdout
            raise Submitted(
                {
                    "role": "exit",
                    "content": args.get("summary", ""),
                    "extra": {
                        "exit_status": "Submitted",
                        "submission": last_stdout,
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
