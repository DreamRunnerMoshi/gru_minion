"""Makes `orchestrator`/`minisweagent` importable regardless of how pytest is invoked
(pytest's default rootdir insertion only adds each test file's own directory, not the
repo root)."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Same as run_exp2_single.py: an unregistered mock model name would otherwise crash
# mini-swe-agent's cost calculator.
os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

# mini-swe-agent retries any non-abort exception from the model call up to 10x with
# exponential backoff (minisweagent.models.utils.retry, up to 60s/attempt) — sensible
# against a real flaky API, but against ScriptedLLM any exception is a bug in the test's
# own script (exhausted steps, a malformed Tool/Text), and retrying it for real just
# burns minutes waiting to reraise the same error. Fail on the first attempt instead.
os.environ.setdefault("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "1")
