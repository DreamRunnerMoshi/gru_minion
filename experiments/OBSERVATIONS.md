# Interesting observations

A standalone list, pulled from `exp4`/`exp5`/`exp6`'s real data — written for external
reach-out (e.g. to researchers working on peer-delegation benchmarks like DecisionBench),
not as an experiment log. Each point links back to the file with the actual evidence.

## 1. Delegation is driven by content-fit, not wording forcefulness

A 12-run ablation on one SWE-bench instance, same model pair throughout, varying only
Gru's system prompt: persona framing ("Master Orchestrator"), a negative constraint
("forbidden from doing grunt work"), and an explicit "trust your peers" instruction all
failed to produce delegation on their own — in each case verified in the actual
trajectory that the model considered and explicitly declined delegating, not that it
never noticed the instruction. What worked was a concrete rule tied to the task's real
workflow shape. See [`exp4/NOTES.md`](exp4/NOTES.md) and
[`exp4/DELEGATION_FAILURE_MODES.md`](exp4/DELEGATION_FAILURE_MODES.md) for the verbatim
trajectory excerpts behind each failure mode.

## 2. Vendor swap alone moved GAIA resolve rate from 14% to 52%

Identical harness, identical prompt, identical 23-instance set — only the Gru/minion
model pair changed. That isolates a genuine capability difference from a harness or
prompt confound: the weaker pair's low score wasn't the benchmark or the architecture,
it was that specific model's own behavior (6 of 22 runs were give-up/refusal answers
under the weaker pair; zero under the stronger one). See
[`exp6/NOTES.md`](exp6/NOTES.md).

## 3. Paired mode never underperformed solo, across 3 independent vendor pairs

Qwen, GLM, and a GPT-family pair, each run solo and paired on the same SWE-bench
instances. Paired was never worse on the resolved-instance count, and in the one case
where the count matched exactly (n=5), the *same* instances were solved solo and paired
— not just the same number. See [`exp5/NOTES.md`](exp5/NOTES.md).

## 4. Token share, not dollar share, is the metric that survives pricing drift

Independently hit the same problem DecisionBench names in its own limitations (pool
freeze date / pricing drift): the same OpenRouter models were observed priced 20-30×
apart from each other in the morning and 9-15× by evening, same day, no model change.
Switched the project's primary cross-run metric from dollar share to token share in
response, since token counts don't move when a provider's pricing does. See
[`exp5/NOTES.md`](exp5/NOTES.md) (Findings 1-3) and
[`exp6/NOTES.md`](exp6/NOTES.md) (cache/cost sections).

## 5. The "verifiability trap" caught a real, otherwise-invisible failure

A delegated one-line edit was textually correct but broke indentation, causing full test
collection to fail — invisible to the minion's own summary, caught only because Gru's
own independently re-run check (not the minion's self-report) is what decides pass/fail.
Real example, both directions (a caught failure and a trusted pass), in
[`exp5/GRU_MINION_COMMUNICATION.md`](exp5/GRU_MINION_COMMUNICATION.md).

## 6. Three infrastructure bugs would have silently invalidated results if unfound

A patch-extraction bug made 5 genuinely correct sessions look like empty-patch failures
(the agent `git commit`ed its own fix, and a bare `git diff` showed nothing — fixed by
diffing against the pre-session commit instead). A cost-tracking gap made a real dollar
cap a silent no-op for specific models whose pricing wasn't in the local static registry.
And a self-authored prompt divergence mid-experiment — introducing a new tool schema and
rewriting shared prompt fragments instead of reusing them — was caught only because it
was checked directly; the confounded batch was deleted, not archived, and rerun. All
three are the kind of bug that produces a plausible, wrong number rather than a crash —
worth flagging because none of them were visible from the results alone, only from
checking the mechanism. See [`exp5/NOTES.md`](exp5/NOTES.md) and
[`exp6/NOTES.md`](exp6/NOTES.md)'s "Correction" section.

## 7. A tool-discoverability failure, and its limit

Gemini spent an entire 60-turn budget reinventing raw scrapers against 6+ dead-end
targets, never once checking what tools the sandbox actually provided — while GLM's
minion, given the identical tool, found it via a routine `find` after two failed
attempts. Fixed at the sandbox level (a `TOOLS.md` file in the working directory a
routine `ls` surfaces), not the prompt — verified live, 9x cost reduction on one
instance. But the fix has a real limit: it solved "does the model know the tool exists,"
not "does the model default to delegating repeatedly rather than reverting to
self-directed work after one delegation" — a separate, deeper behavioral trait left as an
open, documented finding. See [`exp6/NOTES.md`](exp6/NOTES.md).

## 8. Reasoning-model billing has a specific, non-obvious trap

Confirmed live: a reasoning model's `reasoning_content` counts as billed completion
tokens, not a free intermediate step. A low `max_tokens` cap can exhaust an entire
turn's budget on internal reasoning before any answer content is produced — the failure
looks like `LimitsExceeded`, not an obviously billing-shaped error. See
[`exp6/NOTES.md`](exp6/NOTES.md).

## 9. This project's own cache-hit estimate runs hot against reality

Real, provider-reported cache-hit rates (`usage.cached_tokens`) consistently come in
lower than this project's own local heuristic estimate, especially on short sessions
(a session with only 3-4 turns gets zero real cache benefit despite the heuristic
predicting some) — worth flagging as a general caution against trusting a local
cache-hit estimate over the provider's own reported number, whenever one's available.
See [`exp6/NOTES.md`](exp6/NOTES.md), "Cache hit stats" section.
