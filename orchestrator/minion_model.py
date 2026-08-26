"""The minion's model wrapper for agentic-mode delegations: identical to LitellmModel,
except cost tracking prefers the response's own real reported cost over LitellmModel's
static-registry-based calculator — see orchestrator/real_cost.py and gru_model.py's
matching 2026-08-25 revision note for why this exists (caught live: a model outside
litellm's static registry silently tracked as $0.0 cost, making --minion-cost-limit a
no-op for it).
"""

from minisweagent.models.litellm_model import LitellmModel

from orchestrator.real_cost import real_completion_cost


class MinionModel(LitellmModel):
    def _calculate_cost(self, response) -> dict[str, float]:
        real_cost = real_completion_cost(response)
        if real_cost is not None:
            return {"cost": real_cost}
        return super()._calculate_cost(response)
