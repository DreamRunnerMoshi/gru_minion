"""Runs one delegation. This is the whole of the minion side of the architecture:
Gru's environment decides *that* a delegation happens and what to do with the result;
everything about *how* a minion executes lives here.

Extracted 2026-08-26 from orchestrator/gru/environment.py (then GruEnvironment) and its
byte-identical copy in the GAIA environment. The two benchmarks never differed in how a
minion runs — only in what the harness does with a finished session — so a second copy
was pure duplication waiting to drift.

The two modes are the ones Gru chooses between (see gru/toolcall.py's `mode` field):

- `oneshot` — a single model call: text in, text out, no shell. Exists because exp2 ran
  every delegation as a 40-step agentic loop; t1 spent 105,770 tokens to read one
  317-line file and summarise it, work that is one completion. Delegating menial work
  has to be *cheaper* than doing it inline or the criterion is unprofitable to follow.
- `agentic` — mini-swe-agent's stock bash tool loop against the shared testbed/sandbox.

Both carry an OpenRouter `session_id` of `minion-{run_id}-{delegation_id}`, stable
across that one delegation's own turns: each delegation is its own conversation with
its own prefix, not a continuation of Gru's. Without an explicit session_id OpenRouter
derives its sticky-routing key by hashing the opening messages, and a growing agent
conversation changes that hash turn to turn, occasionally landing a request on a
backend other than the one holding the warm cache — exp4's cost data showed real,
provider-reported cache hit rate collapsing on up to 10 of 41 calls per run with no
correlation to wall-clock gaps. See experiments/exp5/NOTES.md.

`MinionModel` (orchestrator/minion/model.py) rather than mini-swe-agent's bare
LitellmModel: same class, except cost tracking prefers the response's own real reported
cost over litellm's static-registry calculator — `--minion-cost-limit` was silently a
no-op for `openrouter/qwen/qwen3-max` otherwise (real cost $0.0017/call, tracked $0.0).
See orchestrator/metrics/real_cost.py.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import litellm

from minisweagent.agents.default import DefaultAgent

from orchestrator.metrics.cache_stats import extract_cache_stats
from orchestrator.metrics.token_usage import extract_token_usage
from orchestrator.minion.model import MinionModel

VERDICT_SUMMARY_MARKER = "===PATCH==="

ONESHOT_SYSTEM = (
    "You are a minion — the execution role in a two-tier coding-agent system. You were handed exactly "
    "one bounded piece of work by Gru, the planning role, along with all the material needed to do it. "
    "You have no shell and no repository access: work only from the material below. Do the work and "
    "return exactly what the output contract asks for, nothing else — no preamble, no commentary."
)


def split_verdict_submission(submission: str) -> tuple[str, str]:
    """A verdict-mode minion submits summary.md then patch.txt, separated by
    VERDICT_SUMMARY_MARKER (see config/minion.yaml's Submission steps). Split them —
    Gru gets the summary, never the raw patch; the check result is still what decides
    pass/fail. No marker (e.g. a oneshot verdict, or a minion that didn't follow the
    ritual) degrades to treating the whole submission as the summary."""
    if VERDICT_SUMMARY_MARKER in submission:
        summary, _, patch = submission.partition(VERDICT_SUMMARY_MARKER)
        return summary.strip(), patch.strip()
    return submission.strip(), ""


@dataclass
class DelegationResult:
    """What one finished delegation reports back. `tokens`/`api_calls`/`cache` are the
    per-role cost accounting (see prompts/README.md "Cost attribution") — Gru is asked
    to prefer work that displaces many tokens for little judgement, which it can only
    act on if it is told what each delegation actually cost."""

    submission: str
    tokens: dict[str, int]
    api_calls: int
    exit_status: str = ""
    trajectory_path: str = ""
    cache: dict[str, Any] = field(default_factory=dict)


class MinionRunner:
    """Holds everything a delegation needs that doesn't change between delegations: the
    shared environment to run against, the minion's model/agent config, its prompts, and
    where trajectories land."""

    def __init__(
        self,
        *,
        env: Any,
        model_kwargs: dict[str, Any],
        agent_kwargs: dict[str, Any],
        system_template: str,
        instance_template: str,
        output_dir: Path | None = None,
        run_id: str = "test-session",
    ):
        self.env = env
        self.model_kwargs = model_kwargs
        self.agent_kwargs = agent_kwargs
        self.system_template = system_template
        self.instance_template = instance_template
        self.output_dir = output_dir
        self.run_id = run_id

    @classmethod
    def from_config(
        cls,
        config: dict,
        *,
        env: Any,
        model_name: str,
        api_base: str | None = None,
        cost_limit: float = 0.0,
        output_dir: Path | None = None,
        run_id: str = "test-session",
    ) -> "MinionRunner":
        """Build from a loaded minion config (config/minion.yaml or its GAIA sibling):
        the agent block minus its two prompt templates becomes the agent kwargs, the
        model block becomes the model kwargs. `cost_limit > 0` overrides the config's
        own (this is --minion-cost-limit: a hard, real per-delegation dollar cap
        enforced by mini-swe-agent, not advisory)."""
        agent_kwargs = {k: v for k, v in config["agent"].items() if k not in ("system_template", "instance_template")}
        if cost_limit > 0:
            agent_kwargs["cost_limit"] = cost_limit
        return cls(
            env=env,
            model_kwargs={
                "model_name": model_name,
                "model_kwargs": {**config["model"]["model_kwargs"], **({"api_base": api_base} if api_base else {})},
            },
            agent_kwargs=agent_kwargs,
            system_template=config["agent"]["system_template"],
            instance_template=config["agent"]["instance_template"],
            output_dir=output_dir,
            run_id=run_id,
        )

    def run(self, args: dict, material: str, delegation_id: str) -> DelegationResult:
        """Dispatch on the delegation's own `mode`. Anything that isn't "oneshot" is an
        agentic loop — gru/toolcall.py validates the field, so an unknown value never
        reaches here."""
        if args["mode"] == "oneshot":
            return self._run_oneshot(args, material, delegation_id)
        return self._run_agentic(args, material, delegation_id)

    def _session_id(self, delegation_id: str) -> str:
        return f"minion-{self.run_id}-{delegation_id}"

    def _run_oneshot(self, args: dict, material: str, delegation_id: str) -> DelegationResult:
        model_kwargs = {k: v for k, v in self.model_kwargs.get("model_kwargs", {}).items() if k != "parallel_tool_calls"}
        # A single call has nothing to route consistently against, but set it anyway for
        # consistency with agentic mode and in case oneshot ever grows a retry/second call.
        model_kwargs["extra_body"] = {"session_id": self._session_id(delegation_id)}
        prompt = (
            f"<task>\n{args['description']}\n</task>\n\n"
            f"<output_contract>\n{args['output_contract']}\n</output_contract>\n\n"
            f"<material>\n{material}\n</material>"
        )
        response = litellm.completion(
            model=self.model_kwargs["model_name"],
            messages=[{"role": "system", "content": ONESHOT_SYSTEM}, {"role": "user", "content": prompt}],
            **model_kwargs,
        )
        usage = getattr(response, "usage", None)
        tokens = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }
        return DelegationResult(
            submission=response.choices[0].message.content or "",
            tokens=tokens,
            api_calls=1,
            exit_status="Completed",
            # A oneshot is a single call with no prior context, so there is nothing a
            # prefix cache could reuse — recorded explicitly rather than left absent.
            cache={
                "n_calls": 1,
                "total_prompt_tokens": tokens["prompt_tokens"],
                "reported_cached_tokens": None,
                "reported_cache_hit_pct": None,
                "estimated_reused_tokens": 0,
                "estimated_cache_hit_pct": 0.0,
            },
        )

    def _run_agentic(self, args: dict, material: str, delegation_id: str) -> DelegationResult:
        model = MinionModel(
            **{
                **self.model_kwargs,
                "model_kwargs": {
                    **self.model_kwargs.get("model_kwargs", {}),
                    "extra_body": {"session_id": self._session_id(delegation_id)},
                },
            }
        )
        output_path = None
        if self.output_dir is not None:
            output_path = self.output_dir / "minions" / f"{delegation_id}.traj.json"
        agent = DefaultAgent(
            model,
            self.env,
            system_template=self.system_template,
            instance_template=self.instance_template,
            output_path=output_path,
            **self.agent_kwargs,
        )
        result = agent.run(subtask=args, prior_delegation_outputs=material)
        return DelegationResult(
            submission=result.get("submission", ""),
            tokens=extract_token_usage(agent.messages),
            api_calls=agent.n_calls,
            exit_status=result.get("exit_status", ""),
            trajectory_path=str(output_path) if output_path else "",
            cache=extract_cache_stats(agent.messages),
        )
