# Experiment 7 — metrics instrumentation + GLM 5.3 pair smoke tests

While scoping a publishable Gru/minion report, two logging gaps surfaced: per-action
cost was computed but never persisted (only formatted into display text), and a verdict
delegation's independently re-run `checks_passed` was computed but discarded before it
reached the saved record. Both fixed in `8fecb3a` (`_turn_usage()` attached to every
`gru_action_log` entry; `checks_passed` — `None` for findings, real bool for verdicts —
added to `minion_records`). This experiment is the fix's own validation: two small runs
that exercise it directly, not a formal batch.

## What ran

1. **Single-instance smoke test** — `gru=glm-5.3`, `minion=glm-5.3-flash`,
   `astropy__astropy-14365`
   ([glm5.3-vs-glm5.3-flash-single/glm53-single/](../glm5.3-vs-glm5.3-flash-single/glm53-single/)).
   The minion's verdict delegation came back with `checks_passed: false` — but the
   session still finished with `final_verification_passed: true`. Reading the trace:
   the two failing checks were flaws in Gru's *own* re-run assertions (column-interleave
   order, an all-`NO` line being a QDP separator), confirmed against pristine code, not
   bugs in the minion's fix. This is exactly the distinction `checks_passed` exists to
   make — "the minion was wrong" vs. "my own check was wrong" — that a single lumped
   pass/fail couldn't have surfaced before this fix.

2. **5-instance batch, `glm-5.2:free` as minion** — `gru=glm-5.3-flash`,
   instances 12907, 14182, 14365, 14995, 6938
   ([glm-5.3-flash-vs-glm-5.2-free/glm-batch/](../glm-5.3-flash-vs-glm-5.2-free/glm-batch/)).
   3/5 crashed with an OpenRouter `RateLimitError` before any delegation occurred; the
   other 2 (14182, 14365) never delegated at all and passed final verification solo.
   Not an architecture finding — OpenRouter's free-tier rate limit makes `glm-5.2:free`
   unusable as a minion in this harness as-is, independent of anything about Gru/minion.

## Status

Raw run data only — no evaluation report, no batch large enough to belong in the
headline-findings table. Recorded here so the rate-limit finding isn't lost.
