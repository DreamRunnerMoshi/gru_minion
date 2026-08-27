"""Tool schemas and action parsing for Gru's loop.

Mirrors minisweagent.models.utils.actions_toolcall (which hardcodes a single
"bash" tool) but supports Gru's own action set instead. See prompts/gru-loop.md
for the design rationale and prompts/README.md for the revision history.

Revised 2026-08-24: the action set is no longer fixed at four. `ToolPolicy` +
`build_tools(policy)` let a session offer any subset (finish is always present;
delegate_to_minion, think, run_check, returns='verdict', and finish's verification
requirement are each independently toggleable) — orchestrator/config/gru.yaml
currently uses the fully-permissive default (all four, no restrictions); the
restrictive path exists for whenever a narrower session is wanted again.

Revised 2026-08-25 (exp5): `allow_delegate` added — False removes delegate_to_minion
entirely, for a genuine solo baseline (see ToolPolicy's own docstring). Before this,
delegate_to_minion was the one action every session was guaranteed to have.

Revised 2026-08-22 (see review.md R5/R6/R13/R15 and the delegation-criterion
discussion behind them):

- **No task taxonomy.** The old `type` enum (context_gather/locate/synthesize)
  encoded our guess about which work is delegable. That guess is now the thing
  under test, so Gru is no longer asked to classify work into our categories.
  Two mechanically-necessary dimensions replace it, and Gru sets both:
    * `returns` — "findings" (content comes back) vs "verdict" (pass/fail from
      a real check comes back). This is the only thing that changes what Gru sees.
    * `mode` — "oneshot" (a single model call: text in, text out) vs "agentic"
      (a full bash tool loop). This sets the *structural floor* on what a
      delegation costs: an agentic loop resends its whole history every turn, so
      anything that enters the conversation is paid for again on every later turn,
      while a oneshot pays once. exp2's t1 spent 105,770 tokens on a delegation
      that generated only 6,328 — the 317-line file it read was resent across 8
      calls (~37k tokens), and the verbatim copy it wrote into findings.md was
      resent across 3 more (~15k). The same work as a oneshot, with the file
      supplied via inputs.read_paths, is a single ~7-10k call.
      Mode is not the whole cost story (scope and description drive how far an
      agentic minion wanders), but it is the part Gru controls directly — and
      choosing it forces the useful question, which is whether a delegation is
      doing discovery and transformation at once. t1 did both: grepping for which
      files mention separability genuinely needs a shell; transcribing and
      summarising one known file does not.
- **`think`** — Gru previously had no action other than delegating or finishing,
  so `prompts/gru-loop.md`'s "reason and decide directly, no delegation" option
  was one the harness forbade. It is now a real action.
- **`run_check`** — Gru had no way to re-run a corrected check without spawning a
  whole no-op minion session (exp2's t4/t6 burned ~20k tokens doing exactly that).
- **Exactly one action per turn is enforced here**, not left to
  `parallel_tool_calls` — that param was silently dropped by Ollama in exp2 and
  Gru batched delegations it should have issued one at a time.
"""

import copy
import json
import time
from dataclasses import dataclass

from jinja2 import StrictUndefined, Template

from minisweagent.exceptions import FormatError

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
                        "— use it whenever a real check can settle whether the work succeeded."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": ["oneshot", "agentic"],
                    "description": (
                        "'oneshot' is a single model call — text in, text out, no shell. Far cheaper. "
                        "Use it for transforming or compressing material you already have. "
                        "'agentic' gives the minion a bash loop to explore or modify the repo."
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
                                "Mainly for mode='oneshot', which has no shell of its own."
                            ),
                        },
                        "scope": {
                            "type": "string",
                            "description": "Path or boundary the minion is allowed to operate within.",
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
                            "description": "Shell commands; exit code 0 means pass. Required when returns='verdict'.",
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
            "is a decision rather than work — a design call, deciding whether what you have is enough, "
            "or interpreting a failure. Nothing is executed and nothing is charged to a minion."
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

RUN_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "run_check",
        "description": "Run shell commands yourself against the shared testbed and see the result.",
        "parameters": {
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

GRU_TOOLS = [DELEGATE_TOOL, THINK_TOOL, RUN_CHECK_TOOL, FINISH_TOOL]

_DELEGATE_REQUIRED = ("description", "returns", "mode", "inputs", "output_contract")
_RETURNS = {"findings", "verdict"}
_MODES = {"oneshot", "agentic"}


@dataclass(frozen=True)
class ToolPolicy:
    """What Gru is offered this session — added 2026-08-24. Defaults reproduce the
    original, fully-permissive design unchanged: every existing config that doesn't
    set `tool_policy` behaves exactly as before.

    This is deliberately the only lever here — which actions/fields exist at all — not
    a lever on how Gru should use them. That distinction matters: this project's stance
    (2026-08-23) is that Gru's delegation judgement should not be forced by the harness.
    A policy that removes `verdict` or drops `run_check` isn't forcing a *choice* Gru
    would otherwise make freely; it's defining what session is being run. Nothing here
    nudges Gru's behavior within whatever action set it's given.
    """

    allow_think: bool = True
    allow_run_check: bool = True
    allow_verdict: bool = True
    require_finish_verification: bool = True
    # Added 2026-08-25 (exp5): False builds a genuine solo baseline — no minion exists
    # for this session at all, not just a restricted one. Every other run this project
    # has produced measures the Gru/minion architecture's behavior; none has measured
    # against "the same model doing the task alone," which is the actual counterfactual
    # needed to see whether delegation saves anything. Defaults True — no existing
    # config's behavior changes unless it explicitly sets this.
    allow_delegate: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "ToolPolicy":
        return cls(**(d or {}))


def build_tools(policy: ToolPolicy | None = None) -> list[dict]:
    """The tool list actually offered to the model this session, shaped by `policy`."""
    policy = policy or ToolPolicy()
    tools = [_delegate_tool(policy)] if policy.allow_delegate else []
    if policy.allow_think:
        tools.append(THINK_TOOL)
    if policy.allow_run_check:
        tools.append(RUN_CHECK_TOOL)
    tools.append(_finish_tool(policy))
    return tools


def _tool_names(policy: ToolPolicy) -> set[str]:
    names = {"finish"}
    if policy.allow_delegate:
        names.add("delegate_to_minion")
    if policy.allow_think:
        names.add("think")
    if policy.allow_run_check:
        names.add("run_check")
    return names


def _delegate_tool(policy: ToolPolicy) -> dict:
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


def _finish_tool(policy: ToolPolicy) -> dict:
    if policy.require_finish_verification:
        return FINISH_TOOL
    tool = copy.deepcopy(FINISH_TOOL)
    tool["function"]["description"] = "Declare the task complete."
    tool["function"]["parameters"]["properties"].pop("final_verification", None)
    tool["function"]["parameters"]["required"] = ["summary"]
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
    """exp2-rerun and exp3 (LOG.md) both found the dominant FormatError is Gru writing a
    prose conclusion instead of calling a tool, and that a static repeated correction does
    not stop it — `think` was added as a legal way to do this and was used 0/147 times in
    exp3 arm B. This escalates the correction itself into a harder constraint (naming the
    consequence, not just repeating the instruction) as consecutive failures pile up,
    rather than relying on the model to self-correct from the same text every time."""
    if consecutive_format_errors <= 0:
        return ""
    if consecutive_format_errors == 1:
        return "This is the 2nd response in a row with no valid tool call. "
    return (
        f"This is response #{consecutive_format_errors + 1} in a row with no valid tool call. "
        "Continuing this loses ALL work done so far — the session terminates with an EMPTY "
        "submission, no partial credit. Do not write any explanation, summary, or analysis text. "
        "Your entire response must be nothing but exactly one tool call. If you believe the task "
        "is already done, call finish now instead of describing why it's done. "
    )


def _validate_delegate(args: dict, policy: ToolPolicy) -> str:
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
            "delegate_to_minion with mode='oneshot' has no shell, so it needs its material supplied: set "
            "inputs.from (earlier delegation ids) and/or inputs.read_paths (files to hand over verbatim), "
            "or use mode='agentic' if the minion needs to go find it."
        )
    return ""


def _validate_finish(args: dict, policy: ToolPolicy) -> str:
    if "summary" not in args:
        return "finish missing required field 'summary'."
    if not policy.require_finish_verification:
        return ""
    final_verification = args.get("final_verification")
    if not isinstance(final_verification, dict):
        return (
            'finish.final_verification must be a JSON object with a \'checks\' field (e.g. {"checks": [...]}), '
            f"got {type(final_verification).__name__}."
        )
    if not final_verification.get("checks"):
        return "finish.final_verification.checks must be non-empty — see prompts/gru-loop.md for why this can't be skipped."
    return ""


def parse_gru_actions(
    tool_calls: list,
    *,
    format_error_template: str,
    template_kwargs: dict | None = None,
    consecutive_format_errors: int = 0,
    policy: ToolPolicy | None = None,
) -> list[dict]:
    """Parse Gru's tool calls into action dicts. Raises FormatError on malformed/unknown calls.

    Exactly one action per turn is enforced here rather than relying on the provider honouring
    `parallel_tool_calls: false` — Ollama silently dropped that param in exp2 and Gru issued
    delegations in pairs, so 4 of 6 were decided without seeing the previous result.

    consecutive_format_errors: how many FormatErrors have already fired in a row before this
    call (0 on a fresh turn) — the caller (GruModel) owns this count and resets it to 0 on any
    clean parse. Used to escalate the correction text (_escalation_prefix) instead of repeating
    the same message every time; see that function's docstring for why.

    policy: which of the four actions/fields this session actually offers (ToolPolicy) — must
    match what build_tools(policy) advertised to the model, so a name it was never offered is
    rejected the same way an unknown tool always would be, not silently accepted.
    """
    policy = policy or ToolPolicy()
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
                    "one alone — you need to see what it returns before deciding the next step, and that "
                    "is the whole point of working one step at a time."
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
        error_msg = _validate_finish(args, policy)
    if not error_msg and name == "think" and not args.get("note"):
        error_msg = "think requires a non-empty 'note'."
    if not error_msg and name == "run_check" and not args.get("checks"):
        error_msg = "run_check requires a non-empty 'checks' array of shell commands."

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
