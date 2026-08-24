"""A factual, non-prescriptive sentence about what Gru and the minion actually cost
per token this session — injected into the prompt as `{{ cost_context }}` (see
orchestrator/prompts/gru/role.md).

Added 2026-08-24: the prompt previously said only "cheaper," with no magnitude, and a
sentence explicitly pre-authorizing zero delegation as "a legitimate outcome, not a
mistake to correct." First real live run (DeepSeek V4 Pro/Flash over OpenRouter)
delegated zero times across 80 turns — consistent with self-hosted Qwen's behavior in
exp3, but it left the project's cost hypothesis untestable (no delegation, nothing to
compare). Decision: still no rule telling Gru to delegate, but replace the vague claim
with the real number so Gru reasons from an actual fact instead of nothing. This is a
fact injection, not a nudge — see the module docstring on ToolPolicy in gru_toolcall.py
for the same distinction applied to actions/fields instead of prompt content.

Real cost data only. When it isn't available (self-hosted models — Phase 1's
ollama_chat/... runs never had per-role cost, by design; see memory
project-machine-config), the sentence is omitted entirely rather than fabricated.
"""

import httpx
import litellm


def _litellm_price_per_million(model: str) -> tuple[float, float] | None:
    info = litellm.model_cost.get(model)
    if not info:
        return None
    inp, out = info.get("input_cost_per_token"), info.get("output_cost_per_token")
    if not inp or not out:
        return None
    return inp * 1_000_000, out * 1_000_000


def _openrouter_price_per_million(model: str) -> tuple[float, float] | None:
    """litellm's bundled cost registry lags brand-new OpenRouter releases — confirmed
    2026-08-24, it had deepseek-v4-pro-0813 but not deepseek-v4-flash-0731 the same
    day both launched. Falls back to OpenRouter's own live catalog for openrouter/
    models litellm doesn't have priced yet. Best-effort: any failure (network,
    missing key, unlisted model) returns None rather than raising — a missing cost
    fact should degrade to omitting the sentence, never break the session."""
    if not model.startswith("openrouter/"):
        return None
    slug = model.removeprefix("openrouter/")
    try:
        # httpx (not the stdlib's bare urllib) deliberately: urllib's default SSLContext
        # can fail CERTIFICATE_VERIFY_FAILED depending on how Python's own CA bundle is
        # set up on the host (hit this exact failure locally on macOS 2026-08-24) — httpx
        # bundles certifi and doesn't inherit that problem.
        data = httpx.get("https://openrouter.ai/api/v1/models", timeout=5).json()
        for entry in data.get("data", []):
            if entry.get("id") == slug:
                pricing = entry.get("pricing", {})
                return float(pricing["prompt"]) * 1_000_000, float(pricing["completion"]) * 1_000_000
    except Exception:
        return None
    return None


def _price_per_million(model: str) -> tuple[float, float] | None:
    return _litellm_price_per_million(model) or _openrouter_price_per_million(model)


def describe_cost_ratio(gru_model: str, minion_model: str) -> str:
    """Returns a sentence fragment (leading space included, empty string if no real
    pricing is known for both models) — designed to be spliced directly after "a
    companion LLM, cheaper to run than you." in role.md."""
    gru_price = _price_per_million(gru_model)
    minion_price = _price_per_million(minion_model)
    if not gru_price or not minion_price:
        return ""
    gru_in, gru_out = gru_price
    min_in, min_out = minion_price
    if min_in <= 0 or min_out <= 0:
        return ""
    return (
        f" Concretely, this session: you cost ${gru_in:.2f} / ${gru_out:.2f} per million "
        f"input/output tokens; the minion costs ${min_in:.3f} / ${min_out:.3f} — "
        f"about {gru_in / min_in:.0f}x / {gru_out / min_out:.0f}x cheaper per token."
    )
