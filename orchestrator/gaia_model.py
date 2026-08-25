"""Gru's model wrapper for GAIA — same pattern as orchestrator/gru_model.py, wired to
gaia_tools instead of gru_toolcall. See that file's docstring for the session_id and
real-cost rationale, unchanged here.
"""

import litellm

from minisweagent.exceptions import FormatError
from minisweagent.models.litellm_model import LitellmModel

from orchestrator.gaia_tools import GaiaToolPolicy, build_tools, format_gaia_observation_messages, parse_gaia_actions
from orchestrator.real_cost import real_completion_cost


class GaiaModel(LitellmModel):
    def __init__(self, *, policy: GaiaToolPolicy | None = None, run_id: str = "test-session", **kwargs):
        super().__init__(**kwargs)
        self._policy = policy or GaiaToolPolicy()
        self._tools = build_tools(self._policy)
        self.config.model_kwargs = {
            **self.config.model_kwargs,
            "extra_body": {"session_id": f"gru-{run_id}"},
        }
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
            actions = parse_gaia_actions(
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
        return format_gaia_observation_messages(
            actions=actions,
            outputs=outputs,
            observation_template=self.config.observation_template,
            template_vars=template_vars,
        )
