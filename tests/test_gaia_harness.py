"""Exercises the GAIA harness's own control flow (tool dispatch, delegation, finish)
against a scripted model — no docker, no real API, no network. Mirrors
tests/test_delegation_flow.py's role for the SWE-bench side: catches real wiring bugs
(wrong action name, wrong field name, wrong exit condition) before spending money on a
live GAIA run.
"""

from tests.gaia_harness import run_session
from tests.mock_llm import Tool, submit


def _finish(answer="4", reasoning="2 + 2 = 4"):
    return Tool("finish", {"answer": answer, "reasoning": reasoning})


def test_think_then_finish(tmp_path):
    steps = [
        Tool("think", {"note": "This is simple arithmetic, no search needed."}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    assert session.result["submission"] == "4"
    assert session.gaia_env.final_reasoning == "2 + 2 = 4"


def test_python_exec_runs_real_code(tmp_path):
    steps = [
        Tool("python_exec", {"code": "print(2 + 2)"}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    tool_msgs = [m for m in session.gru_agent.messages if m.get("role") == "tool"]
    assert any("4" in str(m.get("content", "")) for m in tool_msgs)


def test_web_search_hits_the_fake_script(tmp_path):
    steps = [
        Tool("web_search", {"query": "capital of France"}),
        _finish(answer="Paris", reasoning="found via search"),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    tool_msgs = [m for m in session.gru_agent.messages if m.get("role") == "tool"]
    assert any("canned test snippet" in str(m.get("content", "")) for m in tool_msgs)


def test_delegate_agentic_findings_then_finish(tmp_path):
    """Full loop: Gru delegates a search to the minion (agentic, findings), the minion
    runs a real bash-tool turn and submits, Gru reads the findings and finishes."""
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
        submit("echo Paris"),  # minion's only turn: real bash, real subprocess, no docker needed
        _finish(answer="Paris", reasoning="minion found it"),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    assert session.result["submission"] == "Paris"
    assert len(session.gaia_env.minion_records) == 1
    assert session.gaia_env.minion_records[0]["mode"] == "agentic"
    assert session.gaia_env.minion_records[0]["returns"] == "findings"


def test_delegate_verdict_uses_independent_python_check(tmp_path):
    """returns='verdict' must be decided by GaiaEnvironment re-running verification.checks
    itself, not by the minion's own claim — mirrors gru_environment's verifiability-trap
    design. Script the minion claiming success while the real check would fail, and
    confirm the observation still reports FAIL."""
    steps = [
        Tool(
            "delegate_to_minion",
            {
                "description": "Compute 2 + 2",
                "returns": "verdict",
                "mode": "agentic",
                "inputs": {"scope": "arithmetic"},
                "output_contract": "N/A",
                "verification": {"checks": ["print(1 == 2)"]},  # deliberately always-false
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


def test_finish_without_answer_is_rejected(tmp_path):
    steps = [
        Tool("finish", {"answer": "", "reasoning": "empty answer, should be rejected"}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "Submitted"
    # First call's response should have been a FormatError, not an immediate Submitted —
    # confirmed indirectly: two calls were needed (the empty-answer attempt, then the real one).
    assert len(session.llm.calls) == 2
