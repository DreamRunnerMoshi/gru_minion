# Gru Plan Format

Status: design draft, no implementation yet. Companion to [DESIGN.md](./DESIGN.md) — read that first for the Gru/minion architecture, the escalate-on-failure principle, and the debate-verification branch this format needs to express. Also companion to [prompts/gru-loop.md](./prompts/gru-loop.md) — this file is the schema, that file is the prompt that produces it.

**Revised 2026-08-21**: this format no longer describes a plan Gru writes upfront, in one shot, before any minion runs. That framing was corrected — see [prompts/README.md](./prompts/README.md#revision-history) for why. Gru now runs one continuous session per task, deciding one delegation at a time; what used to be called "the plan" is now **the trace of delegations Gru actually made**, built incrementally, plus a `goal` restatement and a `final_verification` gate. The per-delegation schema below (what used to be "the subtask shape") is now the schema of a single `delegate_to_minion` tool call, issued live, not a pre-committed array element.

## What this format has to do

Every `delegate_to_minion` call, plus the eventual `finish` call, is what a downstream reviewer (or the orchestrator, or a future Gru session picking this up) has to reconstruct "what happened and why" from. So the format has to carry, per delegation, not just "what to do" but "how to know it was done right" — and the sequence of delegations, taken together, has to carry the dependency structure even though no upfront array declares it. Two things pinned down by earlier design decisions constrain the shape:

- **Sequential, not parallel fan-out** (DESIGN.md) — delegations form a chain as Gru works through the task, not an independent-agent swarm. A later delegation can depend on an earlier one's output, named explicitly via `inputs.from`.
- **Escalate-on-failure, but inline** (DESIGN.md, sharpened 2026-08-21) — a delegation's own check failing is handled by Gru immediately, in the same session, not via a separate escalation call. The one thing that still functions like an escalation is the **whole-task** `final_verification` failing despite every individual check passing — that's the signal to reconsider the overall approach, not patch one more subtask.

## `goal` — stated once, at the start of the session

Gru's own restatement of the task, not copied verbatim from the ticket — this is Gru's own understanding, which is itself worth logging (if Gru's restatement is wrong, that's diagnosable independent of anything downstream).

```json
{
  "goal": "Add SMS-based verification alongside existing email verification",
  "source": "JIRA-1234 + linked design doc"
}
```

## `delegate_to_minion` — issued live, one per turn, as many times as needed

```json
{
  "id": "t3",
  "type": "synthesize",
  "description": "Implement SmsVerifier conforming to the Verifier interface located in t1",
  "inputs": {
    "from": ["t1", "t2"],
    "scope": "src/auth/verification/"
  },
  "search_strategy": null,
  "verification": {
    "checks": [
      {"type": "test", "command": "pytest tests/auth/test_sms_verifier.py", "expect": "pass"},
      {"type": "test", "command": "pytest tests/auth/test_email_verifier.py", "expect": "pass"}
    ]
  },
  "output_contract": "diff + list of touched files"
}
```

Field notes:

- **`id`** — assigned when the delegation is issued (not pre-planned); referenced by later delegations' `inputs.from`.
- **`type`** — constrains what `verification` and the return value look like. Only three values now (`design_decision` removed — it was never actually delegated to a minion; it's just Gru reasoning directly, no tool call):
  - `context_gather` — read/summarize/extract (docs, code, existing patterns). Returns its actual findings to Gru — see "Return shape" below. Verification is usually the hard case (completeness); often no check exists at all, and that's an accepted residual, not a defect to paper over.
  - `locate` — find specific artifacts (test files, call sites, config references). Narrower than `context_gather`; often mechanically checkable (count/existence bounds, graph-traversal coverage per [DESIGN.md](./DESIGN.md)'s structural-index proposal).
  - `synthesize` — write/modify code. **Verification is mandatory and mechanical** — a check that demonstrates the specific behavior now works, same pattern as SWE-bench's `FAIL_TO_PASS`/`PASS_TO_PASS` but self-authored (existing tests, or new ones written for this delegation) rather than the hidden gold tests, which Gru has no access to — same distinction as `final_verification` below, just at delegation scope instead of whole-session scope. Returns pass/fail only, not the content — see "Return shape" below.
- **`inputs`** — `from` is a list of prior delegation ids (symbolic reference — Gru issues a delegation before knowing what an earlier one will concretely find, so it can't reference actual file paths yet; the orchestrator resolves `from` to the referenced delegation's real output at execution time, via raw passthrough — no extraction/summarization step). `scope` bounds where the minion is allowed to operate, both as a safety rail and to keep mechanical checks well-defined.
- **`search_strategy`** — required for `context_gather`/`locate`, omitted for `synthesize`. This is where "Gru decides how thoroughly to search, doesn't delegate wholesale" lives concretely — e.g. `{"method": "graph_traversal", "from_symbol": "is_verified", "max_hops": 2}` or `{"method": "keyword", "patterns": ["verification_type", "is_verified"]}`. A missing search strategy on a `context_gather`/`locate` delegation is a defect — it usually means Gru delegated "gather context on X" wholesale, under-specifying completeness.
- **`verification`** — for `synthesize`, mandatory, always mechanical, never absent:
  ```json
  {"checks": [
    {"type": "test", "command": "...", "expect": "pass"},
    {"type": "graph_traversal", "symbol": "verify_email", "max_hops": 2, "expect_min_nodes": 5},
    {"type": "file_exists", "path": "..."}
  ]}
  ```
  For `context_gather`/`locate`, optional — a coverage/bound check where one genuinely exists (e.g. "at least N call sites found" as a floor), absent otherwise. **A delegation that touches tests or verification logic can never be the thing that verifies itself** — whatever confirms it worked has to be a separate, later check that delegation doesn't control.
- **`output_contract`** — what this delegation hands back. For `context_gather`/`locate`, this is the shape of the findings Gru actually receives (see below). For `synthesize`, this is what a *later* delegation's `inputs.from` would reference if it needs to point at this one's result (e.g. "diff + list of touched files") — Gru itself only sees pass/fail for `synthesize`, not this content directly.

There is no `escalation_policy` field anymore — a failed check is something Gru sees and reacts to in its own next reasoning turn, not a declared policy attached to the delegation upfront.

## Return shape — what Gru actually sees back

This is the part that most changed from the original design, and it's not uniform across types:

| `type` | What Gru receives |
|---|---|
| `context_gather`, `locate` | The actual findings, per `output_contract` — a summary, file list, extracted content. No independent check most of the time; the content *is* the deliverable, and Gru's next step depends on reading it. |
| `synthesize` | Pass or fail from the mechanical check only, plus a reference to the result (not the diff itself). Gru does not re-read the content — the check already established what it needed to know. Re-verifying it would just be redoing the minion's work (the "verifiability trap"). |

## `finish` — ends the session, gates the whole result

```json
{
  "summary": "Added SmsVerifier alongside EmailVerifier, both implementing the shared Verifier interface",
  "final_verification": {
    "checks": [
      {"type": "test", "command": "pytest tests/ -k verification", "expect": "pass"}
    ]
  }
}
```

`final_verification` is a whole-session gate, distinct from any individual delegation's local check. This exists because a sequence of locally-passing delegations doesn't guarantee the composed result works — integration failure is a real risk even without concurrency. **If this fails**, that's not routine — it means the overall decomposition was wrong, not one step; Gru reconsiders its approach broadly rather than patching the last delegation, still within the same session (it keeps everything it learned, it doesn't discard history).

**This is not SWE-bench's `FAIL_TO_PASS`/`PASS_TO_PASS`** — Gru has no access to those; they run in a separate process, after the session ends, exactly as in exp0/exp1. `final_verification.checks` has to be a self-authored proxy: a reproduction case grounded in the task description (ideally set up as one of the *first* delegations, then re-run here) plus the repo's existing test suite as a regression guard — see [prompts/gru-loop.md](./prompts/gru-loop.md#authoring-final_verification-without-access-to-the-real-ground-truth) for the full reasoning. This proxy is a real signal but a necessarily incomplete one; the actual resolve/not-resolve verdict for logging results still only comes from the post-hoc SWE-bench evaluation harness, same as every prior experiment in this project.

## Worked example (sequential slice, as it actually unfolds — not a pre-written array)

Using the running email/SMS-verification feature example from DESIGN.md:

1. Gru delegates `t1` — `context_gather`: "find the current `Verifier` interface/implementation and every call site assuming email-only verification." `search_strategy`: graph traversal from `is_verified`/`verify_email`, 2 hops. Gru receives the actual findings back (file list + summaries) and reads them.
2. Based on what `t1` found, Gru delegates `t2` — `locate`: "find all existing tests covering the `Verifier` interface." Gru receives the findings (test file list).
3. Gru reasons directly (no delegation) about the abstraction question: should `SmsVerifier` share `Verifier`'s state machine or get its own? This is a judgment call — not something a check can adjudicate, so it's Gru's own decision, made using what `t1`/`t2` surfaced, not delegated to a minion.
4. Gru delegates `t3` — `synthesize`: implement `SmsVerifier` per the decision just made (shown above). Gru receives pass/fail only — the tests from `t2` plus new ones passed.
5. Gru calls `finish` with a whole-plan `final_verification` covering both verifiers.

Note step 3 happening *between* t2 and t3, informed by what t1/t2 actually found — this is exactly the thing a pre-committed upfront array couldn't do (t3's real spec depends on a decision that couldn't be made until t1/t2's real findings were in hand).

## Open questions specific to this format

**Resolved, scoped to the next experiment (2026-08-21)** — see [prompts/README.md](./prompts/README.md#format-decisions-this-experiment-needed-resolving-plan_formatmds-open-questions-scoped-to-whats-needed-now) for the reasoning:

1. ~~Single-shot vs. staged planning~~ — superseded. There is no upfront plan; every delegation is issued live, one at a time.
2. ~~Symbolic reference resolution~~ — orchestrator does raw content passthrough of a referenced delegation's output.
3. ~~Can Gru expand the plan mid-execution?~~ — yes, by construction; every delegation is decided in the moment.

**Still open**:

4. **Debate verdict re-entry.** When a `debate`-method delegation's judge accepts/rejects, does that verdict become part of the delegation's `output_contract` for downstream consumption, or is it purely a gate? Leaning toward "gate only" (matches DESIGN.md's framing of debate as an accept/reject rung), but debate is entirely deferred for the next experiment (`verification.checks` is mechanical-only, no `debate` method exists in this schema right now) — not worth resolving further until debate is actually prototyped.
