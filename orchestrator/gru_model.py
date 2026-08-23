"""Gru's model wrapper: same as LitellmModel, but offers delegate_to_minion/finish
instead of the hardcoded bash tool. Everything else (retry, cost tracking, message
prep) is inherited unmodified from LitellmModel.
"""

import litellm

from minisweagent.models.litellm_model import LitellmModel

from orchestrator.gru_toolcall import GRU_TOOLS, format_gru_observation_messages, parse_gru_actions


class GruModel(LitellmModel):
    def _query(self, messages: list[dict[str, str]], **kwargs):
        try:
            return litellm.completion(
                model=self.config.model_name,
                messages=messages,
                tools=GRU_TOOLS,
                **(self.config.model_kwargs | kwargs),
            )
        except litellm.exceptions.AuthenticationError as e:
            e.message += " You can permanently set your API key with `mini-extra config set KEY VALUE`."
            raise e

    def _parse_actions(self, response) -> list[dict]:
        tool_calls = response.choices[0].message.tool_calls or []
        return parse_gru_actions(
            tool_calls,
            format_error_template=self.config.format_error_template,
            template_kwargs={"finish_reason": response.choices[0].finish_reason},
        )

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
