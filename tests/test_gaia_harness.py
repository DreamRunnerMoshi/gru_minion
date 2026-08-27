"""Exercises the GAIA harness's own control flow against a scripted model — no docker,
no real API, no network. Uses the SAME action set as the SWE-bench side
(delegate_to_minion/think/run_check/finish, unchanged tool schema) — see
orchestrator/gaia_environment.py's module docstring for why there's no GAIA-specific
web_search/python_exec tool or answer field. Mirrors tests/test_delegation_flow.py's
role for the SWE-bench side: catches real wiring bugs before spending money on a live
GAIA run.
"""

from tests.gaia_harness import run_session
from tests.mock_llm import Tool, submit


def _finish(summary="done", checks=None):
    return Tool("finish", {"summary": summary, "final_verification": {"checks": checks or ["echo 4"]}})


def test_think_then_finish_extracts_answer_from_last_check(tmp_path):
    """finish() has no `answer` field (same shared tool schema as SWE-bench) — the
    answer comes from the last final_verification check's own stdout, independent of
    what Gru wrote in summary. This is the mechanism, not a convention Gru is trusted
    to follow."""
    steps = [
        Tool("think", {"note": "This is simple arithmetic, no search needed."}),
        _finish(summary="The answer is 4.", checks=["echo 4"]),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    assert session.result["submission"] == "4"
    assert session.gaia_env.final_answer == "4"


def test_run_check_executes_real_commands(tmp_path):
    steps = [
        Tool("run_check", {"checks": ["python3 -c \"print(2 + 2)\""]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    tool_msgs = [m for m in session.gru_agent.messages if m.get("role") == "tool"]
    assert any("4" in str(m.get("content", "")) for m in tool_msgs)


def test_run_check_can_reach_the_websearch_helper(tmp_path):
    """Same mechanism as SWE-bench's run_check reaching `git`/`sed`/etc: this is just a
    shell command, and the sandbox happens to have websearch.py on PATH — no dedicated
    tool needed."""
    steps = [
        Tool("run_check", {"checks": ["websearch.py capital of France"]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    tool_msgs = [m for m in session.gru_agent.messages if m.get("role") == "tool"]
    assert any("canned test snippet" in str(m.get("content", "")) for m in tool_msgs)


def test_delegate_agentic_findings_then_finish(tmp_path):
    """Full loop: Gru delegates a search to the minion (agentic, findings) via the
    unchanged delegate_to_minion tool, the minion runs a real bash-tool turn and
    submits, Gru reads the findings and finishes."""
    steps = [
        Tool(
            "delegate_to_minion",
            {
                "description": "Find the capital of France",
                "returns": "findings",
                "mode": "agentic",
                "inputs": {"scope": "capital of France"},
                "output_contract": "The capital city name.",
            },
        ),
        submit("echo Paris"),
        _finish(summary="minion found it", checks=["echo Paris"]),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    assert session.result["submission"] == "Paris"
    assert len(session.gaia_env.minion_records) == 1
    assert session.gaia_env.minion_records[0]["mode"] == "agentic"
    assert session.gaia_env.minion_records[0]["returns"] == "findings"


def test_delegate_verdict_uses_independent_check(tmp_path):
    """returns='verdict' must be decided by GaiaEnvironment re-running verification.checks
    itself, not by the minion's own claim — mirrors gru_environment's verifiability-trap
    design, unchanged. Script the minion claiming success while the real check would
    fail, and confirm the observation still reports FAIL."""
    steps = [
        Tool(
            "delegate_to_minion",
            {
                "description": "Compute 2 + 2",
                "returns": "verdict",
                "mode": "agentic",
                "inputs": {"scope": "arithmetic"},
                "output_contract": "N/A",
                "verification": {"checks": ["test 1 -eq 2"]},  # deliberately always-false
            },
        ),
        submit("echo 'claims success, but the check will disagree'"),
        Tool("think", {"note": "the check failed even though the minion claimed success — as expected"}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    tool_msgs = [m for m in session.gru_agent.messages if m.get("role") == "tool"]
    verdict_msg = next(m for m in tool_msgs if "Delegation t1" in str(m.get("content", "")))
    assert "FAIL" in str(verdict_msg["content"])


def test_finish_rejected_when_final_verification_fails(tmp_path):
    steps = [
        Tool("finish", {"summary": "done", "final_verification": {"checks": ["test 1 -eq 2"]}}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    # First call's checks failed and got rejected; second (real) finish succeeded —
    # confirmed indirectly by needing two calls.
    assert len(session.llm.calls) == 2
