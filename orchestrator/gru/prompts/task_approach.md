## Boundaries

Modify regular source files to fix the issue, in a way that is general and consistent with the codebase — not a narrow patch for the literal example in the task. Do not modify test files, or configuration/build/packaging files (pyproject.toml, setup.cfg, and similar), unless the task explicitly calls for it. This applies whether you make the change yourself or hand it to the minion — if you delegate, the minion needs the same boundary, not just you.

## Recommended Workflow

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust

This list is a shape, not a fixed sequence — loop back to analysis whenever something later (a failed check, a delegation's summary, an edge case you hadn't considered) shows your diagnosis was incomplete. There's no penalty for revising it, and no step you've "already passed."

Diagnosis is yours regardless of how many passes it takes. Once — and only once — you're actually confident you know what the fix needs to be, delegate making the edit to the minion (`returns=verdict`, with your verification checks attached) rather than typing it yourself through `run_check`: typing in a change you've already fully decided is exactly the well-specified execution the minion is for. Exception: a change small enough that writing the delegation costs more than the edit itself, judged case by case. If a delegation's result (or a failed check) shows the diagnosis was wrong, that's not something to patch in place — it means going back to analysis with what you just learned, not re-delegating the same fix with a tweak.