# Experiment Log Format

Status: design draft. Template for `experiments/<expN>/LOG.md`, one per experiment. Companion to [DESIGN.md](./DESIGN.md) (architecture/hypotheses) — this is the record of what was actually run and what happened, not what's planned.

Motivation: Experiment 0 alone burned most of a session on infra debugging (Docker-in-Docker on vast.ai, a litellm/pydantic version mismatch, a hanging finish-prompt, a wrong dataset name) that would otherwise get silently re-discovered by a future run. A fixed log format exists so that (a) results are comparable across experiments without re-deriving what conditions produced them, and (b) infra gotchas get written down once instead of re-debugged.

## Template

Write every section terse — bullets and one-liners over paragraphs. `experiments/exp0/LOG.md` is the reference example for the target density; match that, not the verbosity of an early draft.

```markdown
# Experiment <N>: <short title>

- **Status**: planned | running | complete | aborted
- **Date**: <date(s) run>
- **Hypothesis under test**: <one sentence, link to the DESIGN.md section/open question this addresses>

## Setup

- **Model(s)**: <e.g. openrouter/anthropic/claude-haiku-4.5>
- **Dataset**: <e.g. SWE-bench/SWE-bench_Lite, split=test> — use the exact HF dataset name (`princeton-nlp/SWE-bench_Lite` and `SWE-bench/SWE-bench_Lite` are NOT interchangeable — the former lacks the `image` field the harness needs)
- **Instances**: <IDs + selection method — first-N, random seed, filtered how>
- **Infra**: <where it ran, $/hr>
- **Harness**: <e.g. mini-swe-agent vX.Y.Z, config/overrides>
- **Pinned**: <any dependency pinned away from latest, one-line why — e.g. litellm==1.90.0 (1.97.0 breaks on pydantic 2.13)>

## Procedure

<Exact reproducible commands, as if written fresh knowing what now works — not a transcript of the false starts (those go in Issues encountered). One code block.>

## Results

| Instance | Resolved | Cost | Tokens | API calls |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

**<resolve rate>**, <infra failures>, <empty patches> — <one-line cost/token total, with actual-billed vs. tracked caveat if they diverge>.

## Issues encountered

<One bullet per problem: **symptom** → fix. Skip the narrative — write down anything that cost more than a few minutes, even if obvious in hindsight, so a future run doesn't rediscover it.>

## Findings

<What the results mean, not what they are — especially for failures: genuine capability limit vs. drift/hallucination vs. confidently-incomplete-self-verification vs. infra artifact. A resolve-rate number alone doesn't distinguish these, and that distinction is the point of this project. Root-cause failures individually in short bullets, then one line on the pattern across them if there is one.>

## Conclusion & next steps

<1-3 sentences: confirmed/refuted, and what it motivates running next.>

## Artifacts

<One line: directory + file types, not an exhaustive listing.>
```

## Notes on using it

- One `LOG.md` per experiment directory (`experiments/exp0/LOG.md`, `experiments/exp1/LOG.md`, ...) — colocated with the raw artifacts it references.
- Fill in **Issues encountered** even for a "successful" run if anything needed a workaround.
- **Findings** stays separate from **Results**: the table is what happened, this section is what it means — never skip it just because the table looks self-explanatory.
- Write it dense the first time rather than drafting long and trimming after — re-editing an already-written log for concision is wasted motion.
