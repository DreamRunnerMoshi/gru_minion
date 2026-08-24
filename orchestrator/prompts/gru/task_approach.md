## Boundaries

Modify regular source files to fix the issue, in a way that is general and consistent with the codebase — not a narrow patch for the literal example in the task. Do not modify test files, or configuration/build/packaging files (pyproject.toml, setup.cfg, and similar), unless the task explicitly calls for it. This applies whether you make the change yourself or hand it to the minion — if you delegate, the minion needs the same boundary, not just you.

## Recommended Workflow

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust

While doing all these steps, always remember you have minion to work for you.