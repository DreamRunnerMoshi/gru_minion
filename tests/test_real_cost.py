"""2026-08-25 (exp5): caught mid-batch against openrouter/qwen/qwen3-max — mini-swe-agent's
own cost tracking (litellm.cost_calculator.completion_cost, a static local price table)
silently tracked $0.0 for a call OpenRouter actually billed $0.0017 for, because the model
isn't in that static table and MSWEA_COST_TRACKING=ignore_errors swallows the failure.
That makes --cost-limit/--minion-cost-limit a silent no-op for any such model. GruModel
and MinionModel now prefer the response's own real reported cost instead.
"""

from litellm.types.utils import ChatCompletionMessageToolCall, Choices, Function, Message, ModelResponse, Usage

from orchestrator.gru.model import GruModel
from orchestrator.minion.model import MinionModel
from orchestrator.metrics.real_cost import real_completion_cost


def _response(usage: Usage) -> ModelResponse:
    tc = ChatCompletionMessageToolCall(id="call_1", type="function", function=Function(name="finish", arguments="{}"))
    msg = Message(role="assistant", content=None, tool_calls=[tc])
    choice = Choices(index=0, message=msg, finish_reason="tool_calls")
    return ModelResponse(id="mock", choices=[choice], created=0, model="mock", object="chat.completion", usage=usage)


def test_real_completion_cost_reads_the_response_field():
    resp = _response(Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120, cost=0.0017))
    assert real_completion_cost(resp) == 0.0017


def test_real_completion_cost_is_none_when_the_field_is_absent():
    resp = _response(Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120))
    assert real_completion_cost(resp) is None


def test_gru_model_prefers_real_cost_over_the_static_calculator():
    model = GruModel(model_name="mock/gru")
    resp = _response(Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120, cost=0.0017))
    assert model._calculate_cost(resp) == {"cost": 0.0017}


def test_minion_model_prefers_real_cost_over_the_static_calculator():
    model = MinionModel(model_name="mock/minion")
    resp = _response(Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120, cost=0.0017))
    assert model._calculate_cost(resp) == {"cost": 0.0017}


def test_gru_model_falls_back_when_no_real_cost_is_present(monkeypatch):
    # Self-hosted/Ollama-style response: no usage.cost field at all. Must not crash, and
    # must fall back to the original calculator's own error-handling (ignore_errors -> 0.0)
    # rather than raising — this is the path every existing DeepSeek/Ollama run still uses.
    monkeypatch.setenv("MSWEA_COST_TRACKING", "ignore_errors")
    model = GruModel(model_name="mock/gru", cost_tracking="ignore_errors")
    resp = _response(Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120))
    result = model._calculate_cost(resp)
    assert result == {"cost": 0.0}
