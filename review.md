# Design & Experiment Review

- **Status**: review complete, no changes applied
- **Date**: 2026-08-22
- **Scope**: whole project — hypothesis, prior-art reasoning, architecture decisions, `orchestrator/` implementation, exp0/exp1/exp2 results
- **Method**: every quantitative claim re-derived from raw artifacts, not read from `LOG.md`. See [Provenance](#provenance--what-was-verified-how) for what was checked directly vs. inferred vs. unverifiable.
- **Companion**: `review_opus.md` — point-by-point responses. Every finding below has a stable ID; reference those. IDs are stable identifiers, not an ordering — later-numbered findings sometimes sit earlier in the document.
- **Revised 2026-08-22** after review discussion and a primary-source verification pass: `R1` rewritten against the actual papers; `R4`/`R12` rescoped against Phase 1's own success criteria; `R13`–`R17` added; [Source verification](#source-verification) records what the three checked citations actually say; [Changes implemented](#changes-implemented) records what was acted on. Written as current-best-understanding per [EXPERIMENT_LOG_FORMAT.md](EXPERIMENT_LOG_FORMAT.md)'s correction convention, not as a transcript of what changed.

## Verdict

The engineering discipline and self-honesty are unusually good — token accounting reconciles exactly, gaps are flagged rather than papered over, and the project pressure-tests its own hypotheses. Four things need attention before Phase 2:

1. **The architecture has the right topology but not the mechanism that makes it work** (`R1`, `R2`) — verified against primary sources. Both working systems in the prior art put a filter or a strong curation tier between cheap exploration and frontier reasoning. This one has neither, and Gru cannot explore for itself.
2. **The failure mode is incompleteness, not hallucination** (`R15`) — measured against surviving trajectories, correcting a working assumption. Minions do not fabricate; they answer accurately and narrowly. That changes which fix is correct.
3. **exp2 states conclusions Phase 1 forbids it from stating** (`R3`, `R4`) — the resolve verdict is hand-transcribed for 4 of 5 instances, and the comparison it drives is one the project's own scoping rule says explicitly not to make.
4. **Observed Gru behavior diverges from the documented design in two load-bearing ways** (`R5`, `R13`) — delegations were batched rather than sequential, and Gru specifies edits at line level despite a ground rule forbidding it. The second appears to be *helping*.

Nothing here invalidates the project. The cheapest high-value moves are editorial (`R3`, `R4`, [Source verification](#source-verification)) and one build (`R15`).

---

# Tier 1 — threatens core validity

## R1 — Right topology, missing mechanism

**Status**: verified against primary sources 2026-08-22 — the original research pass was never checked. All three citations are real and their headline numbers accurate; all three summaries are lossy in ways that change the design implication. Details in [Source verification](#source-verification).

**Claim**: The effective topology matches SuperScout/AI21 — frontier does the code cognition, cheap tier executes. But the mechanism both papers identify as load-bearing — a filter or curation tier between cheap exploration and frontier reasoning — is absent here, and Gru cannot compensate by exploring itself.

**What the delegation content shows.** This is the measurement that settles the topology question; the system prompt and the `type` distribution both mislead. Across all 16 `synthesize` delegations:

| Instance | Gru's synthesize delegation | Resolved |
|---|---|---|
| 12907 t3 | exact file, exact function, exact line, exact replacement expression | ✅ |
| 14182 t3 | exact file, exact signature change, exact `super()` call, exact index logic | ❌ |
| 14995 t5 | exact method, exact file, exact required behavior | ✅ |
| 6938 t3 | exact file, **line numbers 1262–1264**, exact expression, full diagnosis | ✅ |
| 6938 t5/t6 | exact old value → exact new value for both checksums | ✅ |
| **14365 t2** | *"Make QDP command parsing case-insensitive, and add a regression test."* | ❌ |

In **4 of 5 instances Gru wrote the patch and the minion typed it.** Reading `prompts/gru-loop.md`'s *"You do not write code yourself"*, or the 16-of-29 `synthesize` count, as evidence that the cheap tier does the code cognition is wrong — the delegation bodies say the opposite.

**The number that matters.** SuperScout's verify-then-strip gate replays every reproduction claim against the unpatched repo. Of **249 claims from the 7B scout, only 50 (20%) were genuine**; 174 were demonstrably false and stripped, 25 errored. That is the empirical content of *"the verified handoff drove the gain."* [`PLAN_FORMAT.md`](PLAN_FORMAT.md) specifies the opposite for `context_gather`/`locate`: **raw verbatim passthrough, no extraction or verification step.**

**Qualifier that changes the fix** (`R15`): this project's minions are measurably **not** producing false claims. The gap is real, but it is a *coverage* gap, not a *truth* gap, and SuperScout's gate ported directly would strip nothing here.

**All three sources converge on the same thing** — the frontier tier must be present where information density is highest:

- **SuperScout / AI21**: cheap may explore, *if* the handoff is mechanically filtered (80% stripped) or curated by a strong mid-tier (AI21 interposes GPT-5.2 between explorer and patcher).
- **Stencil**: the one measured loser is a frontier model working from a brief instead of exploring itself — `/plan` at $3.18/84.6% vs. solo at $2.78/84.6%. Its recommended configuration, `/prewalk`, is *frontier explores then cheap executes* ($1.04 @ 85% vs. $1.71 @ 88% solo).

**Where Gru sits**: Gru has **no repo access** — its only tools are `delegate_to_minion` and `finish`. It cannot explore; everything it knows arrives as a minion report. In Stencil's vocabulary that is `/plan`, not `/prewalk` — the configuration Stencil measured as the loser.

**Augment/Stencil differentiation — confirmed, gap closed.** `/plan` is genuinely upfront-batch (*"creates a comprehensive plan document upfront before execution begins — no interleaving"*), so the interleaving argument does differentiate this system from the counter-example. The provenance gap previously flagged here is closed in the project's favor; the fact now needs adding to the literature-review entry.

**Recommendation** — two independent moves:
1. **Give Gru read-only repo access** (`grep`, `cat`, a test invocation). `_run_checks` already executes against the shared testbed, so the plumbing exists. This converts Gru from `/plan` to `/prewalk` without touching the delegation design.
2. **Coverage receipts on the exploration handoff** — see `R15`.

## R2 — ORACLE-SWE is read backwards

**Claim**: The +12.3pp localization result is cited as evidence that localization is menial and delegable; it is evidence that localization is the hardest, highest-leverage step.

**Evidence**:
- [`literature-review/2604.07789`](literature-review/2604.07789-oracle-swe-localization-bottleneck.md): *"validates this project's core intuition behind splitting menial context-gathering work (which a cheaper minion can do) from high-cognition code synthesis."*
- `DESIGN.md:38` repeats it; `literature-review/README.md`'s summary table repeats it a third time.
- `DESIGN.md`'s own "Important nuance surfaced during design" paragraph **contradicts all three**: *"judgment-laden curation (which of 200 references actually matter, did we find everything relevant) — this is often as hard as code-writing and is exactly where missed implicit invariants live."*
- exp2 assigned 13/29 delegations (`context_gather` + `locate`) to the weak minion. **Both failures were scope/localization failures** — `experiments/exp2/NOTES.md` diagnoses this correctly and independently: *"the check is real and passes, but its scope is bounded by what the delegation's own investigation happened to surface."*

**Why it matters**: a step worth 12.3pp of resolve rate is not the step to hand the weakest model. The experiment reproduced the paper's finding and the docs didn't connect them. This compounds `R1`: localization is simultaneously the highest-leverage step *and* the one delegated to the cheap tier with no verified handoff.

**Recommendation**: rewrite the "What we took from it" section of the ORACLE-SWE entry to match `DESIGN.md`'s own nuance paragraph, and propagate to `DESIGN.md:38` and the README table. Then re-ask whether `context_gather`/`locate` belong on the cheap tier at all — the answer may be "the cheap tier executes the search, Gru specifies and audits its coverage," which is what `search_strategy` was already reaching for.

## R15 — The failure mode is incompleteness, not hallucination

**Status**: premise tested against surviving trajectories 2026-08-22. Corrects a working assumption held during design discussion ("the minion is hallucinating / verifying incorrectly"). It is not.

**Claim**: exp2's minions did not fabricate. Every finding traces to a command that actually ran. The failures are coverage failures.

**Evidence** — `experiments/exp2/trajectories/t1`–`t6` (`astropy-12907`, the only instance whose minion trajectories survived):
- **t1** transcribed the 317-line `separable.py` into `findings.md`, then self-verified **unprompted**: `sed -n '/^\`\`\`python$/,/^\`\`\`$/p' findings.md | sed '1d;$d' > /tmp/extracted.py && diff -u ... && echo IDENTICAL`. Trajectory message [22]: **`IDENTICAL`** — byte-for-byte match against the real file.
- **t2** ran the reproduction for real, probed `inner.separable` and `inner._separable` in live Python, and grep'd the exact buggy line to confirm it existed.
- **t3** and **t5** used `git stash` / `git stash pop` to establish genuine pre-fix baselines before attributing test failures as pre-existing.
- Both exp2 failures had **accurate** findings: `14182`'s gathering was correct but never covered what `test_rst_with_header_rows` additionally asserts; `14365`'s case-sensitivity analysis was correct but never reached the downstream exact-case dispatch.

**Why it matters**: SuperScout's 80%-false rate (`R1`) comes from a 7B scout making reproduction claims **it never ran**. These minions run everything. Porting SuperScout's verify-then-strip gate directly would strip nothing. Same-shaped gap, different mechanism required.

**Rejected — a Gru verification pass over returned content** (considered and declined 2026-08-22):
- It would not have caught either failure. Gru re-reads findings that are true and correctly concludes they are true.
- It is the weakest verification available, by the project's own [LLM-Modulo](literature-review/2402.01817-llms-cant-plan-llm-modulo.md) citation — LLMs *"frequently accept their own flawed self-generated plans as valid."* This is model self-assessment one step removed.
- It reinstates the every-completion Gru cost `DESIGN.md` explicitly rejected, in exchange for the least informative signal available.
- It would **not** violate the verifiability-trap principle — that scopes to content a real check already confirmed, and `context_gather` has none. The objection is cost and efficacy, not self-consistency.

**Adopted instead — verify coverage, not truth**:
1. **Coverage receipts.** `output_contract` for `context_gather`/`locate` changes from a prose shape to: the exact command run, its complete output, the full candidate set returned, and per candidate either an examination or an explicit rejection reason. The orchestrator re-runs the command through the existing `_run_checks` and asserts the candidate set matches — silent dropping becomes a failed check. Catches `14365` directly: six sites returned, three discussed → check fires, and the dispatch step is among the unexamined three.
2. **Negative space, minion-side.** Require every gathering delegation to report what it searched and found nothing in. This is the useful half of the Gru-pass instinct, relocated to the cheap tier; Gru's existing judgment step then has something to judge.
3. **`search_strategy` gets teeth.** It currently names a method and proves nothing was done with it — make it emit the receipt from (1).

**The irreducible residual**: `14365` has now failed identically across three architectures — Haiku solo, Qwen solo, Gru+minion — including a run where Gru *explicitly* delegated a hunt for case-sensitivity sites. Nothing in the issue text points at the dispatch step; only walking the code path outward from the changed symbol reaches it. `DESIGN.md`'s structural-graph proposal ([Code Isn't Memory](literature-review/2606.22417-code-structural-index.md)) is the one idea in the design that plausibly cracks this, and it remains unbuilt. **Promoted from deferred sub-design to next real experiment.**

## R3 — exp2's headline 3/5 is not machine-verified

**Claim**: The resolve verdict driving exp2's Findings and Conclusion is hand-transcribed for 4 of 5 instances.

**Evidence**:
- `experiments/exp2/results/summary_report_5instances.json` — its own `note` field: *"reconstructed from conversation record, not a machine-generated file."*
- Schema comparison: exp1's report carries `schema_version: 2`, `failure_reasons`, `ambiguous_failure_instances`, `unstopped_instances` (genuine harness output). exp2's has **none of these** — it is a hand-authored subset of the schema.
- Only `experiments/exp2/results/astropy-12907/eval_report.json` exists as a real per-instance harness report. No `eval_report.json` for 14182, 14365, 14995, 6938.
- `experiments/exp2/LOG.md` Results table presents **3/5** with no caveat; the caveat exists only inside the JSON and in one word of the Artifacts line ("reconstructed").

**Why it matters**: two Findings bullets and the entire Conclusion rest on 3/5 vs. exp1's 4/5. That comparison currently rests on a transcription for 80% of its data points.

**Recommendation**: `predictions_all5.json` is intact — re-run `run_evaluation` on it (one VM-hour) and replace the file with genuine output. Until then, the caveat belongs in the Results section where the number is, not only in the artifact.

## R4 — exp2 makes a resolve-rate claim its own Phase 1 rule forbids

**Claim**: The issue is not sample size. The experiment had a scoping rule and broke it.

**Evidence**:
- [`design/infra/04-machine-config.md`](design/infra/04-machine-config.md) §9, explicit: *"Resolve rate and cost/token spend are **not** the point of Phase 1 and shouldn't be read as signal either way — a bad resolve rate at this stage could mean the framework works but the open model is weak, or the framework itself is still broken; Phase 1 alone can't distinguish those, and isn't trying to."*
- [`experiments/exp2/LOG.md`](experiments/exp2/LOG.md) Findings makes exactly that reading: *"the Gru/minion architecture in this raw form was net-negative on this small sample, not neutral — **a real result**."* The Conclusion then turns it into a gating decision.
- The claim could not carry weight even if it were in scope:

| Test | Result |
|---|---|
| exp2 3/5 vs. exp1 4/5, Fisher exact two-sided | **p = 1.0** |
| Paired (same instances), 1 discordant instance (14182), McNemar exact | **p = 1.0** |
| 95% Wilson CI, 3/5 | **[0.231, 0.882]** |
| 95% Wilson CI, 4/5 | **[0.376, 0.964]** |

- All 5 instances are **astropy**, selected by dataset order; [`experiments/exp0/LOG.md`](experiments/exp0/LOG.md) flagged this (*"use a stratified/random sample next time"*) and the caveat never propagated forward. Every instance ran **once**, against the project's own [Token Economics](literature-review/2605.09104-token-economics-llm-agents.md) finding of **up to 30× run-to-run variance** and [`experiments/exp1/NOTES.md`](experiments/exp1/NOTES.md)'s note to build repeats into later designs.

**Why it matters**: exp1's LOG was well-calibrated on the same sample size (*"a real, if small, capability data point"*). exp2 regressed on calibration while its underlying evidence got weaker (`R3`).

**Recommendation**: **editorial, not experimental.** Keep the observations — 3/5 resolved, 3.5× tokens, ~3.9× wall-clock, the harness ran end to end. Strike the interpretation ("net-negative", "a real result", and the gating language in the Conclusion). No additional instances are needed, because Phase 1 does not want a resolve-rate claim. If one is wanted later, it needs ≥3 repeats per instance and a stratified multi-repo subset — that is Phase 2's problem.

---

# Tier 2 — defects in code and trajectories

## R5 — `parallel_tool_calls: false` was silently dropped; Gru batched delegations

**Claim**: exp2 did not run the architecture it documents. Gru issued multiple delegations per turn without observing intermediate results.

**Evidence**:
- `experiments/exp2/trajectories/gru.traj.json`, assistant messages **[2] and [7] each carry two `delegate_to_minion` actions** (t1+t2 fired together; t4+t5 fired together). **4 of the pilot's 6 delegations** were issued blind.
- `orchestrator/config/gru.yaml` sets `parallel_tool_calls: false` — but also `drop_params: true`. Ollama's OpenAI-compatible endpoint does not support the param; litellm dropped it silently.
- Not recorded in `experiments/exp2/LOG.md` Issues.

**Why it matters**: the entire 2026-08-21 correction (`prompts/README.md` revision history) exists to establish *"Decide the next step, act on it, learn from the result, decide the next one."* Batched delegation is the ReWOO-style design that correction explicitly rejected. exp2 measured a hybrid of the two and reported it as the ReAct design.

**Recommendation**: drop `drop_params: true` for Gru (or enforce single-action in `parse_gru_actions` — one line, and it fails closed rather than depending on provider support). Re-run at least the pilot before drawing architecture conclusions.

## R6 — `NOTES.md` misdiagnoses t4/t6, and prescribes the harmful fix

**Claim**: The "redundant re-verification" finding is factually wrong, and the fix it recommends would make things worse.

**Evidence**:
- `experiments/exp2/NOTES.md`: *"`t4` and `t6` were both 'no code changes, just verify' delegations — Gru re-delegating a check `t3` had already run and **passed**, rather than trusting the result... arguably the 'verifiability trap' creeping back in through a different door."*
- The trajectory says otherwise. `gru.traj.json` message **[6]: `Delegation t3 (synthesize): FAIL`** (returncode 1). Message **[8]: `Delegation t4 (synthesize): FAIL`**. Only **[11]: `Delegation t6 (synthesize): PASS`**.
- Gru's own reasoning, message [7]: *"The `AttributeError` in `is_separable` is **my bug in the check script**, not their bug."* t6's delegation description confirms the correction: *"the `is_separable` expectation for the Pix2Sky_TAN case is intentionally `[False, False, True, True]`..."*

**Actual root cause**: Gru authored a buggy check command, and **has no way to re-run a corrected check except by spawning a full no-op minion session**. `_run_checks` in `orchestrator/gru_environment.py` is reachable only via `_delegate` (synthesize) or `_finish`. t4 + t6 burned **20,088 tokens and 9 API calls** running shell commands.

**Why it matters**: the recommended fix ("trust the result, don't re-delegate") is wrong — the check genuinely had not passed. Following it would suppress a legitimate retry. And `experiments/exp2/LOG.md`'s Conclusion makes fixing these two items **the gate on further runs**, so the misdiagnosis is on the critical path.

**Recommendation**: correct the NOTES entry. Add a third Gru action — `run_check(checks: [str])` — dispatching straight to `_run_checks` with no minion spawned. This also gives Gru a cheap way to validate its own check syntax before spending a delegation on it.

## R7 — "A subtask that touches tests can never verify itself" is prompt-only, and was violated 5/5

**Claim**: The invariant the design's safety story rests on is unimplemented, and was broken in every instance.

**Evidence** — every submitted patch modifies a test file:

| Instance | Test file touched |
|---|---|
| 12907 | `astropy/modeling/tests/test_separable.py` |
| 14182 | `astropy/io/ascii/tests/test_rst.py` (+ stray `repro_rst_header_rows.py`, see `R8`) |
| 14365 | `astropy/io/ascii/tests/test_qdp.py` |
| 14995 | `astropy/nddata/mixins/tests/test_ndarithmetic.py` |
| 6938 | `astropy/io/fits/tests/test_checksum.py` |

- In the pilot: **t3 authored `test_separable.py`**, and `final_verification` ran `pytest astropy/modeling/tests/test_separable.py` (per `cost_summary.json`'s `final_verification_output`). The delegation was verified through a test it wrote.
- The invariant is stated in `prompts/gru-loop.md`, `prompts/minion-execution.md`, and `PLAN_FORMAT.md`. **No code in `orchestrator/` enforces it.**
- `experiments/exp2/NOTES.md`'s reward-hacking audit examined only `astropy-6938` — the one instance where the pattern was conspicuous — while the same shape was present in all five.

**Mitigating fact**: SWE-bench's harness reverts agent edits to the hidden-test files before grading, so **scoring was not affected here**. This is luck of the substrate, not a property of the design.

**Recommendation**: enforce mechanically — reject a `synthesize` delegation whose `verification.checks` execute a test path that same delegation's diff modifies (`git diff --name-only` before/after, intersect against check command strings). Cheap, and it converts a prose norm into the checkable claim the project prefers everywhere else. Then re-audit all 5 patches with the EvilGenie-style method `DESIGN.md` already specifies, not just 6938.

## R8 — No per-delegation isolation; testbed contamination reached a submitted prediction

**Claim**: Failed and incidental work accumulates in the shared tree and ships in the final patch.

**Evidence**:
- `orchestrator/gru_environment.py::_delegate` has no rollback. A failed `synthesize` leaves its edits in place; the next delegation inherits them.
- `astropy-14182`'s submitted patch contains **`repro_rst_header_rows.py`** — a scratch reproduction script, staged and shipped as part of the prediction.
- The pilot's t5 findings show `git status` with untracked `findings.md`, `patch.txt`, and `astropy/modeling/findings.md` inside the package directory.
- `prompts/minion-execution.md` instructs *"make sure your working tree only contains changes actually relevant to this delegation"* — unenforced.

**Recommendation**: snapshot (`git stash create` / commit-to-scratch-ref) before each `synthesize`, restore on check failure. Filter the final `git diff` to tracked source paths, or at minimum warn when the submitted patch adds a file outside any delegation's declared `scope`.

## R9 — "Independent verification" is overstated in the LOG

**Claim**: The independence being claimed is narrower than the wording implies.

**Evidence**:
- `experiments/exp2/LOG.md` Setup: the orchestrator *"independently re-runs verification checks rather than trusting minion self-report."*
- What is actually independent: the **minion's self-report** is bypassed. Correct and worth having.
- What is not: the check is **authored by Gru**, executed against a tree the **minion** controlled, with pass defined as `exit 0` and no validity check on the command. `_run_checks([])` returns `(True, "(no checks specified)")`. No party in the loop is independent of Gru.
- `experiments/exp2/NOTES.md`'s verification-divergence section is fully honest about exactly this (*"the proxy isn't unreliable in a random way — both failures are the same shape"*). The **Setup section is what gets read**, and it isn't.

**Recommendation**: one clause in Setup — "independently of the minion's self-report; the checks themselves remain Gru-authored, see NOTES.md." No design change implied.

## R13 — Gru violates its own anti-prescription rule, and it appears to help

**Claim**: The ground rule against low-level delegation is broken in 4 of 5 instances, and the one instance that complied is the one that failed.

**Evidence**:
- [`prompts/gru-loop.md`](prompts/gru-loop.md) and `orchestrator/config/gru.yaml`: *"**Keep delegated subtasks high-level and outcome-oriented** ('implement X conforming to contract Y'), not a literal script ('open file A, change line B'). Over-specifying execution constrains a minion's own problem-solving even in cases where its own judgment would have gotten it right."* Backed by [`2605.29927`](literature-review/2605.29927-plan-granularity-web-agents.md) via [`01-planning.md`](design/architecture/01-planning.md) §5.2.
- Measured across all 16 `synthesize` delegations (table in `R1`): 4/5 instances name file + symbol + the exact edit. `astropy-6938` t3 cites **line numbers 1262–1264**.
- The single compliant delegation — `14365` t2, *"Make QDP command parsing case-insensitive, and add a regression test"* — is the instance that has now failed **identically across exp0, exp1, and exp2**.
- Prescriptive: **3/4 resolved**. Compliant: **0/1**.

**Why it matters**: n=5, so this is a hypothesis, not a result — but it is the most testable thing exp2 produced, and it points the opposite way from the design doc. It also reframes what the minion tier *is*: if the winning mode is "Gru specifies the edit, minion executes and independently verifies it," then the cheap tier is a **verified-execution substrate**, not a junior engineer. That is a coherent and defensible architecture — it is simply not the one `gru-loop.md` describes, and the gap should be closed deliberately rather than left as drift.

**Recommendation**: run it as the ablation, before Phase 2. Two arms on the same instances — Gru instructed to delegate outcome-only, vs. Gru free to prescribe. Cheaper than Phase 2, tests a claim the project already holds evidence on, and its answer determines what the minion prompt should say. Whichever wins, reconcile `gru-loop.md` and `01-planning.md` §5.2 to match.

## R16 — Agentic-loop history resend is the dominant cost, and `mode` is the lever

**Claim**: exp2's token inflation is mostly conversation *resend* inside agentic loops, not generation. Running every delegation as a 40-step bash loop is a structural cost, not a prompt-quality problem.

**Evidence** — per-call usage from `experiments/exp2/trajectories/t1.traj.json`:

| call | prompt | compl | cumulative | |
|---|---|---|---|---|
| 1 | 874 | 130 | 1,004 | |
| 2 | 1,460 | 134 | 2,598 | |
| 3 | 6,046 | 177 | 8,821 | ← `cat -n separable.py` enters the conversation |
| 4 | 9,058 | 324 | 18,203 | |
| 5 | 10,306 | 213 | 28,722 | |
| 6 | 10,832 | 125 | 39,679 | |
| 7 | 11,369 | **4,927** | 55,975 | ← minion re-types the file into `findings.md` |
| 8 | 16,343 | 135 | 72,453 | ← `findings.md` now in history too |
| 9 | 16,513 | 77 | 89,043 | |
| 10 | 16,641 | 86 | **105,770** | |

- **94% prompt, 6% completion.** Only 6,328 tokens were ever generated. Prompt grew **19×** from first call to last.
- The file body (~4,600 tokens) enters on call 3 and is resent on calls 4–10 — **eight payments, ~37k tokens**.
- The verbatim copy written into `findings.md` is resent on calls 8–10 — **~15k more**.
- **~52k of 99k prompt tokens are re-sends of two artifacts** — independently consistent with [`experiments/exp2/NOTES.md`](experiments/exp2/NOTES.md)'s estimate traced to one phrase in that delegation's `output_contract`.

**Why it matters**: mini-swe-agent resends full history every turn, so cost inside an agentic loop grows roughly quadratically in turn count. That is invisible in a per-delegation total, and it dwarfs the generation the delegation actually existed to produce.

**Adopted** — `mode` on every delegation:
- `oneshot`: a single model call, no shell; material supplied by the orchestrator via `inputs.from` / `inputs.read_paths`. Pays for its input once. t1's transcription work this way is ~7–10k against 105,770.
- `agentic`: full bash loop. Necessary wherever the work involves finding or changing something.

**Caveat, stated honestly**: `mode` is not the whole cost story — scope and description drive how far an agentic minion wanders. What it does is force the useful question: is this delegation doing *discovery* and *transformation* at the same time? t1 did both — grepping for which files mention separability genuinely needs a shell; transcribing and summarising one known file does not. The fix is splitting such delegations, not relabelling them. See `R12` for why the resulting token savings must not be read as cost savings without cache data.

## R17 — Gru had no legal way to take a reasoning turn, and it killed sessions

**Claim**: `RepeatedFormatError` crashes in the exp2-rerun batch were not a provider bug. Gru wanted a reasoning turn, the action space had no slot for one, so it emitted prose and was rejected until the session died.

**Evidence** — from the exp2-rerun handoff (`experiments/exp2-rerun/LOG.md`, `cce461c`): **2 of 3 attempts never reached `finish` at all.** Both times Gru (Qwen3.8-27B) produced a plain-text response with no tool call, three times consecutively, hitting mini-swe-agent's `max_consecutive_format_errors=3`:

- *Attempt 1*, after `t6` ran pytest and passed: **"PASS. All the evidence lines up…"** — instead of calling `finish`.
- *Attempt 3*, after `t4` returned context: **"I now have a complete, precise picture. Let me summarize the fix I've designed before implementing:"** — instead of delegating.

Both are requests for a reasoning turn. `prompts/gru-loop.md` told Gru it could *"reason and decide directly, no delegation"*; `parse_gru_actions` raised a `FormatError` on any turn without a tool call. The prompt offered an action the harness forbade, and the model went out of band to take it.

**Both failures fired immediately after a success signal** — a passing check, a "complete picture." The impulse to narrate arrives exactly when the model feels done, which is precisely the moment a reasoning turn is wanted.

**Distinct from `R5`, despite the shared symptom.** `R5` is *multiple* tool calls — Ollama genuinely ignoring `parallel_tool_calls: false`, i.e. provider non-compliance. This is *zero* tool calls — the model choosing content, faithfully transmitted. Same symptom class, opposite causes; treating them together points at Ollama configuration when the fix is action-space design.

**Adopted**: `think` as a first-class action; the tool-call-less error message now names it directly; `max_consecutive_format_errors` raised to 6 as a net behind it, not as the fix.

**Consequence worth tracking**: `cce461c`'s pre-finish test-recheck rule has never actually been exercised — both attempts that would have tested it crashed first. If `think` works, that rule gets its first real test.

**Unresolved, and possibly worsened**: the secondary `"no user query found in messages"` error Ollama returned mid-conversation. Gru's history is `system, user, [assistant, tool] × N` — after the opening turn there is never another `user` message. If that is what Ollama objects to in long histories, `think` adds turns and makes it more likely, not less.

---

# Tier 3 — research trail

## R10 — "Capacity, Not Format" was discarded without being addressed

**Claim**: A well-evidenced recommendation was reversed by a correction aimed at a different axis, and the docs now contradict the implementation.

**Evidence**:
- `design/architecture/01-planning.md` §2 and §5.1, and `literature-review/README.md`, all still carry: *"have Gru reason freely first, convert to `PLAN_FORMAT.md`'s schema as a separate step — don't ask for the structured plan directly while it's still reasoning"* — citing [`2606.09410`](literature-review/2606.09410-capacity-not-format.md): **10-30% degradation**, *"worst when task is already near the model's capability boundary,"* *"weak models degrade severely."*
- The 2026-08-21 correction (`prompts/README.md`) replaced the two-call design with a single-call ReAct loop emitting schema-constrained JSON **in the same generation as its reasoning** (`orchestrator/gru_model.py` passes `tools=[DELEGATE_TOOL, FINISH_TOOL]` on every turn).
- The correction's stated rationale is PlanBench-XL — *don't commit to a full plan upfront*. That is about **when planning happens**. "Capacity, Not Format" is about **whether reasoning and schema-emission share a generation**. Two orthogonal axes were collapsed into one correction; the evidence attached to the second was dropped silently, not argued against.

**Why it matters, concretely**: exp2's Gru is **Qwen3.8-27B at 4-bit** — the "weak model near its capability boundary" case the paper singles out. `experiments/exp2/LOG.md` Issues records Qwen emitting `final_verification` as a bare string instead of an object, hard enough to crash `parse_gru_actions` with zero output saved. That is format-compliance strain visible in the data. A 10-30% hit to Gru's reasoning is a **live, untested confound for exp2's regression** — and the cheapest one on this list to test.

**Recommendation**: it is possible to keep the continuous loop *and* the reason-then-structure split — free-form reasoning turn, then a schema-emission turn, still one delegation at a time, still no upfront plan. Run it as one arm against the current design. Either way, reconcile `01-planning.md` §5.1 and the README table with what the code does.

## R11 — Phase 1's success criterion was not met as written; one LOG claim looks unsupported

**Claim**: The mechanism unique to this architecture may never have fired.

**Evidence**:
- `design/infra/04-machine-config.md` §9 defines Phase 1 success as the full ladder running: *"plan → subtask dispatch → mechanical check → debate → Gru escalation → amend-plan-and-retry."* Debate is deferred (documented and reasonable).
- **All 5 runs show `final_verification_passed: true`** in `cost_summary.json`. The finish-rejection / reconsider-the-decomposition path is the mechanism that distinguishes this architecture from a plain delegating agent.
- `experiments/exp2/LOG.md` Conclusion claims *"delegation, independent verification, inline retry, and the finish-rejection-continues-session path **all fired for real during this batch**."*
- Pilot (`12907`): trajectory shows a **single `finish`, which passed** — claim contradicted.
- `14182`: 4 Gru calls, 4 delegations, 1 finish. Turn accounting **forecloses** a rejected finish — no spare turns.
- `14365` / `14995` / `6938`: spare turns exist (8/6, 8/6, 12/7), but `FormatError` retries consume `n_calls` identically, and the LOG documents those as frequent. **Trajectories were destroyed** — unverifiable.

**Net**: contradicted for 2 instances, unverifiable for 3. Inline retry-after-failed-check **did** fire and is well-evidenced (t3→t4→t6) — that part of the claim is solid.

**Recommendation**: correct the Conclusion to claim only what survives. If the finish-rejection path matters, construct a case that forces it (e.g. a `final_verification` including a check the current patch cannot satisfy) rather than hoping a batch surfaces one.

## R12 — Tokens are the wrong cost unit for a self-hosted run (deferred, not blocking)

**Scope**: cost is explicitly *not* what Phase 1 is measuring, so this is recorded for Phase 2, not raised against exp2.

**Claim**: The 3.5× token headline cannot be converted to cost, and the direction of the error is unknown.

**Evidence**:
- exp1 reported both tokens and money (~$0.17 rental, **$0.097/M blended**). exp2's summary line omits the $ figure [`EXPERIMENT_LOG_FORMAT.md`](EXPERIMENT_LOG_FORMAT.md) asks for (`<cost total, $ or GPU-hr>`).
- [`experiments/exp1/NOTES.md`](experiments/exp1/NOTES.md) established that **~96% prefix-cache reuse** makes raw token counts a poor proxy for self-hosted cost.
- exp2's architecture is structurally far worse for cache reuse: **30 separate conversation prefixes** (1 Gru session + 29 fresh minion sub-sessions) versus 1 in exp1. Each minion starts a new prompt sharing no prefix with the last.
- [`orchestrator/run_exp2_single.py`](orchestrator/run_exp2_single.py) documents the deliberate decision to skip live cache capture — defensible for Phase 1's question.

**Cache caveat on `R16`'s `mode` savings** (added 2026-08-22): [`experiments/exp1/NOTES.md`](experiments/exp1/NOTES.md) argued the resend-everything pattern is *"a much smaller cost problem for a self-hosted minion than an API-billed one"* because ~96% prefix-cache reuse puts real GPU cost far below the raw token count. That reasoning holds **within one conversation** — each turn's prompt strictly extends the previous one, so the cache absorbs the resend. Two things change it under this architecture, in opposite directions:

- **Against**: exp2 runs 29 separate minion sessions plus Gru — roughly **30 independent prefixes**. Cross-session reuse is zero, so the resend tax is paid afresh per session instead of being amortised across one long conversation.
- **For**: `oneshot` has no history to resend, cached or not — it sidesteps the question entirely rather than winning it.

Net: `R16`'s savings are real against a **metered API** and *partially already absorbed* on **self-hosted inference**. Which, and by how much, is unmeasured — exp2 captured no cache stats at all. **Do not read the next run's token delta as a cost result** without per-role cache-hit numbers; that is precisely the trap this finding records.

**Recommendation**: for exp2, lead the cost line with **wall-clock (~3.9×)**, the actual billing unit for a rented GPU, and add the $ rental figure — one line, no re-run. For Phase 2, capture cache stats live: §6's ~76% breakeven math is unresolvable without it, and the 30-prefix structure makes per-role cache behavior a first-class variable.

## R14 — LLM-Modulo is cited for a claim it does not make

**Claim**: Kambhampati is invoked to support incremental-over-upfront planning; it argues for external verification, not for scheduling.

**Evidence**:
- [`2402.01817`](literature-review/2402.01817-llms-cant-plan-llm-modulo.md)'s prescription is a generate-and-test loop with an **external, ideally sound, verifier** critiquing candidate plans. It is agnostic on whether plans are formed upfront or incrementally.
- [`01-planning.md`](design/architecture/01-planning.md) §4 gets this right: *"a direct, independent argument for this project's escalate-on-failure / external-verification architecture."*
- The evidence that actually supports interleaving is [PlanBench-XL](literature-review/2606.22388-planbench-xl.md) (plans collapse once the environment diverges from assumptions) plus [ReAct](literature-review/2210.03629-react-reasoning-and-acting.md) — both already cited correctly in [`prompts/README.md`](prompts/README.md)'s revision history.

**Why it matters**: minor on its own, but the interleaved-loop decision is load-bearing and should rest on the citations that support it. Conflating the two also obscures that LLM-Modulo's real demand — a *sound external* verifier — is the same demand `R1` finds unmet on the exploration leg.

**Recommendation**: no design change. Keep LLM-Modulo where it is (verification architecture); cite PlanBench-XL + ReAct for interleaving.

---

# Source verification

Three prior-art sources checked against primary sources on 2026-08-22 — the original research pass was never verified. **All three are real and their headline numbers are accurate.** All three summaries are lossy in ways that change what the source implies for this project.

## SuperScout — [arXiv 2608.04804](https://arxiv.org/abs/2608.04804)

Actual title: *"Scrouting: Cost-Aware Routing of Coding Agents by Scouting the Repository First"* — SuperScout is the system, not the paper. Bhola, Krishnan, NS (SuperAGI Research), 5 Aug 2026.

| Repo claim | Verdict |
|---|---|
| small scout explores, frontier fixer patches | ✅ SuperScout-7B scouts only; the patch is written by a routed fixer |
| matched Opus at ~1/5 cost | ✅ 159/266 @ **$0.230/solve** vs. Opus 4.6's 158/266 @ **$1.274/solve** |
| the verified handoff drove the gain, not routing | ✅ no-router ablation (Kimi K2.5 + handoff) ties at $0.227; router worth $0.003/solve |

**Missing from the summary**:
- The fixer is a **pool of four** (Opus 4.6, GPT-5.2, Kimi K2.5, Gemini 3 Flash) behind a résumé-based router — not a single frontier model.
- **The verify-then-strip numbers**: 50 of 249 reproduction claims genuine (20%), 174 stripped as demonstrably false, 25 errored. This is the paper's single most relevant number for this project (`R1`).
- The paper's own caveat: *"whether blanket assignment to one cheap fixer reaches parity is a property of this pool and benchmark, not a general rule."*

## AI21 — [Better and cheaper together](https://www.ai21.com/blog/better-and-cheaper-together-open-models-explore-frontier-models-patch/)

| Repo claim | Verdict |
|---|---|
| open models explore, frontier patches | ✅ *"the principal model sit down and write the patch, once, from a prepared brief"* |
| 80.8% SWE-bench Pro @ $5.99/task | ✅ against solo Opus 4.8 at **$18.28/task** |

**Missing**: it is **three tiers, not two**. Junior (MiniMax-M3) fans out across the repo; **Senior (GPT-5.2) digs into the code they touched and writes up exactly what the real fix depends on**; Principal (Opus 4.8 / Fable 5) writes the patch. They also measure handoff quality directly — **~90% coverage of gold-patch removed lines, ~71% of added lines** before frontier generation. That senior tier performs exactly the "judgment-laden curation" `DESIGN.md` identifies as *"often as hard as code-writing."*

## Stencil — [stencil.so/blog/prewalk](https://stencil.so/blog/prewalk)

**Attribution error**: filed as "Augment Code / Stencil." The source is **Stencil**; Augment Code is a different company with its own separate routing product (Prism). Rename the file and title.

| Repo claim | Verdict |
|---|---|
| Opus-plans + Flash-executes: $3.18 @ 84.6% | ✅ |
| Opus solo: $2.78 @ 84.6% | ✅ |
| `/plan` is upfront-batch, not interleaved | ✅ *"creates a comprehensive plan document upfront before execution begins — no interleaving"* |

**Missing — four of six configurations, including the article's actual conclusion**:

| Config | Cost | Pass |
|---|---|---|
| Opus + `/plan` (plans upfront, Flash executes) | $3.18 | 84.6% |
| Opus solo | $2.78 | 84.6% |
| **Opus + `/prewalk` (Opus explores + lands first edit, then Flash)** | **$1.46** | **78%** |
| Flash oneshot | $1.16 | 60% |
| GPT-5.6 Sol solo | $1.71 | 88% |
| **Sol + `/prewalk`** | **$1.04** | **85%** |

The article's headline is `/prewalk`: *"97% of Sol's pass rate at 61% of the cost, and it's the fastest of the three."* A source filed as a pure counter-example is in fact a **third demonstration** that the frontier model must be present where the information is. It tests **no** cheap-explores configuration at all.

## Still unverified

Post-cutoff and never checked against primary sources: ORACLE-SWE `2604.07789` (load-bearing for `R2`), Capacity-Not-Format `2606.09410` (`R10`), PlanBench-XL `2606.22388` (load-bearing for the entire continuous-loop correction), Token Economics `2605.09104` (`R4`, `R12`), Code Isn't Memory `2606.22417` (the structural-graph proposal `R15` promotes), SearchSwarm `2606.09730` (already self-flagged in-repo), EvilGenie `2511.21654`, Verification Horizon `2606.26300`.

**Base rate from this pass: citation real, reading incomplete.** Three for three.

---

# Changes implemented

Applied to `orchestrator/` and `prompts/` on 2026-08-22, after the review discussion. **None of this is validated — the harness has not been run since.** Recorded so the findings above are not read as all-open.

| Finding | Change | Status |
|---|---|---|
| `R5` | One action per turn enforced in `parse_gru_actions`, rather than trusting `parallel_tool_calls` (which Ollama silently dropped) | implemented, unvalidated |
| `R6` | `run_check` action added — Gru verifies without spawning a no-op minion session | implemented, unvalidated |
| `R15` | Coverage receipts required on `findings` delegations: exact commands, full output, dismissed candidates with reasons, and what was searched for and not found | implemented, unvalidated |
| `R16` | `mode` (`oneshot` \| `agentic`) added; `oneshot` is a single call with orchestrator-supplied material | implemented, unvalidated |
| — | **`type` taxonomy removed.** `context_gather`/`locate`/`synthesize` and `search_strategy` encoded our guess about which work is delegable; that guess is the hypothesis under test. `returns` + `mode` replace it | implemented, unvalidated |
| — | **Delegation criterion changed** from verifiability to token displacement, with a tool-first escape hatch and a decide-first guard. Verification is now a per-delegation requirement, not the gate | implemented, unvalidated |
| — | `think` action added — Gru previously had no non-delegating action, so the prompt's "reason and decide directly" was an option the harness rejected, and delegation *choice* was unmeasurable | implemented, unvalidated |
| `R17` | `max_consecutive_format_errors` raised 3 → 6 in `gru.yaml`, and the tool-call-less error message now names `think` explicitly | implemented, unvalidated |
| — | `cce461c`'s pre-finish test-recheck rule preserved through the prompt rewrite, with two dangling references updated (`locate`, "the overconfidence ground rule above"). Still unvalidated — it has never been reached in a completed session | preserved, unvalidated |
| — | Every delegation's token cost returned in its observation — Gru was asked to prefer low-token work while being shown no token counts | implemented, unvalidated |
| `R13` | Prompt left deliberately neutral on prescriptiveness rather than instructing either way | ablation still to run |
| `R3` | exp2's `LOG.md` Results now marks the verdict provenance (`Resolved†`) where the number is, with the methodology and the recovery command in `NOTES.md#verdict-provenance` | **editorial half done**; the verdict is still transcribed for 4 of 5 — `run_evaluation` not re-run |
| `R4` | exp2's Findings bullet now records the exp1 comparison without interpreting it — cites Phase 1's §9 scoping rule and the n=5 statistics; "net-negative", "a real result" and the gating language are gone from the Conclusion | done |
| `R11` | Same Conclusion edit: the claim that the finish-rejection path "fired for real during this batch" is replaced with what the artifacts support — it never fired, `final_verification` passed on the first `finish` in all 5 runs | done |
| `R1` | **Gru read-only repo access — declined.** Would make the architecture Stencil's `/prewalk`, a different system than the one under test. `run_check` runs commands for verification only, and that boundary now lives in the prompt rather than the schema | declined by design |
| `R15` | **Gru verification pass over returned content — declined.** Would not have caught either exp2 failure, is the weakest verification available per the project's own LLM-Modulo citation, and reinstates the per-completion Gru cost `DESIGN.md` rejected | declined by design |

Still open and unaddressed: `R2`, `R7`, `R8`, `R9`, `R10`, `R12`, `R14`, and the literature-review corrections in [Source verification](#source-verification). The one remaining blocker is the non-editorial half of `R3` — re-running `run_evaluation` on the intact `predictions_all5.json`, which needs a VM rather than an edit.

---

# What's genuinely strong

Stated specifically, because it is why the above is worth fixing rather than restarting.

- **The token accounting is exact.** Every figure in exp2's `LOG.md` and `NOTES.md` was recomputed from raw `cost_summary.json` files: all five per-instance totals, all five vs-exp1 multipliers (3.4×, 1.3×, 13.5×, 4.9×, 5.1×), the 3.5× aggregate, the 478,886 / 3,701,786 split, the 11.5% / 88.5% shares. **All reconcile.** That is rarer than it should be.
- **The Augment counter-example is kept and made load-bearing.** Most projects quietly drop the inconvenient result. The irony of `R1` is that it was taken seriously and applied to the wrong axis — the instinct was right.
- **Gaps are flagged, not filled with speculation**: SearchSwarm's 70% marked unverified, "Notation Matters" marked a placeholder, vLLM-vs-llama.cpp throughput, container-vs-VM GPU access, Qwen3.8-27B's launch-week benchmark provenance. `04-machine-config.md` §8 pressure-tests the user's *own* hypothesis to "likely wrong as a blanket claim." Consistently applied.
- **`astropy-14365` is the best science in the project.** The identical `re.IGNORECASE` fix across Haiku, solo Qwen, and Gru+minion — with exp2's Gru *explicitly delegating a context-gather aimed at case-sensitivity sites* and still missing the downstream dispatch. Three independent architectures, one blind spot. Correctly framed, and stronger evidence for `R2` than the literature is.
- **The Issues sections are excellent operational engineering** — vast.ai NAT port mapping, the scp/SFTP hang, tmux + `nohup` vs. local pipe redirect, the recurring bad-host IP. And the destroyed-trajectories mistake is reported plainly with its consequence (*"that data is permanently lost"*), not minimized.
- **Holding the 5 instances fixed across exp0/1/2** was the right call for comparability, and the two-tier `LOG.md` / `NOTES.md` split genuinely works — terse results stay terse, methodology gets the room it needs.
- **The verifiability-trap principle and the delegation-return-type split** are sharp, non-obvious design thinking, and `_delegate` implements the split faithfully (`synthesize` returns only pass/fail plus check output; content is withheld from Gru).

---

# Priority

| # | Action | Cost | Blocks |
|---|---|---|---|
| 1 | Re-run `run_evaluation` on exp2's intact `predictions_all5.json`; replace the transcribed summary (`R3`) | ~1 VM-hour | everything downstream |
| ~~2~~ | ~~Strike exp2's resolve-rate interpretation (`R4`)~~ | done | — |
| 3 | Correct the three literature-review entries; fix the Stencil attribution ([Source verification](#source-verification)) | editorial | all prior-art reasoning |
| ~~4~~ | ~~Build coverage receipts + negative-space reporting (`R15`)~~ | done | — |
| ~~5~~ | ~~Fix `parallel_tool_calls` / enforce single-action (`R5`)~~ | done | — |
| 6 | Correct the t4/t6 diagnosis in `NOTES.md` (`run_check` added; the note itself is still wrong) | editorial | exp2's own stated gate on further runs |
| ~~7~~ | ~~Give Gru read-only repo access (`R1`)~~ — declined by design | — | — |
| 8 | Run the prescription ablation — outcome-only vs. free-to-prescribe (`R13`) | one run | what the minion prompt should say |
| 9 | Enforce the test-authorship invariant in code (`R7`) | small | the safety story |
| 10 | Build the structural-graph index as the next real experiment (`R15`) | real build | the irreducible residual (`14365` × 3) |
| 11 | Test the reason-then-structure arm (`R10`) | one run | untested explanation for exp2's regression |
| 12 | Verify the remaining eight citations | ~1 session | `R2` and `R10` rest on unverified readings |
| 13 | Re-run the five instances on the rewritten harness — nothing in [Changes implemented](#changes-implemented) is validated | one batch | every claim about the new design |

---

# Provenance — what was verified how

Matching this project's own convention of labeling measured vs. estimated vs. unverifiable.

**Verified directly against raw artifacts**:
- All exp2 token/call/wall-clock figures — recomputed from the five `cost_summary.json` files and cross-checked against `LOG.md` and `NOTES.md`. Exact match.
- Delegation type distribution (10 `context_gather`, 16 `synthesize`, 3 `locate`) — summed from `cost_summary.json`.
- Test-file modification in all 5 patches — regex over `diff --git` headers in each `prediction.json`.
- t3/t4 FAIL and t6 PASS, and the two-actions-per-turn batching — read from `experiments/exp2/trajectories/gru.traj.json` message by message.
- exp1 vs. exp2 report schema difference — field-by-field comparison of the two `summary_report_5instances.json` files.
- Delegation **content** prescriptiveness — read all 16 `synthesize` delegation descriptions from the five `cost_summary.json` files and classified each by whether it names file + symbol + the exact edit (`R1`, `R13`).
- Statistics (Fisher, McNemar, Wilson) — computed from the resolve vectors.

**Inferred, stated as such**:
- The cause of the dropped `parallel_tool_calls` (Ollama non-support + `drop_params: true`) is inference from config and observed behavior; the batching itself is directly observed.
- The cache-reuse degradation in `R12` follows from the 30-prefix session structure; **not measured** — exp2 captured no cache stats.

**Unverifiable — trajectories destroyed**:
- Whether a `finish` was ever rejected on `14365` / `14995` / `6938` (`R11`).
- How `astropy-6938`'s replacement checksum values were derived — `NOTES.md` already names this honestly.

**Verified against primary sources (web, 2026-08-22)**:
- SuperScout `2608.04804` — arXiv abstract + full HTML text: topology, cost figures, no-router ablation, verify-then-strip counts.
- AI21 blog — tier structure, patch authorship, cost baselines, context-coverage metrics.
- Stencil `prewalk` — all six configurations, the upfront-vs-interleaved question, the article's recommended config.

**Verified against surviving trajectories**:
- Minion command-level behavior in `t1`–`t6` for `astropy-12907`, including t1's self-issued `diff` returning `IDENTICAL` (`R15`).

**Not examined**: `tools/trajectory_viewer.html`, `docs/architecture.excalidraw`, `design/architecture/03-graph-orchestration_onhold.md` (on hold), and the debate-verification branch (unprototyped by design).
