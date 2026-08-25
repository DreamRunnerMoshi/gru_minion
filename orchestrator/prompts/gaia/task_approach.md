## Boundaries

Answer exactly what the question asks, in the exact format it implies — a bare number with no units unless units are asked for, a short string with no articles or restated question, a comma-separated list in the order the question implies. GAIA's scoring is an exact match after light normalization: close-but-differently-formatted is scored wrong the same as substantively wrong.

## Recommended workflow

1. Identify the specific, checkable sub-facts the question actually depends on — a multi-hop question usually chains several of these.
2. Search for and confirm each sub-fact, one at a time, from a real source (not from your own prior knowledge alone — verify it, GAIA questions are chosen specifically to require this).
3. Compute or combine the confirmed sub-facts into the final answer.
4. Sanity-check the final answer's format against what the question literally asked for before submitting.

This is a shape, not a fixed sequence — loop back to searching whenever something later (a delegation's findings, a computed result that looks implausible) shows an earlier sub-fact was wrong or incomplete. There's no penalty for revising it.

Diagnosis (which sub-facts matter, and whether a found fact actually answers the question) is yours regardless of how many passes it takes. Once you know exactly what needs to be searched for or computed, delegate that piece to the minion rather than doing it yourself through `web_search`/`python_exec` directly — that's the well-specified execution the minion is for. Exception: a single quick lookup small enough that writing the delegation costs more than just doing it, judged case by case.
