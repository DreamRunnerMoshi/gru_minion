# Experiment 5 — spending less on Gru, more on Minion, in token terms

exp5's actual question, stated by the user starting this experiment: exp4 established
that Gru *can* delegate under the right prompt conditions, and that the verdict-summary
mechanism can even use delegation to catch a gap in Gru's own diagnosis (run 12). But
exp4's own closing token/cost table showed delegation never moved past ~7% of a run's
total spend, on any run, including the ones that "worked." exp5 is about actually moving
that number — shifting a meaningfully larger share of total token volume from Gru
(expensive) to the minion (cheap) — not just getting delegation to happen at all.

Before touching prompt wording again, the first task was diagnostic: **is prompt size
even the lever that matters for cost, or is something else driving it?**

## Finding 1: compressing the system prompt would not have helped

Gru's composed system prompt is ~2,700 tokens (system + instance template, measured with
litellm's token_counter). That's cached after the very first call in a session — its
one-time uncached cost is roughly $0.003-0.005 per run, against total run costs of
$0.10-0.55 across exp4's twelve runs. Even eliminating it entirely couldn't move total
cost by more than ~2%. Whatever "compress the prompt" was going to fix, this wasn't it.

## Finding 2: the real cost driver is periodic full cache-miss events, not prompt size

Pulled the real, provider-reported `cached_tokens` field (from `usage.prompt_tokens_details`,
via `orchestrator/cache_stats.py`) for every call in every exp4 run, and cross-validated it
against the actual billed `$` (litellm's own `gru.cost`) — the two independently-computed
numbers agree to the cent, confirming this isn't a measurement artifact: cost tracks
non-cached ("fresh") tokens almost exactly (`non_cached_prompt × $1.32/M + completion ×
$3.96/M`, cached tokens contributing ~$0.00001/M — noise).

Most calls in most runs cache well: 95-99% hit rate, as expected for a growing,
stable-prefix conversation. But in nearly every run, a handful of calls show the cache
hit rate collapsing — sometimes to exactly 0% — meaning the *entire* accumulated
conversation gets rebilled at full price on that one call, not just the newly-added
content. These anomalous calls are a small fraction of total calls but a large fraction
of total non-cached cost:

| Run | Calls with <70% cache hit | Share of run's non-cached cost |
|---|---:|---:|
| 02 | 9 of 68 | 73.7% |
| 06 | 6 of 31 | 60.9% |
| 10 | 10 of 41 | 78.3% |
| 11 | 10 of 66 | 70.4% |
| 12 | 6 of 56 | 66.5% |

Checked and ruled out: wall-clock TTL expiry. Gap length before an anomalous call
doesn't predict it — run 10's longest gap (96s, between calls 39 and 40) preceded a
*normal* call; several 5-second gaps preceded anomalies. Loosely correlated with the
action immediately preceding the call (9 of 10 anomalies in run 10 followed `run_check`),
but not conclusively root-caused beyond that.

## Finding 3: this matches a known OpenRouter routing behavior, and there's a documented fix

[OpenRouter's own docs](https://openrouter.ai/blog/tutorials/prompt-caching-sticky-routing/)
describe exactly this failure mode. Without an explicit `session_id`, OpenRouter derives
its sticky-routing key by hashing a request's opening messages, and routes based on that
hash to whichever backend replica is holding a warm cache for it. An agent loop's opening
messages aren't static — content shifts as the conversation grows — so the hash drifts,
and a request can land on a *different* backend replica than the one holding the actual
warm cache, even though nothing about wall-clock timing changed. Quoting the docs
directly: *"the fix for agent loops is an explicit session_id... sticky routing kicks in
after the first successful request, before any cache hit has happened,"* pinning all of a
conversation's requests to one backend regardless of how the opening messages change turn
to turn.

Sources:
- [Prompt Caching — OpenRouter docs](https://openrouter.ai/docs/guides/best-practices/prompt-caching)
- [OpenRouter Prompt Caching: What Cached Tokens Cost — OpenRouter Blog](https://openrouter.ai/blog/tutorials/prompt-caching-sticky-routing/)

## Action taken: session_id wired in before any prompt work (exp5.1)

Every OpenRouter call now carries `extra_body: {"session_id": ...}`:

- **Gru**: one `session_id` (`gru-{run_id}`), stable for the whole Gru session. Set
  inside `GruModel.__init__` itself (`orchestrator/gru_model.py`) rather than left to
  each call site to construct — the first implementation set it correctly in
  `run_gru_session.py` but silently missed it in `tests/harness.py`'s separate
  construction, which would have made the mechanism untestable without anyone noticing.
  Owning it inside `GruModel` means any caller gets it for free; `run_id` defaults to
  `"test-session"` so mocked tests exercise the same code path.
- **Minion**: one `session_id` per delegation (`minion-{run_id}-{delegation_id}`), stable
  across that one delegation's own turns — never shared with Gru's or with another
  delegation's, since each delegation is its own conversation with its own prefix, not a
  continuation of anything else. Set in `orchestrator/gru_environment.py`'s `_run_agentic`
  and `_run_oneshot`.
- `run_id` itself (`{instance_id}-{8 hex chars}`) is generated once per `run_gru_session.py`
  invocation, not per instance — the same instance gets re-run repeatedly across a day of
  experiments, and reusing a stable id across unrelated runs would defeat the purpose.

Pinned by `tests/test_delegation_flow.py::test_openrouter_session_id_is_stable_per_conversation_distinct_per_delegation`:
asserts Gru's calls all share one session_id and two different delegations get two
different ones, using the mocked harness's own call-recording (no live API needed to
verify the mechanism is wired correctly).

## What's still open

This is a routing fix, not a prompt-content fix — it doesn't compress anything, and it
doesn't change what Gru or the minion say. The prediction it makes is narrow and
checkable: **the anomalous full-cache-miss calls found in Finding 2 should mostly
disappear** on a live re-run of the same instance/prompt, and total `$` cost for a
comparable run should drop by roughly the anomaly share shown above (60-78% of
non-cached cost, in the worst runs) — not because less work happened, but because less
of the same work gets rebilled at full price.

## Run 1: minion's share of total spend jumped from a 7.2% exp4 ceiling to 31.7%

First live run under the current prompt (post-exp5.2 `role.md` cleanup) with
`session_id` in place. `Submitted`, verified, real SWE-bench evaluation: **resolved**.
Two delegations, but an unusually large minion call volume for both (21 and 36 API
calls, 730K combined minion tokens) — a genuinely different run shape from anything in
exp4, not just a same-prompt-plus-session_id rerun.

**This is the headline result, and it's the actual target metric moving for the first
time.** exp4's closing note flagged that delegation had never exceeded ~7% of a run's
total dollar spend on any of twelve runs — the core cost-asymmetry hypothesis (a
meaningful *volume* of work shifting to the cheap model) had never actually been tested.
This run breaks that ceiling by a wide margin:

| Run | Gru $ | Minion $ | Total $ | Minion % of $ | Minion % of tokens |
|---|---:|---:|---:|---:|---:|
| exp4 run 8 | $0.2259 | $0.0175 | $0.2434 | 7.2% | — |
| exp4 run 10 | $0.2380 | $0.0041 | $0.2421 | 1.7% | — |
| exp4 run 12 | $0.4049 | $0.0120 | $0.4169 | 2.9% | — |
| **exp5 run 1** | **$0.2262** | **$0.1049** | **$0.3311** | **31.7%** | **61.0%** |

By token count, the **majority of this run's total work (61.0%) was handled by the
minion**, not Gru — the first run, across thirteen total, where that's true. Gru's own
dollar cost ($0.2262) stayed in the same range as exp4's cheaper runs, not inflated by
managing two large delegations; the total cost increase over run 8/10 comes entirely
from the minion actually doing a large volume of real work, not overhead. This is
attributable to the *prompt* — `delegation.md`'s content-based "When to delegate"
default (exp4.17) finally being exercised at real scale (t1: a large `findings`-mode
search/investigation delegation; t2: a large `verdict`-mode execution delegation,
matching the two content categories that section names) — not to `session_id`, which
only affects cache routing, not what gets delegated or how much.

**The cache-anomaly picture, below, is a separate and smaller-stakes finding than this
one.** Worth keeping the two apart: this run is strong, if single-sample, evidence that
the delegation-volume side of exp5's goal is achievable with the current prompt; the
cache-hit-rate question is about squeezing more efficiency out of whatever volume
happens, and remains open regardless of how this first question resolves.

**Methodological note: token share, not `$` share, is the metric to trust across runs.**
Already visible in this project's own logs, same day, same two models, same provider:
`cost_context.py`'s live-pricing lookup told Gru *"the minion costs roughly 20x to 30x
less per token"* for runs 8-11, and *"roughly 9x to 15x less"* for run 12 and both exp5
runs — OpenRouter's real per-token pricing for `deepseek-v4-pro`/`deepseek-v4-flash`
moved on its own, hours apart, with nothing on our side changing. A `$`-based comparison
between runs from different points in the day is partly measuring the market, not just
the architecture — and that only gets worse across different models or providers, where
pricing structures aren't even comparable in shape. Token counts don't have this
problem: they measure the actual computational work distributed between Gru and the
minion, independent of whatever a provider charges for it that hour. Going forward,
**minion's share of total tokens is the primary metric** for whether exp5's goal is
being met; `$` stays a useful secondary number for absolute-cost awareness, not the
axis for comparing runs against each other.

**But the anomaly pattern this run's own data shows did not improve.** Gru's own
session: 7 of 23 calls (30.4%) came in under 70% cache hit rate — a *higher* anomaly
rate than run 10's un-fixed baseline (10 of 41, 24.4%) — and overall cache hit rate
(74.8%) was worse than most of exp4's twelve runs (typically 85-98%). Both minion
delegations, despite each getting a distinct `session_id`, still showed several
anomalous calls apiece (t1: 3 of 21, 91.6% overall; t2: 4 of 36, 82.4% overall) rather
than the near-elimination the fix was meant to produce.

**This is not clean evidence the fix doesn't work.** Two things are confounded in this
one run that a real test needs to separate: (1) the prompt itself also changed
(`role.md`'s boundary section removed, exp5.2) between this run and any exp4 baseline,
and (2) this run's shape — two very large delegations dominating the session — is
unlike any exp4 run's, so different cache dynamics could come from that alone,
independent of routing. What this run *does* rule out is the easy version of the
hypothesis: `session_id` is not a complete, guaranteed fix for these anomalies by
itself, at least not one that shows up cleanly on the first try. Either sticky routing
has limits beyond what the docs describe (backend-side cache eviction under memory
pressure or its own TTL, which routing to the same backend can't prevent), or this is
still just n=1 variance on top of a run that also changed for other reasons.

## Runs 2-3: solo Opus wasn't affordable, so a genuine but budget-safe pair — deepseek-r1

User's proposal: use a genuinely expensive frontier model as Gru (Opus) so `$` savings
from delegation become visible against a large, structural price gap rather than the
noisy 9-30x drift between two similarly-priced DeepSeek variants — and, crucially, run
a true solo baseline (the same model working alone) as the actual counterfactual this
project has never measured against. Opus was ruled out on cost grounds ("don't want to
spend $1-2"). `google/gemini-3.7-flash:batch` was floated as a cheaper alternative but
turned out to be a genuine async batch-only endpoint (confirmed live: OpenRouter
rejects a normal chat-completion call to it with *"This model is only available
through the Batch API"* — true of every `:batch` suffix in the whole Gemini lineup, not
just this one model), incompatible with this project's per-turn synchronous loop
without a real rearchitecture.

Landed on `openrouter/deepseek/deepseek-r1` as Gru ($0.70/$2.50 per M, DeepSeek's own
flagship reasoning model, same vendor as the minion) against the existing
`deepseek-v4-flash-0731` minion ($0.14/$0.28) — a real ~5x/8.9x gap, confirmed live to
handle tool-calling correctly, protected by a new hard `--cost-limit` flag (real
enforcement via mini-swe-agent's own `LimitsExceeded`, not advisory) set to $0.35 per
Gru session as a safety net. Building the solo side required `ToolPolicy.allow_delegate`
and `gru-solo.yaml` (see gru-loop.md's twenty-third change) — the actual comparison this
project has never run before.

**Both runs failed real evaluation, for the same reason.** Solo (`02-solo-deepseek-r1`):
`Submitted`, unresolved — 14 turns, $0.0772, 96,260 tokens. Paired
(`03-paired-r1-flash`): `Submitted`, unresolved — 5 Gru turns, 3 delegations, $0.1118
total, 492,886 tokens. Checked directly: neither patch sets `self.data.start_line` —
both found and fixed the write-path half of the bug, neither found the read-path half,
the same specific gap that broke exp4 runs 5-7. Whether R1 worked alone or delegated
three separate pieces of investigation/execution, it converged on the same incomplete
diagnosis. This is a genuinely different failure signature from exp4's: it isn't about
delegation compressing investigation (the paired run did *five times* the token volume
of the solo run) — R1 as a model apparently doesn't independently derive the read-path
requirement on this task, regardless of how much work surrounds the diagnosis.

**But the token/cost shift is the largest seen yet, by a wide margin.** The paired run:

| Run | Gru $ | Minion $ | Total $ | Minion % of $ | Minion % of tokens |
|---|---:|---:|---:|---:|---:|
| exp5 run 1 (deepseek-pro/flash) | $0.2262 | $0.1049 | $0.3311 | 31.7% | 61.0% |
| **exp5 run 3 (r1/flash)** | **$0.0459** | **$0.0659** | **$0.1118** | **59.0%** | **92.1%** |

92.1% of total token volume, and for the first time **the minion cost more in absolute
dollars than Gru did** — the clearest evidence yet that the architecture can shift the
large majority of both cost and work to the cheap model. Three delegations this run
(t1: `findings`, a scoped search; t2 and t3: `verdict`, large agentic executions) versus
exp5 run 1's two — R1 delegated more readily and more heavily than DeepSeek-v4-pro did
under the same prompt, on top of doing far less work itself (5 turns vs. run 1's 23).

**The honest tension this leaves:** the run that shifted the most work to the cheap
model is also a run that failed, on the same task two prior successful architectures
(exp4 runs 1-4, 8, 10, 12) got right. This doesn't mean heavy delegation caused the
failure — the solo run failed identically without any delegation at all, so the actual
cause traces to R1's own diagnosis, not to the architecture. But it does mean this
project still doesn't have a single run that combines "most of the work shifted to the
cheap model" with "correct" — run 12 (exp4) came closest on the correctness-plus-real-
delegation front at 61.0% minion tokens; this run beats that on cost-shift but not on
correctness. The two things this project cares about — cost-shift and correctness —
still haven't been demonstrated together in the same run.

## What's still open

Not yet done: a genuinely controlled before/after for the `session_id` fix — the *same*
prompt configuration, run twice, once without `session_id` (impossible to reconstruct
now, since it's wired into every call unconditionally) and once with it, or at minimum
several repeats under the current fixed prompt to see whether run 1's 30% anomaly rate
is typical or itself an outlier. Also not yet done: repeating the r1/flash pair (or
trying a different, less reasoning-heavy premium model) to see whether R1's specific
diagnostic miss is a repeatable property of this model on this task, or this run's own
variance — and whether a correct diagnosis with a large minion-token-share is
achievable at all, or whether thoroughness (however cheaply purchased) and correctness
are pulling against each other on this specific two-part-fix task. Until either is
settled, exp5's central finding stays: the architecture *can* shift the substantial
majority of token volume and dollar cost to the cheap model (confirmed twice now, at
61% and 92%) — whether it can do that *and* stay correct, on this task, is still
unconfirmed.
