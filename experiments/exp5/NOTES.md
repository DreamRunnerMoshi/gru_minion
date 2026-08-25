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

## Runs 4+: the cross-vendor batch — three pairs, solo vs. paired, real SWE-bench eval

Runs 2-3 left the cost-shift/correctness tension unresolved on a single R1/flash pair
and a single instance. To get more than n=1, the user asked for more pairs "from
different models" and a full run across the 5-instance set (the same 5 astropy
instances used throughout exp3-5), solo and paired, per pair — scoped down from "all of
SWE-bench Lite" via an explicit tradeoff question, landing on 3 pairs (Qwen, GLM,
OpenAI) x {solo, paired} x 5 instances = 30 configs, budget-capped against the
project's remaining $5.33 of OpenRouter credit (real balance checked live via
OpenRouter's `/credits` endpoint before every run, not self-tracked spend — see
`scripts/exp5_batch.sh`).

Pairs (same-vendor Gru/minion, real OpenRouter pricing per M tokens, verified live):

| Pair | Gru | Minion | Gru $/M | Minion $/M |
|---|---|---|---:|---:|
| qwen | qwen/qwen3-max | qwen/qwen3-coder-flash | $0.78 / $3.90 | $0.195 / $0.975 |
| glm | z-ai/glm-4.6 | z-ai/glm-4.5-air | $0.50 / $2.00 | $0.13 / $0.85 |
| gpt | openai/gpt-5-mini | openai/gpt-4.1-nano | (tracked via real `usage.cost`) | $0.10 / $0.40 |

**Two infrastructure bugs surfaced mid-batch, both fixed and both real, not
task-specific:**

1. **Silent cost-tracking failure for non-DeepSeek models** (exp5.12): mini-swe-agent's
   own cost tracker uses litellm's static local price registry, which doesn't have
   every OpenRouter model in it. For `qwen/qwen3-max` this silently tracked $0.0 for a
   call OpenRouter itself billed $0.0017 for — `MSWEA_COST_TRACKING=ignore_errors`
   swallowed the lookup failure rather than raising it. This made `--cost-limit` a
   silent no-op for any such model — caught live via a raw HTTP response showing real
   nonzero cost against a $0.0 tracked cost. Fixed by having `GruModel`/`MinionModel`
   prefer the response's own real `usage.cost` field (OpenRouter always reports this;
   `orchestrator/real_cost.py`, pinned by `tests/test_real_cost.py`). One already-run
   config (`qwen-solo/astropy-12907`, and separately `qwen-paired/astropy-12907`, same
   bug window) had to be deleted and rerun under the fix.

2. **Patch-extraction bug via `git commit`** (exp5.16): `openai/gpt-5-mini` routinely
   commits its own fix as a normal part of its workflow — something no other model in
   this project's history has done. `_finish()` used to read a bare `git diff` (working
   tree only), which shows nothing once a change is committed. Gru's own
   `final_verification` still genuinely passed (the fix really was in the repo), so it
   submitted believing it had a real patch, and the harness silently recorded an empty
   one. **All five `gpt-solo` runs and two of five `gpt-paired` runs** (`astropy-12907`,
   `astropy-14182` — same Gru model) were reported as real SWE-bench failures
   ("unresolved, empty patch") that were actually this bug, not a capability finding —
   confirmed unrecoverable for the original containers (searched every trajectory
   message for diff content; found none, only `git show --name-only` filename
   listings). Fixed via `GruEnvironment.initial_commit` (captured at session start) +
   `git diff {initial_commit}` in both `_finish()` and the crash-fallback path in
   `run_gru_session.py`, pinned by a regression test
   (`test_finish_captures_the_patch_even_if_gru_committed_it`). All 7 affected configs
   were deleted and rerun under the fix; every retry produced a real, non-empty patch.

A third thing worth recording as a finding, not a bug: `glm-paired/astropy-14182` hung
twice, independently, with zero CPU/log activity for 15+ minutes the first time and
confirmed-zero-progress again on a retry — the same model pair, same instance, same
failure mode. Abandoned after the second hang (not essential to the batch, budget was
tighter by then); `glm-paired`'s real evaluation is 4 completed instances, not 5.
Separately, `qwen-solo/astropy-14995` produced a genuinely empty patch for a different,
legitimate reason: it hit `LimitsExceeded` (the real `--cost-limit` cap) mid-debug,
still failing its own reproduction script, with no working fix in the tree yet — not a
patch-extraction artifact, an honest budget-exhaustion case.

### Results: resolved rate, real SWE-bench evaluation, all 6 groups

| Group | Resolved | Completed | Empty patch |
|---|---:|---:|---:|
| qwen-solo | 2/5 | 4/5 | 1 (budget exhaustion, legitimate) |
| qwen-paired | 2/5 | 5/5 | 0 |
| glm-solo | 3/5 | 5/5 | 0 |
| glm-paired | 3/4 | 4/5 | 0 (1 instance abandoned: reproducible hang) |
| gpt-solo | 3/5 | 5/5 | 0 (post-fix; was 0/5, all empty-patch, pre-fix) |
| gpt-paired | 3/5 | 5/5 | 0 (post-fix; 2/5 were empty-patch, pre-fix) |

No pair shows a clean solo-vs-paired resolve-rate difference on this 5-instance set —
qwen and gpt are flat (2-vs-2, 3-vs-3), glm is flat modulo the abandoned instance
(3-vs-3 on the 4 glm-paired actually completed). On this sample size, delegation isn't
costing correctness anywhere, but it isn't demonstrably buying it either — the
resolve-rate signal is just noise-dominated at n=5 per group.

### Results: where the tokens and dollars actually go

Gru $ is real (tracked via `usage.cost`, post exp5.12 fix). Minion $ isn't persisted in
`cost_summary.json` per-call, so it's estimated here from minion prompt/completion
token counts at each model's list price — an upper-bound estimate that ignores prompt
caching, so real minion $ share is likely somewhat higher than shown (caching would
lower minion $ less than it lowers Gru $, since Gru's system prompt is the larger fixed
cost). Solo rows show 0% by construction — solo has no minion.

| Pair | Mode | Gru tokens | Minion tokens | Minion tok share | Gru $ | Minion $ (est.) | Minion $ share (est.) |
|---|---|---:|---:|---:|---:|---:|---:|
| qwen | solo | 2,292,956 | 0 | 0% | $0.7805 | — | — |
| qwen | paired | 1,958,387 | 7,184,118 | **78.6%** | $0.8189 | $1.5045 | **64.8%** |
| glm | solo | 3,347,256 | 0 | 0% | $0.7306 | — | — |
| glm | paired | 1,364,969 | 2,193,886 | **61.6%** | $0.2660 | $0.3311 | **55.5%** |
| gpt | solo | 1,872,249 | 0 | 0% | $0.1451 | — | — |
| gpt | paired | 1,551,914 | 18,542,343 | **92.3%** | $0.1789 | $1.8883 | **91.3%** |

Every paired run shifts the majority of both tokens and dollars to the minion — this
now holds across three independent vendors, not just the one DeepSeek pair from runs
2-3, and the gpt pair pushes past run 3's 92.1% token share while landing squarely in
"correct" territory (3/5 resolved, same as its solo baseline). That combination —
large minion share *and* correct — that runs 2-3 explicitly flagged as unconfirmed, now
has real instances (gpt-paired's 3 resolved astropy instances each ran with the vast
majority of tokens and dollars on the cheap model). The unresolved tension from runs
2-3 (heavy delegation vs. correctness) doesn't reproduce at this pair/task combination —
gpt-paired resolves exactly as many instances as gpt-solo, while moving 92% of tokens
and an estimated 91% of dollars to `gpt-4.1-nano`.

qwen is the standout on delegation *frequency and readiness*, not magnitude — 78.6%
token share is the middle of the three, but qwen-paired's own results_table shows the
heaviest and most consistent per-instance delegation counts of any pair (see
`experiments/exp5/results/qwen-paired/results_table.md`).

### Operational footnote: vast.ai provisioning

Three attempts to spin up a second, purpose-sized instance all failed (wrong image tag,
a host that doesn't support VM-style images, one stuck permanently at `created`) before
discovering the existing instance (48577034) already had 88 vCPU/128GB RAM — bigger
than any offer being chased. All three failed instances were destroyed
(`vastai destroy instance <id> -y`); the whole batch ran on the pre-existing instance.

## What's still open

The `session_id` fix still has no genuinely controlled before/after (the *same* prompt
configuration, run twice, once without `session_id` and once with it) — impossible to
reconstruct now that it's wired into every call unconditionally. Real per-minion-call
`$` tracking (not just tokens) remains a gap — `cost_summary.json` tracks minion tokens
exactly but not minion dollars, so every minion $ figure in this document is a
list-price estimate, not a tracked one. And resolve rate is still noise-dominated at
n=5 per group — enough to confirm the token/cost-shift finding holds up across three
vendors, not enough to say anything sharper about correctness than "delegation didn't
cost any of these three pairs a single resolved instance." Until either is settled,
exp5's central finding stays: the architecture reliably shifts the substantial majority
of both token volume and dollar cost to the minion (61-92% of tokens, 55-91% of
estimated dollars, across four independent model pairs now — DeepSeek, Qwen, GLM, and
GPT) and, at least at this sample size, without a visible cost to correctness.
