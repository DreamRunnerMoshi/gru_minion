"""Gru's "environment" for GAIA — sibling of orchestrator/gru_environment.py. Dispatches
delegate_to_minion, think, web_search, python_exec, finish (see gaia_tools.py).

Reuses the SAME sandbox container for every action, Gru's own and every minion
delegation's, exactly like GruEnvironment does for SWE-bench's shared testbed — except
there's no repo here, so no initial_commit/git-diff tracking; `finish` submits an
`answer` string, not a patch. `web_search` and `python_exec` both dispatch to the
sandbox via `docker_env.execute()`, the same primitive `_delegate`'s agentic mode and
oneshot mode already use — no new execution machinery needed for those two actions.

The minion's own agentic-mode loop is unmodified from GruEnvironment's: a bare
MinionModel (LitellmModel, generic) driven by a bare DefaultAgent against the same
`docker_env` — mini-swe-agent's own stock bash-tool loop, submission triggered by the
`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` marker convention baked into DockerEnvironment
itself (verified against the installed mini-swe-agent source, not assumed). Nothing
GAIA-specific needed there: the minion just has a network-enabled sandbox with
/usr/local/bin/websearch.py on its PATH instead of a git testbed.
"""

import logging
import shlex
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
    "You are a minion — the execution role in a two-tier research-agent system. You were handed exactly "
    "one bounded piece of work by Gru, the planning role, along with all the material needed to do it. "
    "You have no tools of your own: work only from the material below. Do the work and return exactly "
    "what the output contract asks for, nothing else — no preamble, no commentary."
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
        websearch_path: str = "/usr/local/bin/websearch.py",
    ):
        self.docker_env = docker_env
        # Configurable so tests can point this at a fake script instead of writing into
        # /usr/local/bin on the test host — see tests/gaia_harness.py.
        self.websearch_path = websearch_path
        self.minion_model_kwargs = minion_model_kwargs
        self.minion_agent_kwargs = minion_agent_kwargs
        self.minion_system_template = minion_system_template
        self.minion_instance_template = minion_instance_template
        self.output_dir = output_dir
        self.logger = logger or logging.getLogger("gaia.environment")
        self.run_id = run_id
        # Set by run_gaia_session.py right after DefaultAgent(gru_model, self, ...) is
        # constructed — see gru_environment.py's matching field for why.
        self.gru_agent: DefaultAgent | None = None

        self.delegation_outputs: dict[str, str] = {}
        self.delegation_counter = 0
        self.minion_records: list[dict[str, Any]] = []
        self.gru_action_log: list[dict[str, Any]] = []
        # Set by _finish() so run_gaia_session.py can score against the gold answer
        # without re-parsing the trajectory.
        self.final_answer: str | None = None
        self.final_reasoning: str = ""

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

    # -- dispatch --

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        kind = action.get("kind")
        self.gru_action_log.append({"kind": kind, "args": action.get("args", {})})
        if kind == "delegate_to_minion":
            return self._delegate(action["args"])
        if kind == "think":
            return self._think(action["args"])
        if kind == "web_search":
            return self._web_search(action["args"])
        if kind == "python_exec":
            return self._python_exec(action["args"])
        if kind == "finish":
            return self._finish(action["args"])
        raise ValueError(f"GaiaEnvironment cannot execute action of kind {kind!r}")

    def _next_id(self) -> str:
        self.delegation_counter += 1
        return f"t{self.delegation_counter}"

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

    def _web_search(self, args: dict) -> dict[str, Any]:
        query = args.get("query", "")
        out = self.docker_env.execute({"command": f"python3 {self.websearch_path} {shlex.quote(query)}"})
        return {
            "output": f"{out['output']}{self._turn_cost_line()}",
            "returncode": out["returncode"],
            "exception_info": out.get("exception_info", ""),
        }

    def _python_exec(self, args: dict) -> dict[str, Any]:
        code = args.get("code", "")
        out = self.docker_env.execute({"command": f"python3 -c {shlex.quote(code)}"})
        return {
            "output": f"{out['output']}{self._turn_cost_line()}",
            "returncode": out["returncode"],
            "exception_info": out.get("exception_info", ""),
        }

    def _run_python_checks(self, checks: list[str]) -> tuple[bool, str]:
        """Verdict-mode delegation checks: Python snippets, must run without raising
        and the last stdout line must be truthy ('True'/non-empty/non-'False'/non-'0')."""
        if not checks:
            return True, "(no checks specified)"
        outputs = []
        all_passed = True
        for check_code in checks:
            out = self.docker_env.execute({"command": f"python3 -c {shlex.quote(check_code)}"})
            last_line = out["output"].strip().splitlines()[-1].strip() if out["output"].strip() else ""
            ok = out["returncode"] == 0 and last_line not in ("", "False", "0", "None")
            all_passed = all_passed and ok
            tail = out["output"][-2000:]
            outputs.append(f"$ python3 -c {check_code!r}\n(exit {out['returncode']})\n{tail}")
        return all_passed, "\n\n".join(outputs)

    # -- delegation (mirrors GruEnvironment._delegate; see that file's docstring) --

    def _gather_inputs(self, inputs: dict) -> str:
        parts = []
        for ref in inputs.get("from") or []:
            parts.append(f"--- {ref} ---\n{self.delegation_outputs.get(ref, '[no output recorded for this id]')}")
        for path in inputs.get("read_paths") or []:
            out = self.docker_env.execute({"command": f"cat {shlex.quote(path)}"})
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
        """A full bash tool loop against the shared sandbox — same mechanism as
        GruEnvironment's, just no repo/testbed to modify, a websearch.py on PATH
        instead."""
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
            passed, check_output = self._run_python_checks(args["verification"]["checks"])
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
        """No repo to diff — GAIA scores an ANSWER string against a hidden gold answer
        (exact-match after normalization, see orchestrator/gaia_scorer.py), not a patch.
        Unlike SWE-bench's finish(), there's no self-authored final_verification gate:
        there's no hidden test suite to approximate, so nothing here can be more
        confident than Gru's own stated reasoning. finish always succeeds — the actual
        correctness check happens after the session, in run_gaia_session.py, against the
        real gold answer Gru never sees."""
        self.final_answer = args.get("answer", "")
        self.final_reasoning = args.get("reasoning", "")
        self.logger.info(f"finish: answer={self.final_answer!r}")
        raise Submitted(
            {
                "role": "exit",
                "content": args.get("reasoning", ""),
                "extra": {
                    "exit_status": "Submitted",
                    "submission": self.final_answer,
                },
            }
        )
