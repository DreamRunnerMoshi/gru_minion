## Boundaries

Modify regular source files to fix the issue, in a way that is general and consistent with the codebase — not a narrow patch for the literal example in the task. Do not modify test files, or configuration/build/packaging files (pyproject.toml, setup.cfg, and similar), unless the task explicitly calls for it. This applies whether you make the change yourself or hand it to the minion — if you delegate, the minion needs the same boundary, not just you.

## Recommended Workflow

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust

Steps 1 and 2 are diagnosis — do those yourself, however much investigation they take. Once they've told you exactly what the fix needs to be, delegate step 3 — making the edit — to the minion (`returns=verdict`, with the checks from steps 2 and 5 attached as `verification.checks`) instead of typing it yourself through `run_check`. You already did the hard part; typing the edit in is exactly the kind of well-specified execution the minion is for. The one exception: a change small enough that writing the delegation costs more than the edit itself — judge that case by case, but delegating is the default once you know what the fix is, not something to talk yourself out of.