"""Live cache accounting for a Gru or minion session.

EXPERIMENT_LOG_FORMAT.md asks for cache-hit % captured *during* the run, not
reconstructed afterwards. exp1 missed that and had to estimate post-hoc from
destroyed instances; exp2 skipped it entirely as out of scope. It is no longer
out of scope: `mode="oneshot"` removes history resend that prefix caching was
already partly absorbing, so the token delta between exp2 and exp3 is not
readable as a cost delta without knowing how much of exp2's resend was cached
in the first place (see review.md R12/R16).

Two independent sources, both recorded, never conflated:

1. **provider-reported** — `usage.prompt_tokens_details.cached_tokens`. Real
   measurement where the provider exposes it. litellm/Ollama left this None for
   every call in exp1, so expect it to be absent on self-hosted runs and present
   on Anthropic/OpenAI-tier APIs.
2. **estimated** — exp1's prefix-reuse reconstruction, computed live rather than
   after the fact: a conversation only ever grows, so each call's prompt is a
   prefix-extension of the previous call's prompt + completion, and
   `min(prev_prompt + prev_completion, this_prompt)` bounds what could have been
   reused. This is an **upper bound**, not a measurement — llama.cpp evicts
   context checkpoints on long conversations, so real reuse can be lower.
"""

from typing import Any


def _usage(message: dict) -> dict | None:
    return (message.get("extra") or {}).get("response", {}).get("usage")


def extract_cache_stats(messages: list[dict[str, Any]]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    prev_prompt = prev_completion = 0
    reported_total = 0
    reported_seen = False

    for m in messages:
        u = _usage(m)
        if not u:
            continue
        prompt = u.get("prompt_tokens") or 0
        completion = u.get("completion_tokens") or 0

        details = u.get("prompt_tokens_details") or {}
        reported = details.get("cached_tokens") if isinstance(details, dict) else None
        if reported is not None:
            reported_seen = True
            reported_total += reported

        estimated_reuse = min(prev_prompt + prev_completion, prompt) if calls else 0
        calls.append(
            {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "reported_cached_tokens": reported,
                "estimated_reused_tokens": estimated_reuse,
                "estimated_new_tokens": prompt - estimated_reuse,
            }
        )
        prev_prompt, prev_completion = prompt, completion

    total_prompt = sum(c["prompt_tokens"] for c in calls)
    total_reused = sum(c["estimated_reused_tokens"] for c in calls)
    return {
        "n_calls": len(calls),
        "total_prompt_tokens": total_prompt,
        # measured, or None when the provider doesn't expose it (Ollama in exp1)
        "reported_cached_tokens": reported_total if reported_seen else None,
        "reported_cache_hit_pct": round(100 * reported_total / total_prompt, 2)
        if reported_seen and total_prompt
        else None,
        # upper-bound estimate, always computable — never report as measured
        "estimated_reused_tokens": total_reused,
        "estimated_cache_hit_pct": round(100 * total_reused / total_prompt, 2) if total_prompt else 0.0,
        "per_call": calls,
    }


def merge_cache_stats(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate across a whole run (Gru session + every minion sub-session).

    Cross-session reuse is zero by construction — each minion starts a fresh
    conversation sharing no prefix with the last — so this sums independent
    sessions rather than treating the run as one growing context. That is the
    structural reason exp2's ~30 separate prefixes cache far worse than exp1's
    single long conversation, at identical raw token counts.
    """
    total_prompt = sum(s["total_prompt_tokens"] for s in sessions)
    total_reused = sum(s["estimated_reused_tokens"] for s in sessions)
    # Only sessions that actually reported may appear in the reported ratio — dividing
    # a partial numerator by every session's prompt tokens understates it badly.
    reporting = [s for s in sessions if s["reported_cached_tokens"] is not None]
    reported_cached = sum(s["reported_cached_tokens"] for s in reporting)
    reported_prompt = sum(s["total_prompt_tokens"] for s in reporting)
    return {
        "n_sessions": len(sessions),
        "n_calls": sum(s["n_calls"] for s in sessions),
        "total_prompt_tokens": total_prompt,
        "reported_cached_tokens": reported_cached if reporting else None,
        "reported_over_prompt_tokens": reported_prompt if reporting else None,
        "reported_sessions": len(reporting),
        "reported_cache_hit_pct": round(100 * reported_cached / reported_prompt, 2)
        if reporting and reported_prompt
        else None,
        "estimated_reused_tokens": total_reused,
        "estimated_cache_hit_pct": round(100 * total_reused / total_prompt, 2) if total_prompt else 0.0,
    }
