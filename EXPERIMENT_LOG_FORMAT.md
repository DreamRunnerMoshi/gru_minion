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

**Numbers only. One table, one summary line. No prose paragraphs, no methodology, no caveats, no "why this matters" — those go in Findings or NOTES.md (see below).** If you catch yourself writing a second sentence under the table, stop and move it out.

| Instance | Resolved | Prompt tok | Compl tok | Cache-hit% | API calls | Wall-clock |
|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... |
| **Total** | x/N | ... | ... | ... | ... | ... |

`<resolve rate>` · `<cost total, $ or GPU-hr>` · `<infra failures>` · `<empty patches>`

Drop any column that doesn't apply (e.g. no cache-hit% if the provider doesn't expose it) rather than filling it with N/A. Add a column instead of a paragraph if a new metric is genuinely per-instance data (this is how prompt/compl/cache-hit got added here) — the test for "column vs. Findings bullet vs. NOTES.md" is: *is it a number that varies per instance* (→ column) *, a one-sentence takeaway* (→ Findings bullet) *, or does explaining it need methodology/caveats/multiple sentences* (→ NOTES.md).

**Cache stats**: capture KV/prompt-cache reuse live, during the run, not after, whenever the provider exposes it — self-hosted or metered API (Anthropic's `cache_read_input_tokens`, OpenAI's `prompt_tokens_details.cached_tokens`, or the self-hosted server's own stats endpoint if litellm doesn't surface it). Reconstructing it later from a destroyed instance only gets you an estimate — see `experiments/exp1/NOTES.md` for what that reconstruction looks like and why it's a fallback, not the plan.

## Issues encountered

<One bullet per problem: **symptom** → fix. Skip the narrative — write down anything that cost more than a few minutes, even if obvious in hindsight, so a future run doesn't rediscover it.>

## Findings

<What the results mean, not what they are — one bullet per point, **2 sentences max each**. Especially for failures: genuine capability limit vs. drift/hallucination vs. confidently-incomplete-self-verification vs. infra artifact. Root-cause failures individually in short bullets, then one line on the pattern across them if there is one. If a finding needs more than 2 sentences to state, it needs NOTES.md, not a longer bullet.>

## Conclusion & next steps

<1-3 sentences: confirmed/refuted, and what it motivates running next.>

## Artifacts

<One line: directory + file types, not an exhaustive listing.>
```

## NOTES.md — where the long stuff goes

Some findings genuinely need methodology, worked numbers, and caveats to be credible (e.g. "how was cache-hit % estimated after the instance was destroyed" needs to show its work). That doesn't belong in `LOG.md` — put it in `experiments/<expN>/NOTES.md` and link it from the one Findings bullet that needs it: `- Cache-hit ~96% (est.) — real cost lever, see [NOTES.md](./NOTES.md)#cache-estimate.` `LOG.md` should be readable end-to-end in under a minute; `NOTES.md` is where you're allowed to show your work at whatever length it takes. `experiments/exp1/NOTES.md` is the reference example.

## Notes on using it

- One `LOG.md` per experiment directory (`experiments/exp0/LOG.md`, `experiments/exp1/LOG.md`, ...) — colocated with the raw artifacts it references. `NOTES.md` alongside it is optional — only add one when a finding actually needs the space.
- Fill in **Issues encountered** even for a "successful" run if anything needed a workaround.
- **Findings** stays separate from **Results**: the table is what happened, this section is what it means — never skip it just because the table looks self-explanatory.
- Write it dense the first time rather than drafting long and trimming after — re-editing an already-written log for concision is wasted motion.
- **If a correction is needed after the fact** (a finding turns out to be wrong or overstated), edit the bullet in place — don't leave the old claim standing with a "Correction:" bullet appended after it. `LOG.md` should read as current-best-understanding, not as a transcript of the discussion that produced it; the discussion trail belongs in conversation history, not the file.
