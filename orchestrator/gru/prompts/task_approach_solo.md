## Boundaries

Modify regular source files to fix the issue, in a way that is general and consistent with the codebase — not a narrow patch for the literal example in the task. Do not modify test files, or configuration/build/packaging files (pyproject.toml, setup.cfg, and similar), unless the task explicitly calls for it.

## Recommended Workflow

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust

This list is a shape, not a fixed sequence — loop back to analysis whenever something later (a failed check, an edge case you hadn't considered) shows your diagnosis was incomplete. There's no penalty for revising it, and no step you've "already passed."
