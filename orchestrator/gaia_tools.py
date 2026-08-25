"""Tool schemas and action parsing for Gru's loop on GAIA — the SWE-bench sibling is
orchestrator/gru_toolcall.py. Same shapes (delegate_to_minion, think, finish, exactly
one action per turn) reused where they're genuinely domain-agnostic; `run_check`
(shell against a git testbed) is replaced with `web_search` + `python_exec` (this
pilot's tool budget: search + code execution, no file/image/audio parsing — see
orchestrator/gaia_dataset.py), and `finish` drops SWE-bench's final_verification.checks
requirement (there's no hidden test suite to self-check against on GAIA; the check is
exact-match against a hidden gold answer, done only at evaluation time) in favor of a
required `answer` field, since GAIA scores the ANSWER, not a diff.
"""

import copy
import json
import time
from dataclasses import dataclass

from jinja2 import StrictUndefined, Template

from minisweagent.exceptions import FormatError

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web. Returns a list of results (title, url, snippet).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
            },
            "required": ["query"],
        },
    },
}

PYTHON_EXEC_TOOL = {
    "type": "function",
    "function": {
        "name": "python_exec",
        "description": "Run Python code in a sandbox and see stdout/stderr. Use for calculation, "
        "text processing, or fetching/parsing a specific URL. No persistent state between calls "
        "beyond files written to disk in the sandbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to execute."},
            },
            "required": ["code"],
        },
    },
}

DELEGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_to_minion",
        "description": (
            "Hand a bounded piece of work to a cheaper model. Use this for work that consumes many "
            "tokens but little judgement. You keep responsibility for the task; the minion only does "
            "the piece you describe."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Outcome-oriented — what must be true / what must come back when this is done.",
                },
                "returns": {
                    "type": "string",
                    "enum": ["findings", "verdict"],
                    "description": (
                        "'findings' returns the minion's actual output to you. 'verdict' returns only "
                        "pass/fail from your verification.checks, run independently by the orchestrator "
                        "— use it whenever a real check (e.g. re-running a computation) can settle whether "
                        "the work succeeded."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["oneshot", "agentic"],
                    "description": (
                        "'oneshot' is a single model call — text in, text out, no tools. Far cheaper. "
                        "Use it for transforming or compressing material you already have. "
                        "'agentic' gives the minion its own search/python_exec loop to go find or compute something."
                    ),
                },
                "inputs": {
                    "type": "object",
                    "properties": {
                        "from": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "ids of earlier delegations whose output this one needs.",
                        },
                        "read_paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Files the orchestrator should read and hand to the minion verbatim. "
                                "Mainly for mode='oneshot', which has no tools of its own."
                            ),
                        },
                        "scope": {
                            "type": "string",
                            "description": "What this minion is bounded to — a topic, a URL, a specific sub-question.",
                        },
                    },
                    "required": ["scope"],
                },
                "verification": {
                    "type": "object",
                    "properties": {
                        "checks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Python snippets; must run without raising and print a truthy "
                            "result on the last line to pass. Required when returns='verdict'.",
                        }
                    },
                },
                "output_contract": {
                    "type": "string",
                    "description": "What this delegation hands back, and in what shape.",
                },
            },
            "required": ["description", "returns", "mode", "inputs", "output_contract"],
        },
    },
}

THINK_TOOL = {
    "type": "function",
    "function": {
        "name": "think",
        "description": (
            "Spend a turn reasoning without delegating anything. Use this when the next thing needed "
            "is a decision rather than work — weighing conflicting search results, or deciding whether "
            "what you have is enough to answer. Nothing is executed and nothing is charged to a minion."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "The reasoning or decision you are recording."}
            },
            "required": ["note"],
        },
    },
}

FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Submit your final answer. GAIA scores this against a hidden gold answer with an exact-match "
            "rule (after light normalization) — answer in the exact format the question asks for: a number "
            "alone (no units unless asked), a short string (no articles, no abbreviations unless asked), or "
            "a comma-separated list, in the order the question implies. No extra words, no restating the question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The final answer, exactly as it should be scored."},
                "reasoning": {"type": "string", "description": "Brief justification — what you found and how you got the answer."},
            },
            "required": ["answer", "reasoning"],
        },
    },
}

GAIA_TOOLS = [DELEGATE_TOOL, THINK_TOOL, WEB_SEARCH_TOOL, PYTHON_EXEC_TOOL, FINISH_TOOL]

_DELEGATE_REQUIRED = ("description", "returns", "mode", "inputs", "output_contract")
_RETURNS = {"findings", "verdict"}
_MODES = {"oneshot", "agentic"}


@dataclass(frozen=True)
class GaiaToolPolicy:
    """Mirrors orchestrator.gru_toolcall.ToolPolicy's shape for the GAIA tool set —
    see that class's docstring for the "define what exists, don't force how it's
    used" rationale, unchanged here."""

    allow_think: bool = True
    allow_verdict: bool = True
    allow_delegate: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "GaiaToolPolicy":
        return cls(**(d or {}))


def build_tools(policy: GaiaToolPolicy | None = None) -> list[dict]:
    policy = policy or GaiaToolPolicy()
    tools = [_delegate_tool(policy)] if policy.allow_delegate else []
    if policy.allow_think:
        tools.append(THINK_TOOL)
    tools.append(WEB_SEARCH_TOOL)
    tools.append(PYTHON_EXEC_TOOL)
    tools.append(FINISH_TOOL)
    return tools


def _tool_names(policy: GaiaToolPolicy) -> set[str]:
    names = {"finish", "web_search", "python_exec"}
    if policy.allow_delegate:
        names.add("delegate_to_minion")
    if policy.allow_think:
        names.add("think")
    return names


def _delegate_tool(policy: GaiaToolPolicy) -> dict:
    if policy.allow_verdict:
        return DELEGATE_TOOL
    tool = copy.deepcopy(DELEGATE_TOOL)
    props = tool["function"]["parameters"]["properties"]
    props["returns"] = {
        "type": "string",
        "enum": ["findings"],
        "description": "Always 'findings' in this session: the minion's actual output comes back to you.",
    }
    del props["verification"]
    return tool


def _format_error(format_error_template: str, *, error: str, has_tool_calls: bool, template_kwargs: dict) -> dict:
    return {
        "role": "user",
        "content": Template(format_error_template, undefined=StrictUndefined).render(
            error=error, actions=[], has_tool_calls=has_tool_calls, **template_kwargs
        ),
        "extra": {"interrupt_type": "FormatError"},
    }


def _escalation_prefix(consecutive_format_errors: int) -> str:
    if consecutive_format_errors <= 0:
        return ""
    if consecutive_format_errors == 1:
        return "This is the 2nd response in a row with no valid tool call. "
    return (
        f"This is response #{consecutive_format_errors + 1} in a row with no valid tool call. "
        "Continuing this loses ALL work done so far — the session terminates with an EMPTY "
        "submission, no partial credit. Do not write any explanation, summary, or analysis text. "
        "Your entire response must be nothing but exactly one tool call. If you believe you already "
        "have the answer, call finish now instead of describing why it's the answer. "
    )


def _validate_delegate(args: dict, policy: GaiaToolPolicy) -> str:
    missing = [k for k in _DELEGATE_REQUIRED if k not in args]
    if missing:
        return f"delegate_to_minion missing required field(s): {missing}."
    allowed_returns = _RETURNS if policy.allow_verdict else {"findings"}
    if args.get("returns") not in allowed_returns:
        return f"delegate_to_minion 'returns' must be one of {sorted(allowed_returns)}, got {args.get('returns')!r}."
    if args.get("mode") not in _MODES:
        return f"delegate_to_minion 'mode' must be one of {sorted(_MODES)}, got {args.get('mode')!r}."
    inputs = args.get("inputs")
    if not isinstance(inputs, dict):
        return (
            "delegate_to_minion.inputs must be a JSON object with a 'scope' field, got "
            f"{type(inputs).__name__}."
        )
    if "scope" not in inputs:
        return "delegate_to_minion.inputs missing required 'scope'."
    verification = args.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    if policy.allow_verdict and args["returns"] == "verdict" and not verification.get("checks"):
        return (
            "delegate_to_minion with returns='verdict' requires at least one verification.checks entry "
            '(as an object: {"checks": ["..."]}) — the verdict is computed by running them, so there is '
            "nothing to return without them."
        )
    if args["mode"] == "oneshot" and not (inputs.get("from") or inputs.get("read_paths")):
        return (
            "delegate_to_minion with mode='oneshot' has no tools, so it needs its material supplied: set "
            "inputs.from (earlier delegation ids) and/or inputs.read_paths, or use mode='agentic' if the "
            "minion needs to go search/compute it."
        )
    return ""


def _validate_finish(args: dict) -> str:
    if "answer" not in args or not str(args.get("answer", "")).strip():
        return "finish missing required non-empty field 'answer'."
    if "reasoning" not in args:
        return "finish missing required field 'reasoning'."
    return ""


def parse_gaia_actions(
    tool_calls: list,
    *,
    format_error_template: str,
    template_kwargs: dict | None = None,
    consecutive_format_errors: int = 0,
    policy: GaiaToolPolicy | None = None,
) -> list[dict]:
    """GAIA sibling of orchestrator.gru_toolcall.parse_gru_actions — same one-action-
    per-turn enforcement and escalating FormatError correction, different tool set."""
    policy = policy or GaiaToolPolicy()
    template_kwargs = template_kwargs or {}
    escalation = _escalation_prefix(consecutive_format_errors)
    tool_names = _tool_names(policy)
    if not tool_calls:
        raise FormatError(
            _format_error(
                format_error_template,
                error=(
                    escalation
                    + "No tool calls found in the response. Every response MUST include exactly one tool call "
                    f"({', '.join(sorted(tool_names))})."
                ),
                has_tool_calls=False,
                template_kwargs=template_kwargs,
            )
        )
    if len(tool_calls) > 1:
        raise FormatError(
            _format_error(
                format_error_template,
                error=(
                    escalation
                    + f"{len(tool_calls)} tool calls in one response; exactly one is allowed. Issue the first "
                    "one alone — you need to see what it returns before deciding the next step."
                ),
                has_tool_calls=True,
                template_kwargs=template_kwargs,
            )
        )

    tool_call = tool_calls[0]
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

    if not error_msg and name not in tool_names:
        error_msg = f"Unknown tool '{name}'. Must be one of {sorted(tool_names)}."

    if not error_msg and name == "delegate_to_minion":
        error_msg = _validate_delegate(args, policy)
    if not error_msg and name == "finish":
        error_msg = _validate_finish(args)
    if not error_msg and name == "think" and not args.get("note"):
        error_msg = "think requires a non-empty 'note'."
    if not error_msg and name == "web_search" and not args.get("query"):
        error_msg = "web_search requires a non-empty 'query'."
    if not error_msg and name == "python_exec" and not args.get("code"):
        error_msg = "python_exec requires non-empty 'code'."

    if error_msg:
        raise FormatError(
            _format_error(
                format_error_template,
                error=escalation + error_msg.strip(),
                has_tool_calls=True,
                template_kwargs=template_kwargs,
            )
        )

    return [{"kind": name, "args": args, "tool_call_id": tool_call.id}]


def format_gaia_observation_messages(
    *,
    actions: list[dict],
    outputs: list[dict],
    observation_template: str,
    template_vars: dict | None = None,
) -> list[dict]:
    """Identical shape to orchestrator.gru_toolcall.format_gru_observation_messages."""
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
