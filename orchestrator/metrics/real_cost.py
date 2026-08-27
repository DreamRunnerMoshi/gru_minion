"""Real, provider-reported cost — bypasses mini-swe-agent's own cost calculator.

Discovered 2026-08-25 (exp5), mid-batch, against `openrouter/qwen/qwen3-max`:
`LitellmModel._calculate_cost()` calls `litellm.cost_calculator.completion_cost()`,
which prices a response from litellm's own *static* registry — never the response's
own `usage.cost` field, which OpenRouter always populates for real (confirmed:
`OpenrouterConfig.transform_request()` unconditionally sets `usage: {"include": True}`
on every request). When a model isn't in litellm's static registry (true for Qwen3-max,
untested but plausibly true for others outside the DeepSeek pair this project validated
earlier), `completion_cost()` raises, and `MSWEA_COST_TRACKING=ignore_errors`
(`run_session.py`) silently swallows that to `cost=0.0` — no warning, no exception.

The practical consequence: `--cost-limit`/`--minion-cost-limit` (real, enforced caps —
see run_session.py's 2026-08-25 revision notes) becomes a silent no-op for any such
model, bounded only by step_limit turns, not dollars. A live batch was running against
exactly this gap when it was caught (one qwen3-max call: real OpenRouter cost $0.0017,
mini-swe-agent's own tracking: $0.0) and had to be stopped and fixed before continuing.

`real_completion_cost()` is used by GruModel and MinionModel to override
`_calculate_cost()`: prefer the response's own reported cost when present, fall back to
litellm's calculator only when it isn't (e.g. a self-hosted Ollama response, which has
no such field) — so nothing breaks for the runs this project already validated.
"""


def real_completion_cost(response) -> float | None:
    """The dollar cost OpenRouter (or any provider that reports it) actually billed for
    this call, read directly from the response — not computed from a local price table
    that may not know this model. None if the response doesn't carry one."""
    usage = getattr(response, "usage", None)
    cost = getattr(usage, "cost", None)
    return float(cost) if cost is not None else None
