"""Gru's model wrapper: same as LitellmModel, but offers delegate_to_minion/finish
instead of the hardcoded bash tool. Everything else (retry, cost tracking, message
prep) is inherited unmodified from LitellmModel.

Revised 2026-08-25 (exp5 start): takes an optional `run_id` and sets
`model_kwargs["extra_body"]["session_id"]` itself, rather than requiring every call
site to hand-construct that dict — the bug that motivated this: run_session.py set
it correctly, but tests/harness.py's separate GruModel construction silently didn't,
so a naive test would have shown Gru's own calls with no session_id at all. Owning it
here means any caller gets consistent behavior for free. See gru_environment.py's
matching note for why session_id exists (OpenRouter sticky-routing, exp4's cache data).

Revised 2026-08-25 (exp5 start, again): `_calculate_cost` now prefers the response's
own real reported cost (`orchestrator.metrics.real_cost`) over LitellmModel's own calculator,
which prices from a static registry that doesn't know every model — caught live when
`openrouter/qwen/qwen3-max`'s real $0.0017/call was silently tracked as $0.0, making
`--cost-limit` a no-op. See real_cost.py for the full story.
"""

import litellm

from minisweagent.exceptions import FormatError
from minisweagent.models.litellm_model import LitellmModel

from orchestrator.gru.toolcall import ToolPolicy, build_tools, format_gru_observation_messages, parse_gru_actions
from orchestrator.metrics.real_cost import real_completion_cost


class GruModel(LitellmModel):
    def __init__(self, *, policy: ToolPolicy | None = None, run_id: str = "test-session", **kwargs):
        super().__init__(**kwargs)
        # Which of Gru's actions/fields this session actually offers — added 2026-08-24
        # for bit-by-bit prompt experimentation (orchestrator/gru/prompts.py).
        # Defaults to the original fully-permissive behavior.
        self._policy = policy or ToolPolicy()
        self._tools = build_tools(self._policy)
        # Stable for Gru's whole session — every one of Gru's own turns shares this,
        # unlike each delegation's own distinct session_id (see gru_environment.py).
        self.config.model_kwargs = {
            **self.config.model_kwargs,
            "extra_body": {"session_id": f"gru-{run_id}"},
        }
        # Consecutive FormatErrors on this model instance (one per Gru session), so
        # parse_gru_actions can escalate its correction text instead of repeating the same
        # message every retry — see gru_toolcall.py's _escalation_prefix. Reset on any clean
        # parse, incremented on any FormatError, tracked here (not on the mini-swe-agent
        # DefaultAgent) because this is the only object both sides of that call share.
        self._consecutive_format_errors = 0

    def _query(self, messages: list[dict[str, str]], **kwargs):
        try:
            return litellm.completion(
                model=self.config.model_name,
                messages=messages,
                tools=self._tools,
                **(self.config.model_kwargs | kwargs),
            )
        except litellm.exceptions.AuthenticationError as e:
            e.message += " You can permanently set your API key with `mini-extra config set KEY VALUE`."
            raise e

    def _calculate_cost(self, response) -> dict[str, float]:
        real_cost = real_completion_cost(response)
        if real_cost is not None:
            return {"cost": real_cost}
        return super()._calculate_cost(response)

    def _parse_actions(self, response) -> list[dict]:
        tool_calls = response.choices[0].message.tool_calls or []
        try:
            actions = parse_gru_actions(
                tool_calls,
                format_error_template=self.config.format_error_template,
                template_kwargs={"finish_reason": response.choices[0].finish_reason},
                consecutive_format_errors=self._consecutive_format_errors,
                policy=self._policy,
            )
        except FormatError:
            self._consecutive_format_errors += 1
            raise
        self._consecutive_format_errors = 0
        return actions

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        return format_gru_observation_messages(
            actions=actions,
            outputs=outputs,
            observation_template=self.config.observation_template,
            template_vars=template_vars,
        )
