# Component 5: Running the minion through Claude Code instead of OpenRouter

Status: investigated 2026-08-27, **not built**. One question is settled and needs no work;
the question that actually decides it is unmeasured, and the experiment to settle it is
specified at the end. Companion to [04-machine-config.md](./04-machine-config.md), which
covers the model-pairing decision this would change.

## The question

The pilot's minion runs through OpenRouter (`openrouter/z-ai/glm-4.5-air`), which needs an
`OPENROUTER_API_KEY` and bills separately from the Claude Code subscription a developer is
already paying for. Could the minion instead be Haiku, invoked through Claude Code itself —
one bill, one credential, and a stronger executing model?

Three readings, only the third of which is what was asked for:

| Option | New key? | Per-token | Work to build |
|---|---|---|---|
| Today: `glm-4.5-air` via OpenRouter | already have it | $0.13 / $0.85 per M | none |
| `anthropic/claude-haiku-4-5` via litellm | **yes, `ANTHROPIC_API_KEY`** | $1 / $5 per M | none — a `--model` change |
| `claude -p --model haiku` (headless Claude Code) | **no** | $1 / $5 per M | a second backend |

Option 2 is a one-flag change but requires exactly the credential the exercise is trying to
avoid. Option 3 is the real subject.

## It works, on existing auth

`claude -p --model haiku --output-format json` runs with **no `ANTHROPIC_API_KEY` set** — it
uses the Claude Code subscription — and reports `total_cost_usd` plus a full per-model token
breakdown, so per-role cost accounting survives the switch.

It can also be constrained more tightly than the current minion:
`--permission-mode acceptEdits` with `--allowedTools "Bash Read Edit Glob Grep"` is a real
improvement over the OpenRouter minion, which gets an unrestricted shell.

## The prefix overhead, and why session reuse does not help

Every headless invocation carries ~20k tokens of Claude Code's own system prompt and tool
definitions.

Measured, `claude -p --model haiku` replying with one word:

| | cost | cache_create | cache_read |
|---|---|---|---|
| cold | $0.0178 | 7,718 | 12,212 |
| warm | $0.0032 | 0 | 19,930 |

The obvious proposal is to hold one long-lived minion session open so that prefix stays
cached, the way `session_id` is used for sticky routing on the OpenRouter path.

**That is already happening, without session reuse.** Three consecutive invocations, each a
distinct `session_id`:

```
session=423d27f1  $0.0032  cache_create=0  cache_read=19930
session=f58eba6c  $0.0032  cache_create=0  cache_read=19930
session=32ade658  $0.0031  cache_create=0  cache_read=19930
```

Separate sessions share the cached prefix already. So the correction worth recording: this
is **not a per-session setup cost that amortises**, it is a **per-request charge for reading
the cached prefix** — cheap (roughly a tenth of the input rate) but never free. $0.0032 is a
floor, not a warm-up.

There is also an architectural reason not to reuse a session even if it did help. A resumed
session accumulates history, so a third delegation would carry the first two in context.
That is precisely what bounded delegation exists to prevent: the minion is meant to receive
only its own material and scope (see
[02-gru-minion-protocol.md](../architecture/02-gru-minion-protocol.md)), and accumulated
history is re-read every turn, so the cost grows as the session goes.

## What is *not* established

A single tool-using task — "count the lines in data.txt and report the number" — cost
**$0.0212**, 6.6× the trivial call. The itemised `usage` does not explain that: it reports
one model turn, `cache_read=19,953`, `out=44`, which should land near $0.003. `total_cost_usd`
is capturing something the `iterations` array is not.

So **per-turn economics are unmodelled**, and should not be estimated from these probes.
What can be said empirically is narrower: headless Haiku was ~20× more expensive than the
OpenRouter minion for comparable trivial work ($0.0212 to count three lines, against $0.0009
for a delegation that ran four shell commands and wrote a findings file).

## The question that actually decides it

Per-token price is the wrong comparison, and the reason is in the field data. An 8-file
constant move through `glm-4.5-air` took **61 model calls and 771,425 tokens** — a weak model
visibly flailing, and Gru correctly called it a poor trade. Haiku is ~7× more expensive per
token, but if it finishes the same work in 15 turns it wins outright.

The thesis was never "cheapest per token". It is "cheapest total, at acceptable quality".
That is measurable, and has not been measured.

### Proposed experiment

Same delegation spec, same starting repository state, once through each backend:

- total cost, both sides
- turns taken
- whether Gru had to correct the result afterwards, and how much

The 8-file constant move is the natural candidate: a real task, already run once, with a
recorded baseline of 61 calls / 771k tokens / two corrections needed. Cost of the comparison
is roughly $0.20, against the cost of building a second backend on a guess.

## If it is built

Keep it a selectable backend — `gru-delegate --backend claude-code` — with litellm as the
default, so nothing existing changes and the two can be compared directly.

One consequence to keep in view: a Claude Code minion spends the **same budget as Gru**. For
a product user that is simpler, one bill. For the research thesis it is a confound — "cost
shifted to the cheaper tier" stops being measurable when both tiers bill to one
subscription. The OpenRouter path should stay as the measurement configuration even if the
product default changes.
