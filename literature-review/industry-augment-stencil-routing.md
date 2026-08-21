# Augment Code / Stencil — model routing writeup

- **Type**: Industry engineering writeup, not a peer-reviewed paper
- **Cited in**: [DESIGN.md](../DESIGN.md) §Investigation: SWE-bench family / prior art (counter-example), §Escalation design

## Thesis

Reports on a split-model routing setup (Opus plans, Gemini-Flash executes) compared directly against Opus running solo on the same tasks.

## Key findings

- **Opus-plans + Gemini-Flash-executes: $3.18/task, 84.6% pass rate.**
- **Opus solo: $2.78/task, same 84.6% pass rate.**
- The split setup was **14% more expensive** for **identical accuracy** — not cheaper, not more accurate, strictly worse on cost for the same outcome.

## What we took from it

**The single most load-bearing counter-example in this project's design.** Directly disproves the naive assumption that "split-model pipelines are automatically cheaper" — savings depend entirely on which cheap model executes and how much frontier-token overhead the plan itself costs. Two concrete downstream design decisions trace directly to this finding:

1. **Killed the "re-engage Gru after every minion completion" design.** That approach is maximally adaptive (catches drift immediately) but eats most of the cost savings the whole project hypothesis depends on — exactly the failure mode this counter-example demonstrates. Directly shaped the escalate-on-failure architecture instead (re-engage only on a failed check, not every completion).
2. **Motivates Phase 2's A/B/C/D ablation** ([design/infra/04-machine-config.md](../design/infra/04-machine-config.md) §9) rather than jumping straight to "frontier Gru + self-hosted minion" as an assumed win — this project treats its own core hypothesis as needing the same kind of real-numbers pressure test this counter-example represents, not as self-evidently true.

## Caveats

Single industry writeup, not independently reproduced — but treated as high-confidence within this project specifically because it's a *negative* result (disproving a convenient assumption), which is generally more trustworthy than a single positive benchmark claim from an interested party.
