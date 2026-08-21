# Anthropic — How we built our multi-agent research system

- **Type**: Industry engineering writeup, not a peer-reviewed paper
- **Source**: [anthropic.com/engineering/multi-agent-research-system](https://www.anthropic.com/engineering/multi-agent-research-system)
- **Cited in**: [design/architecture/02-gru-minion-protocol.md](../design/architecture/02-gru-minion-protocol.md) §2, §6

## Thesis

Describes Anthropic's own production lead-agent + parallel-subagent research system: how tasks are scoped to subagents, how results are synthesized, and what topology/scaling heuristics worked in practice.

## Key findings

- **Task structuring that worked**: each subagent needs an explicit objective, output format, tool/source guidance, and clear scope boundary. Vague instructions ("research the semiconductor shortage") caused subagents to duplicate work and misalign.
- **Scaling heuristics** (guidance, not rigid rules): simple fact-finding → 1 agent, 3-10 tool calls; direct comparisons → 2-4 subagents, 10-15 calls each; complex research → 10+ subagents with clearly divided responsibilities.
- **Topology**: fan-out-and-synthesize — subagents run in parallel, report back, and the lead re-reads everything and synthesizes. Necessary because open-ended research has no automated pass/fail gate, so the lead is the only available verifier and every result has to route through it.
- **Cost**: ~15× tokens vs. single-agent, and delegation "explains 80% of variance" in eval score in their own analysis.

## What we took from it

The closest real production analog to this project's Gru/minion design — this is the reference point [02-gru-minion-protocol.md](../design/architecture/02-gru-minion-protocol.md) is written against directly.

- **Adopted directly**: bound every delegated sub-call explicitly (objective + output format + scope boundary) — Anthropic's finding that vague delegation causes duplication/misalignment is directly actionable for how Gru phrases a minion research request.
- **Adopted (topology)**: lead + bounded workers, one level of delegation, bounded-scope task instructions, artifacts-over-prose in subagent reports.
- **Deliberately NOT adopted (re-engagement frequency)**: Anthropic's every-result-through-the-lead requirement is the direct cause of their ~15× token cost. This project uses **escalate-on-failure** instead — Gru is re-engaged only when a mechanical check fails, not on every minion completion. This divergence is possible specifically because SWE-bench-style tasks admit automated verification (test runners, FAIL_TO_PASS/PASS_TO_PASS) that open-ended research tasks don't — Anthropic's lead has no automated gate and must personally verify every result, this project's Gru does. Re-engaging Gru on every minion completion was explicitly rejected because it would eat most of the cost-savings hypothesis this project is testing (see [Augment/Stencil counter-example](./industry-augment-stencil-routing.md)).

## Caveats

Not adopted wholesale — see the explicit divergence note above. Don't read this project's design as "copying" the Anthropic pattern; the topology transfers, the re-engagement frequency does not, because it's downstream of a difference in task verifiability, not a design preference.
