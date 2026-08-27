"""Gru's "environment": doesn't run bash itself, dispatches Gru's four actions —
delegate_to_minion, think, run_check and finish. See prompts/README.md and
prompts/gru-loop.md for the design this implements.

This class is benchmark-agnostic. Everything here is the architecture proper — the same
four actions, the same delegation bookkeeping, the same cost reporting — regardless of
what is underneath. A benchmark subclasses it (orchestrator/benchmarks/) and supplies
the one thing that genuinely differs: what a passing `finish()` submits. SWE-bench
submits a `git diff` against the testbed's starting commit; GAIA submits the final
check's own stdout. Nothing else about Gru's loop is allowed to vary — one architecture,
one prompt, only the benchmark underneath changes.

Revised 2026-08-22 alongside orchestrator/gru/toolcall.py:

- **Delegation shape is chosen by Gru, not by our taxonomy.** `returns` decides
  what comes back (content vs. a pass/fail computed here from real checks);
  `mode` decides what it costs (a single model call vs. a full bash loop).
- **`mode="oneshot"` exists because exp2 ran every delegation as a 40-step agentic
  loop.** See orchestrator/minion/runner.py, which now owns both modes.
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

Revised 2026-08-26: split into this benchmark-agnostic base plus per-benchmark
subclasses, and the minion side moved out to orchestrator/minion/runner.py. Before this
the GAIA environment was a near-byte-identical copy of the SWE-bench one, differing only
in `finish()`'s extraction step — two copies of the delegation loop, the cost accounting
and the observation wording, waiting to drift apart.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent
from minisweagent.exceptions import Submitted

from orchestrator.minion.runner import MinionRunner, split_verdict_submission


@dataclass
class CheckResult:
    """The outcome of running a list of check commands. `last_stdout` is the last
    check's own raw output — harness-internal, not part of the shared prompt; GAIA's
    finish() uses it as the extracted answer (see benchmarks/gaia.py)."""

    passed: bool
    output: str
    last_stdout: str = ""


class GruEnvironment:
    def __init__(
        self,
        *,
        env: Any,
        minions: MinionRunner,
        output_dir: Path | None = None,
        logger: logging.Logger | None = None,
        run_id: str = "test-session",
    ):
        # The one shared, persistent testbed/sandbox: Gru's own check commands and every
        # minion delegation run against this same container.
        self.env = env
        self.minions = minions
        self.output_dir = output_dir
        self.logger = logger or logging.getLogger("gru.environment")
        self.run_id = run_id
        # Set by the session runner right after the DefaultAgent(gru_model, self, ...) that
        # owns this environment is constructed — can't be passed in __init__ since Gru's
        # agent doesn't exist yet at that point. Used only to surface each turn's own token
        # cost (see _turn_cost_line); a not-yet-wired or empty agent degrades to no cost line.
        self.gru_agent: DefaultAgent | None = None

        self.delegation_outputs: dict[str, str] = {}  # id -> raw content, for inputs.from passthrough
        self.delegation_counter = 0
        # per-role cost accounting (see prompts/README.md "Cost attribution")
        self.minion_records: list[dict[str, Any]] = []
        self.gru_action_log: list[dict[str, Any]] = []

        self.setup()

    # -- benchmark hooks --

    def setup(self) -> None:
        """Runs once, before Gru's session takes any action. Override to capture whatever
        the benchmark's own submission extraction will need later (SWE-bench: the starting
        commit)."""

    def build_submission(self, final_checks: CheckResult) -> str:
        """What a passing finish() actually submits, given the final_verification run.
        The one genuinely per-benchmark step in Gru's loop."""
        raise NotImplementedError

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
        raise ValueError(f"{type(self).__name__} cannot execute action of kind {kind!r}")

    def _next_id(self) -> str:
        self.delegation_counter += 1
        return f"t{self.delegation_counter}"

    def _run_checks(self, checks: list[str]) -> CheckResult:
        """Run check commands directly against the shared testbed. Real, independent
        pass/fail — never trusts a minion's own report on whether its own work passed."""
        if not checks:
            return CheckResult(True, "(no checks specified)")
        outputs = []
        all_passed = True
        last_stdout = ""
        for check_cmd in checks:
            out = self.env.execute({"command": check_cmd})
            ok = out["returncode"] == 0
            all_passed = all_passed and ok
            outputs.append(f"$ {check_cmd}\n(exit {out['returncode']})\n{out['output'][-2000:]}")
            last_stdout = out["output"].strip()
        return CheckResult(all_passed, "\n\n".join(outputs), last_stdout)

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
        result = self._run_checks(args.get("checks", []))
        status = "PASS" if result.passed else "FAIL"
        return {
            "output": f"Checks: {status}{self._turn_cost_line()}\n\n{result.output}",
            "returncode": 0 if result.passed else 1,
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
            out = self.env.execute({"command": f"cat {path}"})
            body = out["output"] if out["returncode"] == 0 else f"[could not read: exit {out['returncode']}]"
            parts.append(f"--- {path} ---\n{body}")
        return "\n\n".join(parts) if parts else "(none)"

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

        result = self.minions.run(args, material, delegation_id)

        # Persist the delegation's actual output. It was previously in-memory only
        # (self.delegation_outputs), which made post-hoc localization-coverage scoring
        # impossible — the thing that lets 5 instances yield ~30 observations instead
        # of 5 bits. See orchestrator/metrics/coverage.py.
        output_path = None
        if self.output_dir is not None:
            output_path = self.output_dir / "delegations" / f"{delegation_id}.txt"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result.submission or "")

        self.minion_records.append(
            {
                "delegation_id": delegation_id,
                "returns": returns,
                "mode": mode,
                "description": args["description"],
                "scope": args["inputs"].get("scope", ""),
                "api_calls": result.api_calls,
                **result.tokens,
                "exit_status": result.exit_status,
                "trajectory_path": result.trajectory_path or None,
                "output_path": str(output_path) if output_path else None,
                "cache": result.cache,
            }
        )

        # Gru is asked to prefer work that displaces many tokens for little judgement. It can
        # only act on that if it is told what each delegation actually cost.
        cost_line = (
            f"[{delegation_id} cost: {result.tokens['total_tokens']:,} tokens, {result.api_calls} model call"
            f"{'' if result.api_calls == 1 else 's'}, mode={mode}]"
        )
        self.delegation_outputs[delegation_id] = result.submission  # kept for a later inputs.from

        if returns == "verdict":
            checks = self._run_checks(args["verification"]["checks"])
            summary, _ = split_verdict_submission(result.submission)
            status = "PASS" if checks.passed else "FAIL"
            observation = (
                f"Delegation {delegation_id}: {status}\n{cost_line}\n\n"
                f"What the minion did:\n{summary}\n\n"
                f"{checks.output}\n\n"
                "(The PASS/FAIL above comes from independently re-running your verification checks, not "
                "the minion's own claim — trust that, not the summary, for whether it actually worked. The "
                "summary is so you're never delegating into a black box: use it to decide what to do next, "
                "especially on FAIL, or to judge whether your checks were even the right ones to write.)"
            )
            return {"output": observation, "returncode": 0 if checks.passed else 1, "exception_info": ""}

        observation = f"Delegation {delegation_id} findings:\n{cost_line}\n\n{result.submission}"
        return {"output": observation, "returncode": 0, "exception_info": ""}

    def _finish(self, args: dict) -> dict[str, Any]:
        """A failing final_verification must NOT end the session — that's the signal for Gru to
        reconsider its approach and keep working, not a terminal state."""
        checks = self._run_checks(args.get("final_verification", {}).get("checks", []))

        self.logger.info(f"finish attempt: final_verification {'PASSED' if checks.passed else 'FAILED'}")

        if checks.passed:
            raise Submitted(
                {
                    "role": "exit",
                    "content": args.get("summary", ""),
                    "extra": {
                        "exit_status": "Submitted",
                        "submission": self.build_submission(checks),
                        "final_verification_passed": True,
                        "final_verification_output": checks.output,
                    },
                }
            )

        observation = (
            "finish() rejected: final_verification failed.\n\n"
            f"{checks.output}\n\n"
            "This means the overall decomposition was wrong somewhere, not one isolated step — "
            "reconsider your approach broadly rather than patching the last delegation. "
            "You still have everything you've learned so far; this session continues."
        )
        return {"output": observation, "returncode": 1, "exception_info": ""}
