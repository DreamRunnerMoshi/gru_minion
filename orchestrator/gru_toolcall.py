"""Tool schemas and action parsing for Gru's loop.

Mirrors minisweagent.models.utils.actions_toolcall (which hardcodes a single
"bash" tool) but supports Gru's two tools instead: delegate_to_minion and
finish. See prompts/gru-loop.md for the design rationale and prompts/README.md
for why Gru is a continuous loop with these two actions, not an upfront batch
plan.
"""

import json
import time

from jinja2 import StrictUndefined, Template

from minisweagent.exceptions import FormatError

DELEGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_to_minion",
        "description": (
            "Hand a bounded, scoped piece of work to a minion. Use this whenever the next thing "
            "needed is mechanical, non-reasoning, and something a check can confirm was done right."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["context_gather", "locate", "synthesize"],
                    "description": "context_gather/locate return findings; synthesize returns pass/fail only.",
                },
                "description": {
                    "type": "string",
                    "description": "Outcome-oriented — what must be true / what must come back when this is done.",
                },
                "inputs": {
                    "type": "object",
                    "properties": {
                        "from": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "ids of earlier delegations this depends on, if any.",
                        },
                        "scope": {
                            "type": "string",
                            "description": "Path or boundary the minion is allowed to operate within.",
                        },
                    },
                    "required": ["scope"],
                },
                "search_strategy": {
                    "type": "string",
                    "description": "Required for context_gather/locate. Omit for synthesize.",
                },
                "verification": {
                    "type": "object",
                    "properties": {
                        "checks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Shell commands; exit code 0 means pass. Required for synthesize.",
                        }
                    },
                },
                "output_contract": {
                    "type": "string",
                    "description": "What this delegation hands back.",
                },
            },
            "required": ["type", "description", "inputs", "output_contract"],
        },
    },
}

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Declare the task complete. final_verification.checks must be self-authored (a reproduction "
            "case + the existing test suite) — you do not have access to the real hidden evaluation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was actually done, in your own words."},
                "final_verification": {
                    "type": "object",
                    "properties": {
                        "checks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Shell commands; exit code 0 means pass.",
                        }
                    },
                    "required": ["checks"],
                },
            },
            "required": ["summary", "final_verification"],
        },
    },
}

_TOOL_NAMES = {"delegate_to_minion", "finish"}

_DELEGATE_REQUIRED = ("type", "description", "inputs", "output_contract")
_DELEGATE_TYPES = {"context_gather", "locate", "synthesize"}


def _format_error(format_error_template: str, *, error: str, has_tool_calls: bool, template_kwargs: dict) -> dict:
    return {
        "role": "user",
        "content": Template(format_error_template, undefined=StrictUndefined).render(
            error=error, actions=[], has_tool_calls=has_tool_calls, **template_kwargs
        ),
        "extra": {"interrupt_type": "FormatError"},
    }


def parse_gru_actions(tool_calls: list, *, format_error_template: str, template_kwargs: dict | None = None) -> list[dict]:
    """Parse Gru's tool calls into action dicts. Raises FormatError on malformed/unknown calls."""
    template_kwargs = template_kwargs or {}
    if not tool_calls:
        raise FormatError(
            _format_error(
                format_error_template,
                error="No tool calls found in the response. Every response MUST include exactly one tool call (delegate_to_minion or finish).",
                has_tool_calls=False,
                template_kwargs=template_kwargs,
            )
        )

    actions = []
    for tool_call in tool_calls:
        name = tool_call.function.name
        error_msg = ""
        args: dict = {}
        try:
            parsed = json.loads(tool_call.function.arguments)
        except Exception as e:
            parsed = None
            error_msg = f"Error parsing tool call arguments: {e}. "

        if not error_msg and not isinstance(parsed, dict):
            error_msg = f"Tool call arguments must be a JSON object, got {type(parsed).__name__}."
        elif not error_msg:
            args = parsed

        if not error_msg and name not in _TOOL_NAMES:
            error_msg = f"Unknown tool '{name}'. Must be one of {sorted(_TOOL_NAMES)}."

        if not error_msg and name == "delegate_to_minion":
            missing = [k for k in _DELEGATE_REQUIRED if k not in args]
            inputs = args.get("inputs")
            inputs = inputs if isinstance(inputs, dict) else {}
            verification = args.get("verification")
            verification = verification if isinstance(verification, dict) else {}
            if missing:
                error_msg = f"delegate_to_minion missing required field(s): {missing}."
            elif args.get("type") not in _DELEGATE_TYPES:
                error_msg = f"delegate_to_minion 'type' must be one of {sorted(_DELEGATE_TYPES)}, got {args.get('type')!r}."
            elif not isinstance(args.get("inputs"), dict):
                error_msg = f"delegate_to_minion.inputs must be a JSON object with a 'scope' field, got {type(args.get('inputs')).__name__}."
            elif "scope" not in inputs:
                error_msg = "delegate_to_minion.inputs missing required 'scope'."
            elif args["type"] in ("context_gather", "locate") and not args.get("search_strategy"):
                error_msg = f"delegate_to_minion with type={args['type']!r} requires a non-empty 'search_strategy'."
            elif args["type"] == "synthesize" and not verification.get("checks"):
                error_msg = "delegate_to_minion with type='synthesize' requires at least one verification.checks entry (as an object: {\"checks\": [...]})."

        if not error_msg and name == "finish":
            final_verification = args.get("final_verification")
            if "summary" not in args:
                error_msg = "finish missing required field 'summary'."
            elif not isinstance(final_verification, dict):
                error_msg = f"finish.final_verification must be a JSON object with a 'checks' field (e.g. {{\"checks\": [...]}}), got {type(final_verification).__name__}."
            elif not final_verification.get("checks"):
                error_msg = "finish.final_verification.checks must be non-empty — see prompts/gru-loop.md for why this can't be skipped."

        if error_msg:
            raise FormatError(
                _format_error(
                    format_error_template,
                    error=error_msg.strip(),
                    has_tool_calls=True,
                    template_kwargs=template_kwargs,
                )
            )

        actions.append({"kind": name, "args": args, "tool_call_id": tool_call.id})

    return actions


def format_gru_observation_messages(
    *,
    actions: list[dict],
    outputs: list[dict],
    observation_template: str,
    template_vars: dict | None = None,
) -> list[dict]:
    """Format GruEnvironment.execute() outputs into tool result messages. Same shape as
    minisweagent.models.utils.actions_toolcall.format_toolcall_observation_messages, generalized
    to actions keyed by "kind"/"args" instead of assuming a bash "command"."""
    not_executed = {"output": "", "returncode": -1, "exception_info": "action was not executed"}
    padded_outputs = outputs + [not_executed] * (len(actions) - len(outputs))
    results = []
    for action, output in zip(actions, padded_outputs):
        content = Template(observation_template, undefined=StrictUndefined).render(
            output=output, **(template_vars or {})
        )
        msg = {
            "content": content,
            "role": "tool",
            "tool_call_id": action["tool_call_id"],
            "extra": {
                "raw_output": output.get("output", ""),
                "returncode": output.get("returncode"),
                "timestamp": time.time(),
                "exception_info": output.get("exception_info"),
                **output.get("extra", {}),
            },
        }
        results.append(msg)
    return results
