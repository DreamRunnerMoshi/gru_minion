"""Fake `litellm.completion` for testing the Gru/minion harness without a real model.

Both GruModel, GruEnvironment's oneshot path, and the minion's LitellmModel all call
`litellm.completion(...)` directly (see orchestrator/gru_model.py, gru_environment.py,
and minisweagent's litellm_model.py) — always via the `litellm` module attribute, never
a `from litellm import completion` import. That means patching `litellm.completion`
itself (not a per-module reference) intercepts every one of them uniformly, which is
what ScriptedLLM below relies on: one ordered queue sees every call, Gru's and every
minion's, in the exact order the harness actually issues them.

Real litellm.types.utils.ModelResponse objects are constructed (not a hand-rolled
stand-in) so every downstream consumer — parse_gru_actions' tool_calls access,
response.model_dump() for trajectory persistence, getattr(response, "usage", None) for
token accounting — sees the same shape it would against a real API response.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from litellm.types.utils import ChatCompletionMessageToolCall, Choices, Function, Message, ModelResponse, Usage


@dataclass
class Tool:
    """Script a turn that calls one tool. `name` is the tool/function name
    (delegate_to_minion/think/run_check/finish for Gru, or "bash" for a minion)."""

    name: str
    args: dict = field(default_factory=dict)


@dataclass
class Text:
    """Script a turn with no tool call at all — the dominant real-world trigger for
    RepeatedFormatError (see experiments/exp3/LOG.md): the model writes prose instead
    of calling a tool."""

    content: str = "Looks good, the fix is complete."


Step = Tool | Text | Callable[[int, list, list | None], "Tool | Text"]


def _tool_response(name: str, args: dict, *, prompt_tokens: int, completion_tokens: int) -> ModelResponse:
    tc = ChatCompletionMessageToolCall(id=f"call_{name}", type="function", function=Function(name=name, arguments=json.dumps(args)))
    msg = Message(role="assistant", content=None, tool_calls=[tc])
    choice = Choices(index=0, message=msg, finish_reason="tool_calls")
    usage = Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=prompt_tokens + completion_tokens)
    return ModelResponse(id="mock", choices=[choice], created=int(time.time()), model="mock", object="chat.completion", usage=usage)


def _text_response(content: str, *, prompt_tokens: int, completion_tokens: int) -> ModelResponse:
    msg = Message(role="assistant", content=content, tool_calls=None)
    choice = Choices(index=0, message=msg, finish_reason="stop")
    usage = Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=prompt_tokens + completion_tokens)
    return ModelResponse(id="mock", choices=[choice], created=int(time.time()), model="mock", object="chat.completion", usage=usage)


class ScriptExhausted(AssertionError):
    pass


class ScriptedLLM:
    """Drop-in replacement for `litellm.completion`, scripted call by call.

    One ordered queue for the whole session, Gru and minion turns interleaved exactly
    as the real harness would issue them — script the minion's turns right after the
    delegation that spawns it, then resume Gru's turns after the minion submits. This
    isn't a simplification: it's the same ordering the harness itself imposes (Gru
    blocks on delegate_to_minion until the minion agent's run() returns), so a test's
    step list reads as a literal transcript of the session under test.

    Every call is recorded in `.calls` (model/messages/tools/kwargs) for assertions —
    e.g. checking the escalation text actually reached the model on a later turn.
    """

    def __init__(self, steps: list[Step], *, prompt_tokens: int = 100, completion_tokens: int = 20):
        self._steps = list(steps)
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, model: str, messages: list, tools: list | None = None, **kwargs) -> ModelResponse:
        idx = len(self.calls)
        self.calls.append({"model": model, "messages": messages, "tools": tools, "kwargs": kwargs})
        if idx >= len(self._steps):
            raise ScriptExhausted(
                f"ScriptedLLM exhausted after {idx} calls — the script needs more steps. "
                f"Last messages: {messages[-2:]!r}"
            )
        step = self._steps[idx]
        if not isinstance(step, (Tool, Text)):
            step = step(idx, messages, tools)
        if isinstance(step, Tool):
            return _tool_response(step.name, step.args, prompt_tokens=self._prompt_tokens, completion_tokens=self._completion_tokens)
        if isinstance(step, Text):
            return _text_response(step.content, prompt_tokens=self._prompt_tokens, completion_tokens=self._completion_tokens)
        raise TypeError(f"script step must resolve to Tool or Text, got {type(step)}")


def bash(command: str) -> Tool:
    """Shorthand for a minion's bash tool call."""
    return Tool("bash", {"command": command})


def submit(read_command: str) -> Tool:
    """Shorthand for a minion ending its turn: mini-swe-agent's LocalEnvironment treats
    a bash command whose first output line is COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT as
    Submitted (see minion.yaml's own instructions to the model — "echo
    COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat findings.md" — and
    minisweagent.environments.local.LocalEnvironment._check_finished). `read_command`
    is whatever prints the submission body, e.g. "cat findings.md" or "cat patch.txt"."""
    return bash(f"echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && {read_command}")
