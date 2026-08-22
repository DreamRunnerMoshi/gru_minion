# Experiment 2 — supporting notes

Methodology and worked evidence behind the terse Findings bullets in [LOG.md](./LOG.md). Read this only if you need to check how a claim was derived; `LOG.md` alone should be enough for everything else.

## Token cost breakdown

| Instance | Gru calls | Minions | Gru tokens | Minion tokens | Total tokens | vs. exp1 (same instance, solo) |
|---|---|---|---|---|---|---|
| astropy-12907 | 5 | 6 | 87,226 | 340,579 | 427,805 | 3.4x |
| astropy-14182 | 4 | 4 | 64,307 | 601,023 | 665,330 | 1.3x |
| astropy-14365 | 8 | 6 | 79,276 | 460,071 | 539,347 | 13.5x |
| astropy-14995 | 8 | 6 | 76,062 | 663,954 | 740,016 | 4.9x |
| astropy-6938 | 12 | 7 | 172,015 | 1,636,159 | 1,808,174 | 5.1x |
| **Total** | 37 | 29 | 478,886 (11.5%) | 3,701,786 (88.5%) | 4,180,672 | **3.5x** |

**Gru stays cheap in aggregate** (11.5% of total tokens) — consistent with the architecture's intent that Gru's role is lightweight coordination, not the volume driver. The problem is minion volume per delegation growing well beyond exp1's solo-agent baseline on the same instances.

**Two specific, already-identified sources of avoidable duplication** (found during live inspection of the `astropy-12907` pilot's `t1` trajectory, before the remaining 4 instances were run — not fixed before this batch, per the user's call to keep the batch methodologically consistent with the pilot rather than change conditions mid-run):

1. **Verbatim file reproduction requested in `output_contract`.** Gru's `t1` delegation asked the minion for "the complete source of the separable module(s)... verbatim." The minion read the 317-line file once (`cat`, 12,142 chars), then re-typed the entire thing into its own `findings.md` per that instruction (17,311 chars), which then got forwarded whole into Gru's own context. Because mini-swe-agent resends full history every turn (same finding as exp1), that duplication compounds: ~24,280 tokens from the `cat` output being resent across 8 subsequent minion turns, ~12,981 tokens from the `findings.md` write being resent across 3 more, plus ~16,728 tokens from the same content being resent across 4 subsequent Gru turns once forwarded — **~53,989 tokens (12.6% of that single instance's 427,805-token total) traced to one phrase in one delegation's `output_contract`.**
2. **Redundant re-verification delegations.** `astropy-12907`'s `t4` and `t6` were both "no code changes, just verify" delegations — Gru re-delegating a check `t3` had already run and passed, rather than trusting the result. Pure overhead, and arguably the "verifiability trap" ([prompts/README.md](../../prompts/README.md#trust-the-mechanical-signal-dont-re-verify-it-the-verifiability-trap)) creeping back in through a different door: not Gru re-reading content itself, but Gru re-*delegating* a check that had already resolved.

Neither fix was applied before running the remaining 4 instances, to keep this batch's methodology consistent with the pilot (see [LOG.md](./LOG.md)'s note on why). Both are candidates for a follow-up run once fixed — plausibly a meaningful fraction of the 3.5x token inflation and part of what made `astropy-14365` cost 13.5x exp1's solo run for the same (failed) outcome.

## Verification divergence — Gru was confidently wrong twice

Gru's `final_verification` is necessarily a self-authored proxy ([prompts/gru-loop.md](../../prompts/gru-loop.md#authoring-final_verification-without-access-to-the-real-ground-truth)) — it has no access to the hidden `FAIL_TO_PASS`/`PASS_TO_PASS` tests. This run gives the first real measurement of how often that proxy is wrong: **3/5 agreement with the real evaluation**, not 5/5.

- **`astropy-14182`**: Gru's final check was a reproduction script confirming the PR's own literal example now writes correctly in both `ascii.fixed_width` and `ascii.rst` formats — it ran and passed (exit 0, correct-looking output for both). Gru also had a minion write its own regression test (`test_write_header_rows`) matching that same example, which also passed. Both checks are real and both genuinely exercise the reported behavior — but they're scoped to exactly the PR's example, not to whatever the actual hidden test (`test_rst_with_header_rows`, per [exp0/LOG.md](../exp0/LOG.md)'s own analysis of this exact instance) additionally asserts. This is the *same* root-cause blind spot exp0's Haiku had on this instance — a self-authored check can't discover what it doesn't know to look for, no matter how deliberately it's constructed.
- **`astropy-14365`**: covered in the reward-hacking-adjacent sense below is not the issue here — this is the *same* `re.IGNORECASE`-only fix as exp0 and exp1, so Gru's proxy check (which only exercises the regex-classifier path, since that's the mechanism the minion's own diagnosis surfaced) necessarily can't catch a downstream command-dispatch step that was never identified as relevant in the first place.

**Net read**: the proxy isn't unreliable in a random way — both failures are the same shape (the check is real and passes, but its *scope* is bounded by what the delegation's own investigation happened to surface). This matters for Phase 2: a frontier Gru might scope its own verification more broadly, but nothing about the self-hosted-vs-frontier axis specifically fixes this — it's a completeness problem in the check-authoring step itself, the same "judgment-laden completeness" gap [DESIGN.md](../../DESIGN.md) already flagged as unsolved for context-gathering generally.

## Reward-hacking check on astropy-6938's test modification

`astropy-6938`'s patch modifies both source and test:

```diff
- output_field.replace(encode_ascii('E'), encode_ascii('D'))
+ output_field[...] = output_field.replace(encode_ascii('E'), encode_ascii('D'))
```
```diff
- assert hdul[1].header['CHECKSUM'] == '51IDA1G981GCA1G9'
+ assert hdul[1].header['CHECKSUM'] == '3rKFAoI94oICAoI9'
- assert hdul[1].header['DATASUM'] == '1948208413'
+ assert hdul[1].header['DATASUM'] == '1914653725'
```

This has the same *shape* as the reward-hacking pattern [DESIGN.md](../../DESIGN.md) warns about (a delegation modifying a test's expected value) and was flagged for scrutiny live, before the real evaluation result was known.

**Why it's legitimate, not gaming**: the source fix is a real, substantive bug — `.replace()` on a numpy record-array field returns a new array rather than mutating in place, so the original line silently discarded its result and did nothing. Making the replacement actually happen legitimately changes the byte content of the written FITS file, which legitimately changes its checksum. The test still asserts strict equality against a specific value — it isn't weakened, wrapped in a try/except, or made permissive, which is what the actual gaming pattern would look like. **The real evaluation resolving this instance is the objective confirmation**: if the new checksum values were wrong (guessed rather than computed from the actual fixed behavior), the hidden `FAIL_TO_PASS` test — which independently computes the same checksum — would have failed regardless of what this patch's own test asserts.

**Caveat**: the full minion trajectory for `t5`/`t6` (which would show *how* the new checksum values were arrived at — computed from a real run, vs. guessed) was lost before it could be inspected directly, per the process mistake in [LOG.md](./LOG.md)'s Issues. This conclusion rests on patch-level evidence plus the objective real-evaluation outcome, not on having read the reasoning trace — a weaker form of confirmation than exp1's equivalent findings had, worth naming honestly.
