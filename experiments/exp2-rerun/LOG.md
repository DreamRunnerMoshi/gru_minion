# Experiment 2 rerun: testing a fix for astropy-14182's regression

- **Status**: aborted — inconclusive on the original hypothesis, but surfaced a real, separate harness finding
- **Date**: 2026-08-22/23
- **Hypothesis under test**: [exp2](../exp2/LOG.md) regressed on `astropy__astropy-14182` (resolved by exp1's solo Qwen, unresolved by Gru+minion) because Gru's self-authored verification inherited the same narrow scope as whatever `context_gather` happened to surface — see [exp2/NOTES.md#verification-divergence](../exp2/NOTES.md#verification-divergence--gru-was-confidently-wrong-twice). Added a new ground rule to [prompts/gru-loop.md](../../prompts/gru-loop.md) / `orchestrator/config/gru.yaml`: before calling `finish`, mandatorily delegate one more `locate` for the existing test file(s) covering the changed behavior, even if already confident. Planned test: rerun `astropy-14182` alone, unfixed then fixed, same model, to see if this recovers the resolve.

## What actually happened

Three attempts on the same instance, same model, same infra pattern as exp2:

1. **Unfixed, attempt 1**: reached `t6` (a `synthesize` delegation that ran `pytest test_rst.py` and passed), then Gru wrote a prose-only response declaring the fix complete **without calling `finish`**, three times in a row — hit mini-swe-agent's `RepeatedFormatError` safety valve (`max_consecutive_format_errors=3`). Session ended abnormally; `run_exp2_single.py` at the time only extracted a patch via `result.get("submission")` on the happy path, so **the completed fix was lost** — 0-char patch despite real, apparently-passing work having been done.
2. **Unfixed, attempt 2** (after fixing the fallback-extraction gap below): reached `t3` (26 minion API calls in, mid-iteration, not stuck) before litellm raised `litellm.APIConnectionError: Ollama_chatException - {"error":"no user query found in messages"}` — an Ollama/litellm-side quirk in a long tool-calling conversation, not a bug in this project's code. This propagated up through Gru's own exception handling (by design — `DefaultAgent.run()` re-raises uncaught exceptions after saving) and crashed the whole process.
3. **Fixed** (`gru.yaml` with the new ground rule): reached `t4` (still all `context_gather` — never got to a `synthesize` step), then the **same prose-without-tool-call pattern as attempt 1** recurred — three `RepeatedFormatError` retries, no valid tool call, session ended abnormally with a 0-char patch (fallback `git diff` also returned empty since no code changes existed yet at that point).

**Two of three attempts hit the identical `RepeatedFormatError` pattern** — Qwen3.8:27b, after several delegations, sometimes writes a prose summary of its plan/conclusion instead of the mandatory tool call, and doesn't reliably self-correct within 3 retries even with explicit corrective feedback (`"No tool calls found in the response. Every response MUST include exactly one tool call."`) repeated verbatim each time.

## Real findings, despite the inconclusive result

- **A genuine harness robustness gap, found and fixed**: `run_exp2_single.py` only extracted the final patch via `result.get("submission")`, which is empty on any non-`Submitted` exit. Fixed with a fallback `git diff` against the shared testbed whenever the session ends any other way — real completed work should not be silently discarded because Gru's *last* message happened to be malformed. (Applied before attempt 2; confirmed working, though attempt 2's own patch was empty because the crash happened mid-`synthesize`, before any diff existed yet.)
- **A recurring model-behavior gap, not yet fixed**: Qwen3.8:27b's tendency to narrate a plan/conclusion in prose without a tool call, after several delegations, hit `RepeatedFormatError`'s 3-retry limit twice in three runs. This is orthogonal to the scope-narrowness hypothesis this rerun was meant to test — a harness-level issue (retry budget, feedback wording), not a verification-completeness issue.
- **The original hypothesis (does the pre-finish test-recheck rule recover `astropy-14182`) remains untested** — the one attempt that used the fixed prompt never survived long enough to reach a `synthesize` step, let alone `finish`.

## Next steps

1. **Raise `max_consecutive_format_errors`** (e.g. 3 → 6) in `orchestrator/config/gru.yaml` before attempting this test again — a harness-level fix, orthogonal to the prompt fix being tested, so it won't muddy the comparison when retried.
2. Retry the fixed-vs-unfixed comparison once that's in place. The ground-rule addition to `prompts/gru-loop.md`/`gru.yaml` is kept as-is (not reverted) since the reasoning behind it stands independent of this inconclusive test.
3. If `RepeatedFormatError` keeps recurring even with a higher retry budget, that becomes its own finding worth a dedicated look — possibly the format-error feedback message itself needs to be more directive after 1-2 failures, not just repeat the same text.

## Artifacts

Under `experiments/exp2-rerun/`: `unfixed-attempt1/console_output.txt` (console output only — trajectory was overwritten by attempt 2 before being pulled, a repeat of exp2's own artifact-loss lesson, at smaller scale this time), `unfixed-attempt2/` and `fixed-attempt1/` (full `gru.traj.json` + partial `minions/*.traj.json` up to the crash point, plus `console_output.txt`).
