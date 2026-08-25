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

Not yet run live. The next step is a direct before/after comparison: re-run one of exp4's
existing prompt configurations (a run with a clear anomaly signature, e.g. run 10's or
run 11's) on the same instance with `session_id` now wired in, and check whether the
per-call cache-hit-rate anomalies are gone and whether `$` drops by roughly the predicted
amount. Only after that's confirmed does it make sense to move on to exp4's actual
closing brief for prompt work: content-shaped, state-conditioned delegation rules,
starting from a clean single-layer baseline rather than continuing to stack changes,
tested toward the real target metric — minion's share of total token spend — not just
"does delegation happen."
