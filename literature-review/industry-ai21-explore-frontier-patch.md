# AI21 — "open models explore, frontier patches"

- **Type**: Industry report, not a peer-reviewed paper
- **Date**: July 2026
- **Cited in**: [DESIGN.md](../DESIGN.md) §Investigation: SWE-bench family / prior art

## Thesis

A split-model pipeline where open-weight models handle exploration and a frontier model writes the final patch.

## Key findings

- **80.8% on SWE-bench Pro at $5.99/task** — reported as state-of-the-art-at-cost for this pipeline shape at the time.

## What we took from it

A second positive existence proof (alongside [SuperScout](./2608.04804-superscout-scout-fixer-handoff.md)) for this project's core cost hypothesis: a cheap tier doing exploration, with a frontier tier doing the final synthesis, can be genuinely cost-effective rather than just "cheaper but worse." Reinforces that the split-model approach is viable *when done right* — which the [Augment/Stencil counter-example](./industry-augment-stencil-routing.md) shows isn't guaranteed by the split alone.

## Caveats

Single industry report, not independently reproduced or peer-reviewed — treated as a directional data point, same caution this project applies to other single-source benchmark claims (e.g. Qwen3.8-27B's launch-week numbers in [design/infra/04-machine-config.md](../design/infra/04-machine-config.md)).
