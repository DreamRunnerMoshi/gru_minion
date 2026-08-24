## Shaping a delegation

Two choices when you delegate:

**`returns`** — `findings` (the minion's actual output comes back to you) or `verdict` (pass/fail, computed by running your `verification.checks` independently after the minion finishes — not the minion's own opinion of its work).

**`mode`** — `oneshot` (a single model call, text in and text out, no shell — supply material via `inputs.from` or `inputs.read_paths`) or `agentic` (the minion gets a bash loop and can explore or change the repository itself).

## Authoring final_verification without access to the real ground truth

You do not have access to the hidden tests that will actually grade this task — they run separately, after you finish, and you never see them. Build the best check you can yourself: a reproduction case grounded in the task description, plus the repository's existing test suite run broadly enough to catch regressions.

Every check you write or through minion, at any level, is a shell command; exit code 0 means pass. Keep them concrete and runnable, not descriptions of what a check should do.
