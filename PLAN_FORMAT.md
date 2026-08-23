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

**Revised 2026-08-22**: the `type` taxonomy (`context_gather` / `locate` / `synthesize`) is gone, along with `search_strategy`. Those fields encoded our own guess about which work is delegable, and that guess is now the thing being tested — so Gru is no longer asked to classify work into our categories. Two dimensions replace it, both set by Gru, and each governs exactly one mechanical consequence:

```json
{
  "id": "t3",
  "returns": "verdict",
  "mode": "agentic",
  "description": "Implement SmsVerifier conforming to the Verifier interface located in t1",
  "inputs": {
    "from": ["t1", "t2"],
    "read_paths": [],
    "scope": "src/auth/verification/"
  },
  "verification": {
    "checks": [
      "pytest tests/auth/test_sms_verifier.py",
      "pytest tests/auth/test_email_verifier.py"
    ]
  },
  "output_contract": "diff + list of touched files"
}
```

- **`id`** — assigned by the orchestrator when the delegation is issued; referenced by later delegations' `inputs.from`.
- **`returns`** — the only thing that changes what Gru sees back.
  - `findings`: the minion's actual output is returned. Used where the content *is* the deliverable and no check could settle it.
  - `verdict`: only pass/fail, computed by the orchestrator independently re-running `verification.checks` against the state the minion left behind — never the minion's own claim. Requires at least one check; there is nothing to return without one.
- **`mode`** — the only thing that changes what a delegation *costs*.
  - `oneshot`: a single model call, text in and text out, no shell. Its material must be supplied via `inputs.from` and/or `inputs.read_paths`, since it has no way to go find anything.
  - `agentic`: a full bash tool loop against the shared testbed. Roughly an order of magnitude more expensive — exp2's `t1` spent 105,770 tokens reading one file this way.
- **`inputs`** — `from` names prior delegation ids (resolved by the orchestrator to their real output, raw passthrough, no summarisation step); `read_paths` names files the orchestrator reads and hands over verbatim; `scope` bounds where the minion may operate.
- **`verification.checks`** — a list of shell commands, exit 0 means pass. Mandatory when `returns: verdict`, optional otherwise (a coverage bound on findings, where one genuinely exists). **A delegation that touches tests or verification logic can never be the thing that verifies itself** — whatever confirms it worked has to be a separate, later check it does not control.
- **`output_contract`** — what this delegation hands back and in what shape. For `findings` delegations the minion prompt additionally requires a coverage receipt: the exact commands run and their full output, every candidate found including dismissed ones with reasons, and what was searched for and not found.

## Gru's other actions

Not every turn is a delegation. Added 2026-08-22:

- **`think {note}`** — a turn spent on a decision rather than on work. Nothing executes, no minion is charged. This exists because the prompt has always told Gru it could "reason and decide directly" while the harness rejected any turn without a tool call, leaving delegation as the only available action.
- **`run_check {checks}`** — run verification commands directly against the testbed and see the result. For confirming a claim or re-running a corrected check, not for exploring the repository. Replaces the pattern in exp2 where Gru spawned entire no-op minion sessions (`t4`, `t6`) purely to re-run a check whose command it had written incorrectly.

## Return shape — what Gru actually sees back

| `returns` | What Gru receives |
|---|---|
| `findings` | The minion's actual output, per `output_contract`, plus the delegation's token cost. |
| `verdict` | Pass or fail from the orchestrator's own run of `verification.checks`, plus the check output and the token cost — not the content. Gru does not re-read the work; the check already established what it needed to know (the "verifiability trap"). |

Every delegation's observation carries its token cost, so that "prefer token-heavy, judgement-light work" is something Gru can act on rather than comply with on faith.

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
