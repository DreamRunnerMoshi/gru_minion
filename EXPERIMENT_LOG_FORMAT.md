# Experiment Log Format

Status: design draft. Template for `experiments/<expN>/LOG.md`, one per experiment. Companion to [DESIGN.md](./DESIGN.md) (architecture/hypotheses) — this is the record of what was actually run and what happened, not what's planned.

Motivation: Experiment 0 alone burned most of a session on infra debugging (Docker-in-Docker on vast.ai, a litellm/pydantic version mismatch, a hanging finish-prompt, a wrong dataset name) that would otherwise get silently re-discovered by a future run. A fixed log format exists so that (a) results are comparable across experiments without re-deriving what conditions produced them, and (b) infra gotchas get written down once instead of re-debugged.

## Template

```markdown
# Experiment <N>: <short title>

- **Status**: planned | running | complete | aborted
- **Date**: <date(s) run>
- **Hypothesis under test**: <one sentence, link to the DESIGN.md section/open question this addresses>

## Setup

- **Model(s)**: <e.g. openrouter/anthropic/claude-haiku-4.5>
- **Dataset**: <e.g. SWE-bench/SWE-bench_Lite, split=test> — note the exact HF dataset name; `princeton-nlp/SWE-bench_Lite` and `SWE-bench/SWE-bench_Lite` are NOT interchangeable (the former lacks the `image` field the harness needs)
- **Instance selection**: <IDs used + how they were chosen — first-N, random seed, filtered how>
- **Infra**: <where it ran — local / provider+instance type, $/hr, why>
- **Harness/scaffold**: <e.g. mini-swe-agent vX.Y.Z, config file/overrides used>
- **Key dependency versions**: <anything pinned away from latest, and why — e.g. litellm==1.90.0 (1.97.0 breaks on pydantic 2.13 with "Message is not fully defined")>

## Procedure

<Exact commands run, or a pointer to a script that reproduces this. Note any deviation from what was planned mid-run.>

## Results

| Instance | Resolved | Cost ($) | Steps/API calls | Notes |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

**Aggregate**: resolve rate, total cost, avg cost/instance.

## Issues encountered

<Bulleted list of infra/tooling problems hit and how they were fixed. This section is the reason this format exists — write down anything that cost more than a few minutes to figure out, even if it seems obvious in hindsight.>

## Findings

<Qualitative analysis, especially of failures: genuine capability limit vs. drift/hallucination vs. infra artifact. This is the part that actually matters for the cost-minimization hypothesis — a resolve-rate number alone doesn't distinguish these.>

## Conclusion & next steps

<Does this confirm/refute the hypothesis under test? What does it motivate running next?>

## Artifacts

<Relative paths to predictions/trajectories/reports for this experiment.>
```

## Notes on using it

- One `LOG.md` per experiment directory (`experiments/exp0/LOG.md`, `experiments/exp1/LOG.md`, ...) — keeps results colocated with the raw artifacts (trajectories, predictions, reports) it references.
- Fill in **Issues encountered** even for a "successful" run if anything needed a workaround — the target reader is a future run of this same experiment, not just this one.
- **Findings** is deliberately separate from **Results**: the table is what happened, this section is what it means. Don't skip it just because the table looks self-explanatory — a 60% resolve rate says nothing about whether the 40% failed from genuine difficulty or from drift, and that distinction is the entire point of this project.
