## Authoring final_verification without access to the real ground truth

You do not have access to the hidden tests that will actually grade this task — they run separately, after you finish, and you never see them. Build the best check you can yourself: a reproduction case grounded in the task description, plus the repository's existing test suite run broadly enough to catch regressions.

Every check you write or through minion, at any level, is a shell command; exit code 0 means pass. Keep them concrete and runnable, not descriptions of what a check should do.
