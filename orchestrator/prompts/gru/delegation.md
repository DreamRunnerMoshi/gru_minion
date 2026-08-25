## Shaping a delegation

Two choices when you delegate:

**`returns`** — `findings` (the minion's actual output comes back to you) or `verdict` (pass/fail, computed by running your `verification.checks` independently after the minion finishes — not the minion's own opinion of its work).

**`mode`** — `oneshot` (a single model call, text in and text out, no shell — supply material via `inputs.from` or `inputs.read_paths`) or `agentic` (the minion gets a bash loop and can explore or change the repository itself).

## What comes back

Whichever `returns` you choose, the minion always reports back what it actually did — you are never delegating into a black box, and you don't have to guess at what happened before deciding your next step. For `findings`, that's the full findings text, summary first. For `verdict`, you get a short summary of what changed and why (not the raw patch) alongside the independently-computed pass/fail. Trust the pass/fail for whether it actually worked — that's the real check, not the minion's opinion — but read the summary too, especially on a FAIL: it's often the fastest way to see whether the delegation failed because the work was wrong, or because your own verification checks didn't test the right thing.
