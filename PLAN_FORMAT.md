# Gru Plan Format

Status: design draft, no implementation yet. Companion to [DESIGN.md](./DESIGN.md) — read that first for the Gru/minion architecture, the escalate-on-failure ladder, and the debate-verification branch this format needs to express.

## What this format has to do

The plan is the only artifact Gru produces per task. Everything downstream — minion execution, mechanical checks, debate rounds, Gru re-escalation — is the orchestrator mechanically walking this structure. So the format has to carry, per subtask, not just "what to do" but "how to know it was done right" and "what happens if it wasn't." Three things pinned down by earlier design decisions constrain the shape:

- **Sequential, not parallel fan-out** (DESIGN.md) — subtasks form a chain, not an independent-agent swarm. But even a strict chain needs explicit handoff: subtask N's output becoming subtask N+1's input has to be named, not implicit.
- **Escalate-on-failure via the mechanical → debate → Gru ladder** (DESIGN.md) — verification isn't one field, it's a choice of *method*, and the choice differs per subtask (a `synthesize` step has tests; a `design_decision` step usually doesn't).
- **Push as much as possible into mechanical form** (open question #2 in DESIGN.md, partially addressed by the structural-graph idea) — the format should make it easy for Gru to specify a mechanical check (test command, graph-traversal bound, file assertion) and should only fall back to debate/escalation when Gru explicitly can't.

## Top-level plan

```json
{
  "goal": "Add SMS-based verification alongside existing email verification",
  "source": "JIRA-1234 + linked design doc",
  "subtasks": [ /* ordered list, see below */ ],
  "final_verification": {
    "method": "mechanical",
    "checks": [
      {"type": "test", "command": "pytest tests/ -k verification", "expect": "pass"}
    ]
  }
}
```

- `goal` — restated task, not copied verbatim from the ticket; this is Gru's own understanding, which is itself worth logging (if Gru's restatement is wrong, that's diagnosable independent of anything downstream).
- `final_verification` — a whole-plan gate, distinct from any individual subtask's local check. This exists because a sequential chain of locally-passing subtasks doesn't guarantee the composed result works (same reasoning that killed parallel fan-out in DESIGN.md — integration failure is a real risk even without concurrency). Mirrors SWE-bench's FAIL_TO_PASS/PASS_TO_PASS being defined at the whole-patch level.

## Subtask

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
    "method": "mechanical",
    "checks": [
      {"type": "test", "command": "pytest tests/auth/test_sms_verifier.py", "expect": "pass"},
      {"type": "test", "command": "pytest tests/auth/test_email_verifier.py", "expect": "pass"}
    ]
  },
  "escalation_policy": {
    "on_fail": "retry_once_with_feedback",
    "then": "gru_escalation"
  },
  "output_contract": "diff + list of touched files"
}
```

Field notes:

- **`id`** — referenced by later subtasks' `inputs.from`. Also the unit the orchestrator retries/escalates independently.
- **`type`** — not just documentation; it constrains which `verification.method` values are sane. Starter taxonomy, open to revision:
  - `context_gather` — read/summarize/extract (docs, PDFs, links, existing code). Verification is usually the hard case (completeness), see below.
  - `locate` — find specific artifacts (test files, call sites, config references). Narrower than `context_gather`; often mechanically checkable (count/existence bounds, graph-traversal coverage).
  - `synthesize` — write/modify code. Verification is the SWE-bench-style FAIL_TO_PASS pattern whenever tests exist or can be written.
  - `design_decision` — abstraction/architecture judgment calls (per the email-verification worked example in DESIGN.md: shared interface vs. bolt-on). Rarely mechanically checkable; usually escalates straight to Gru rather than debate, since it's a judgment call, not a factual claim two debaters can adjudicate.
- **`inputs`** — `from` is a list of prior subtask ids (symbolic reference, not concrete values — Gru writes the plan before any subtask has run, so it can't know actual file paths a `context_gather` step will surface; the orchestrator resolves `from` references to real content at execution time). `scope` bounds where the minion is allowed to operate, both as a safety rail and to keep the mechanical checks well-defined.
- **`search_strategy`** — populated only for `context_gather`/`locate` types. This is where the "Gru decides how thoroughly to search, doesn't delegate wholesale" decision lives concretely — e.g. `{"method": "graph_traversal", "from_symbol": "is_verified", "max_hops": 2}` or `{"method": "keyword", "patterns": ["verification_type", "is_verified"]}`. Absence of a search strategy on a `context_gather` task is itself a smell worth flagging in review — it usually means Gru delegated "gather context on X" wholesale, which DESIGN.md already flagged as under-specifying completeness.
- **`verification`** — three shapes, matching the escalation ladder:

  **Mechanical**
  ```json
  {"method": "mechanical", "checks": [
    {"type": "test", "command": "...", "expect": "pass"},
    {"type": "graph_traversal", "symbol": "verify_email", "max_hops": 2, "expect_min_nodes": 5},
    {"type": "file_exists", "path": "..."}
  ]}
  ```

  **Debate** (for the non-automatable residual — see DESIGN.md's debate-verification branch)
  ```json
  {"method": "debate", "rubric": [
    "Does the search cover every call site of X within 2 hops of the graph index?",
    "Were any test files modified instead of the implementation?"
  ], "max_rounds": 3}
  ```

  **Gru escalation** (default for `design_decision`, or explicit fallback)
  ```json
  {"method": "gru_escalation", "reason": "abstraction choice requires judgment beyond a debate rubric"}
  ```

- **`escalation_policy`** — separate from `verification.method` on purpose: `verification.method` says *how a result gets judged*, `escalation_policy` says *what happens on a negative judgment*. A single cheap retry-with-feedback before escalating up the ladder catches a lot of transient mistakes without paying for debate or Gru.
- **`output_contract`** — informal now (a sentence), but this is the field a later implementation would tighten into an actual schema once subtask types stabilize; flagged rather than resolved here.

## Worked example (sequential slice)

Using the running email/SMS-verification feature example from DESIGN.md:

1. `t1` — `context_gather`: "find the current `Verifier` interface/implementation and every call site assuming email-only verification." `search_strategy`: graph traversal from `is_verified`/`verify_email`, 2 hops. `verification`: mechanical graph-traversal bound (`expect_min_nodes`) as a floor, **debate** as the completeness check on top (did it miss an implicit reference) — this is the concrete case the debate branch was designed for.
2. `t2` — `locate`: "find all existing tests covering the `Verifier` interface." `verification`: mechanical (file existence + a minimum count heuristic).
3. `t3` — `synthesize`: implement `SmsVerifier` (shown above). `verification`: mechanical, tests from `t2` plus new ones.
4. `t4` — `design_decision`: "should `SmsVerifier` share `Verifier`'s state machine or get its own?" `verification`: `gru_escalation` directly — no debate rubric attempts this, per the `type` note above.

## Open questions specific to this format

1. **Single-shot vs. staged planning.** Does Gru emit the entire plan (all subtasks, all four above) in one call before any minion runs — cheapest, but Gru can't use what `t1` actually finds to write a better `t3` spec — or does Gru get re-invoked after `context_gather`/`locate` stages to refine the `synthesize` stage's plan with real findings? This is the same plan-once-vs-re-engage tension from DESIGN.md's orchestration section, but at plan-granularity instead of per-minion-step granularity. Not resolved.
2. **Symbolic reference resolution.** `inputs.from` points at a prior subtask id; the orchestrator has to resolve that to actual content at execution time. Needs a concrete resolution mechanism (raw output passthrough? Gru-written extraction instructions on the receiving end?) — not designed yet.
3. **Can Gru expand the plan mid-execution?** E.g. if `t1`'s context-gathering surfaces something unexpected (a fifth call site nobody anticipated), can it spawn a new subtask, or does that only happen via `gru_escalation`, which would need to include "revise the remaining plan" as a possible action, not just "answer this one judgment call." Not designed yet.
4. **Debate verdict re-entry.** When a `debate`-method subtask's judge accepts/rejects, does that verdict become part of the subtask's `output_contract` for downstream consumption, or is it purely a gate? Leaning toward "gate only" (matches DESIGN.md's framing of debate as an accept/reject rung), but worth confirming once debate is actually prototyped.
