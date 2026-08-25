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

## What's still open

Not yet done: a genuinely controlled before/after — the *same* prompt configuration,
run twice, once without `session_id` (impossible to reconstruct now, since it's wired
into every call unconditionally) and once with it, or at minimum several repeats under
the current fixed prompt to see whether run 1's 30% anomaly rate is typical or itself
an outlier. Until that exists, exp5's cache-cost hypothesis is downgraded from
"diagnosed and fixed" to "diagnosed, a plausible fix implemented and verified to reach
the API, effect on actual cache behavior still unconfirmed." Only after that's settled
does it make sense to move on to exp4's actual closing brief for prompt work:
content-shaped, state-conditioned delegation rules, starting from a clean single-layer
baseline rather than continuing to stack changes, tested toward the real target metric
— minion's share of total token spend — not just "does delegation happen."
