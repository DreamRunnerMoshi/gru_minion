## Shaping a delegation

One choice when you delegate: **`mode`** — `oneshot` (a single model call, text in and text out, no shell — supply material via `inputs.from` or `inputs.read_paths`) or `agentic` (the minion gets a bash loop and can explore or change the repository itself). The minion's actual output comes back to you.

You will be told what each delegation cost in tokens, and what your own turn just cost.
