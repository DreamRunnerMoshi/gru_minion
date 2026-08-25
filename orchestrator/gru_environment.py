"""Gru's "environment": doesn't run bash, dispatches Gru's four actions —
delegate_to_minion, think, run_check and finish. See prompts/README.md and
prompts/gru-loop.md for the design this implements.

Revised 2026-08-22 alongside orchestrator/gru_toolcall.py:

- **Delegation shape is chosen by Gru, not by our taxonomy.** `returns` decides
  what comes back (content vs. a pass/fail computed here from real checks);
  `mode` decides what it costs (a single model call vs. a full bash loop).
- **`mode="oneshot"` exists because exp2 ran every delegation as a 40-step agentic
  loop.** t1 spent 105,770 tokens to read one 317-line file and summarise it — work
  that is a single completion. Delegating menial work has to be *cheaper* than doing
  it inline or the whole criterion is unprofitable to follow.
- **Every delegation reports its own token cost back to Gru.** Gru was previously asked
  to prefer low-token work while being shown no token counts.
- **`think` and `run_check`** close two gaps: Gru had no action other than delegating,
  and no way to re-run a corrected check without spawning a no-op minion session.

Revised 2026-08-24: removed `_looks_like_repo_write`, the regex-based rejection of
`run_check` commands that looked like a repository edit (added 2026-08-23 after exp3
arm B showed Gru doing real edits through `run_check` instead of delegating). Explicit
user decision: don't force Gru's delegation behavior at the harness level, even against
a smaller model that may under-delegate — if it chooses to do work itself rather than
delegate, that's a finding about this model's behavior, not something to engineer
around. See prompts/gru-loop.md for the fuller rationale.

Revised 2026-08-24 (again): `returns="verdict"` used to hide the minion's own submission
from Gru entirely — only the independently re-run checks' pass/fail. Two problems: (1) on
FAIL, Gru had no idea what the minion had actually attempted, making "decide what to do
next" a guess; (2) exp4 runs 5-7 all failed real SWE-bench evaluation because a
delegation's `verification.checks` were too narrow (never tested the read-path half of
the fix) and Gru never saw what was actually changed, so had no chance to notice the gap
itself. Now the minion always compiles a short summary of what it did (see
config/minion.yaml's verdict-mode Submission steps) and that summary — never the raw
patch — is shown alongside the check's real pass/fail. The check result stays the only
thing that decides PASS/FAIL; the summary is explicitly labeled as not to be trusted for
correctness, only for "what happened."

Revised 2026-08-25 (exp5 start): every delegation now carries an OpenRouter `session_id`
(`minion-{run_id}-{delegation_id}`), stable across that one delegation's own turns. exp4's
cost data showed real, provider-reported cache hit rate collapsing on a handful of calls
per run (up to 10 of 41) with no correlation to wall-clock gaps — OpenRouter's own docs
attribute this to sticky-routing drift: without an explicit session_id, the routing key
is derived by hashing the opening messages, and a growing agent conversation changes that
hash turn to turn, occasionally landing a request on a different backend than the one
holding the warm cache. See run_gru_session.py's matching note and experiments/exp5/NOTES.md.
"""

import logging
from pathlib import Path
from typing import Any

import litellm

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.exceptions import Submitted
from minisweagent.models.litellm_model import LitellmModel

from orchestrator.cache_stats import extract_cache_stats
from orchestrator.token_usage import extract_token_usage

_VERDICT_SUMMARY_MARKER = "===PATCH==="


def _split_verdict_submission(submission: str) -> tuple[str, str]:
    """A verdict-mode minion submits summary.md then patch.txt, separated by
    _VERDICT_SUMMARY_MARKER (see config/minion.yaml's Submission steps). Split them —
    Gru gets the summary, never the raw patch; the check result is still what decides
    pass/fail. No marker (e.g. a oneshot verdict, or a minion that didn't follow the
    ritual) degrades to treating the whole submission as the summary."""
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
        run_id: str = "test-session",
    ):
        self.docker_env = docker_env
        self.minion_model_kwargs = minion_model_kwargs
        self.minion_agent_kwargs = minion_agent_kwargs
        self.minion_system_template = minion_system_template
        self.minion_instance_template = minion_instance_template
        self.output_dir = output_dir
        self.logger = logger or logging.getLogger("gru.environment")
        # OpenRouter sticky-routing key prefix — each delegation gets its own
        # {run_id}-{delegation_id} session_id (see run_gru_session.py's 2026-08-25 note),
        # since each delegation is its own conversation with its own prefix, not a
        # continuation of Gru's.
        self.run_id = run_id
        # Set by run_gru_session.py right after the DefaultAgent(gru_model, self, ...) that
        # owns this environment is constructed — can't be passed in __init__ since Gru's
        # agent doesn't exist yet at that point. Used only to surface each turn's own token
        # cost (see _turn_cost_line); a not-yet-wired or empty agent degrades to no cost line.
        self.gru_agent: DefaultAgent | None = None

        self.delegation_outputs: dict[str, str] = {}  # id -> raw content, for inputs.from passthrough
        self.delegation_counter = 0
        # per-role cost accounting (see prompts/README.md "Cost attribution")
        self.minion_records: list[dict[str, Any]] = []
        self.gru_action_log: list[dict[str, Any]] = []

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
        if kind == "run_check":
            return self._run_check_action(action["args"])
        if kind == "finish":
            return self._finish(action["args"])
        raise ValueError(f"GruEnvironment cannot execute action of kind {kind!r}")

    def _next_id(self) -> str:
        self.delegation_counter += 1
        return f"t{self.delegation_counter}"

    def _run_checks(self, checks: list[str]) -> tuple[bool, str]:
        """Run check commands directly against the shared testbed. Real, independent
        pass/fail — never trusts a minion's own report on whether its own work passed."""
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

    def _turn_cost_line(self) -> str:
        """Token cost of the Gru turn that just produced this action, so a self-directed
        run_check/think turn is priced too — not just delegations (gru.yaml: "you will be
        told what each delegation cost... and also what your own turn just cost")."""
        if self.gru_agent is None or not self.gru_agent.messages:
            return ""
        usage = (self.gru_agent.messages[-1].get("extra", {}).get("response", {}) or {}).get("usage") or {}
        total = usage.get("total_tokens")
        return f" [this turn cost: {total:,} tokens]" if total is not None else ""

    # -- non-delegating actions --

    def _think(self, args: dict) -> dict[str, Any]:
        """A turn spent deciding rather than delegating. Nothing runs; this exists so that
        'reason and decide directly' is an action Gru can actually take, and so that the
        choice between deciding and delegating is observable in the trajectory."""
        return {
            "output": f"(noted — nothing was executed and no minion was charged.{self._turn_cost_line()})",
            "returncode": 0,
            "exception_info": "",
        }

    def _run_check_action(self, args: dict) -> dict[str, Any]:
        checks = args.get("checks", [])
        passed, check_output = self._run_checks(checks)
        status = "PASS" if passed else "FAIL"
        return {
            "output": f"Checks: {status}{self._turn_cost_line()}\n\n{check_output}",
            "returncode": 0 if passed else 1,
            "exception_info": "",
        }

    # -- delegation --

    def _gather_inputs(self, inputs: dict) -> str:
        """Assemble the material a delegation was told it needs: prior delegation outputs
        (raw passthrough) plus any files the orchestrator was asked to hand over verbatim."""
        parts = []
        for ref in inputs.get("from") or []:
            parts.append(f"--- {ref} ---\n{self.delegation_outputs.get(ref, '[no output recorded for this id]')}")
        for path in inputs.get("read_paths") or []:
            out = self.docker_env.execute({"command": f"cat {path}"})
            body = out["output"] if out["returncode"] == 0 else f"[could not read: exit {out['returncode']}]"
            parts.append(f"--- {path} ---\n{body}")
        return "\n\n".join(parts) if parts else "(none)"

    def _run_oneshot(self, args: dict, material: str, delegation_id: str) -> tuple[str, dict[str, int], int, dict]:
        """A single model call: text in, text out, no shell. Returns (output, usage, n_calls)."""
        model_kwargs = {
            k: v for k, v in self.minion_model_kwargs.get("model_kwargs", {}).items() if k != "parallel_tool_calls"
        }
        # A single call has nothing to route consistently against, but set it anyway for
        # consistency with agentic mode and in case oneshot ever grows a retry/second call.
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
        # A oneshot is a single call with no prior context, so there is nothing a prefix
        # cache could reuse — recorded explicitly rather than left absent.
        cache = {"n_calls": 1, "total_prompt_tokens": tokens["prompt_tokens"],
                 "reported_cached_tokens": None, "reported_cache_hit_pct": None,
                 "estimated_reused_tokens": 0, "estimated_cache_hit_pct": 0.0}
        return text, tokens, 1, cache

    def _run_agentic(
        self, args: dict, material: str, delegation_id: str
    ) -> tuple[str, dict[str, int], int, str, str, dict]:
        """A full bash tool loop against the shared testbed."""
        minion_model_kwargs = {
            **self.minion_model_kwargs,
            "model_kwargs": {
                **self.minion_model_kwargs.get("model_kwargs", {}),
                "extra_body": {"session_id": f"minion-{self.run_id}-{delegation_id}"},
            },
        }
        minion_model = LitellmModel(**minion_model_kwargs)
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

        # Normalise optional fields the schema allows to be omitted — Jinja's StrictUndefined
        # (as mini-swe-agent's own templates use) errors on a missing key, not just a falsy value.
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

        # Persist the delegation's actual output. It was previously in-memory only
        # (self.delegation_outputs), which made post-hoc localization-coverage scoring
        # impossible — the thing that lets 5 instances yield ~30 observations instead
        # of 5 bits. See orchestrator/coverage.py.
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

        # Gru is asked to prefer work that displaces many tokens for little judgement. It can
        # only act on that if it is told what each delegation actually cost.
        cost_line = (
            f"[{delegation_id} cost: {tokens['total_tokens']:,} tokens, {n_calls} model call"
            f"{'' if n_calls == 1 else 's'}, mode={mode}]"
        )

        if returns == "verdict":
            passed, check_output = self._run_checks(args["verification"]["checks"])
            self.delegation_outputs[delegation_id] = submission  # kept for a later inputs.from (summary + patch)
            summary, _ = _split_verdict_submission(submission)
            status = "PASS" if passed else "FAIL"
            observation = (
                f"Delegation {delegation_id}: {status}\n{cost_line}\n\n"
                f"What the minion did:\n{summary}\n\n"
                f"{check_output}\n\n"
                "(The PASS/FAIL above comes from independently re-running your verification checks, not "
                "the minion's own claim — trust that, not the summary, for whether it actually worked. The "
                "summary is so you're never delegating into a black box: use it to decide what to do next, "
                "especially on FAIL, or to judge whether your checks were even the right ones to write.)"
            )
            return {"output": observation, "returncode": 0 if passed else 1, "exception_info": ""}

        self.delegation_outputs[delegation_id] = submission
        observation = f"Delegation {delegation_id} findings:\n{cost_line}\n\n{submission}"
        return {"output": observation, "returncode": 0, "exception_info": ""}

    def _finish(self, args: dict) -> dict[str, Any]:
        """A failing final_verification must NOT end the session — that's the signal for Gru to
        reconsider its approach and keep working, not a terminal state."""
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
