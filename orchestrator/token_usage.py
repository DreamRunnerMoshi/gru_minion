"""Extract real token usage from a mini-swe-agent message list.

litellm's own cost calculator returns 0.0 for self-hosted/unregistered models
(see experiments/exp1/LOG.md Issues) — but the raw per-call usage survives in
each assistant message's extra.response.usage regardless, since that's set
before the cost calculation that fails. This is the same recovery technique
exp1 had to apply after the fact; doing it live here avoids repeating that.
"""

from typing import Any


def extract_token_usage(messages: list[dict[str, Any]]) -> dict[str, int]:
    prompt_tokens = completion_tokens = total_tokens = 0
    for m in messages:
        usage = (m.get("extra") or {}).get("response", {}).get("usage")
        if not usage:
            continue
        prompt_tokens += usage.get("prompt_tokens") or 0
        completion_tokens += usage.get("completion_tokens") or 0
        total_tokens += usage.get("total_tokens") or 0
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
