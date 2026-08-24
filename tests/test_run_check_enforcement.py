"""Covers the exp3 arm B finding (experiments/exp3/LOG.md Findings): `run_check` was
being used as an unrestricted bash tool — every non-empty-patch instance delegated
exactly once and did every actual edit through `run_check` instead. The fix added
`_looks_like_repo_write` (orchestrator/gru_environment.py) to reject check commands that
look like a repository write. These tests exercise it against a real scratch git repo
(real `sed`, real redirects) rather than asserting on the regex in isolation, so a false
negative that lets a real edit slip through would actually show up as a modified file.
"""

from tests.harness import run_session
from tests.mock_llm import Tool


def _finish(summary="done"):
    return Tool("finish", {"summary": summary, "final_verification": {"checks": ["true"]}})


def _first_check_output(session) -> str:
    """The run_check observation text, wherever it landed — deliberately not indexed by
    position, since exactly how many messages precede it (system/user/assistant framing)
    is a mini-swe-agent implementation detail, not something this test should pin."""
    return next(
        str(m["content"]) for m in session.gru_agent.messages if isinstance(m.get("content"), str) and "Checks:" in m["content"]
    )


def test_sed_write_is_rejected_and_file_is_untouched(tmp_path):
    steps = [
        Tool("run_check", {"checks": ["sed -i 's/foo/bar/' README.md"]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "foo\n"})

    assert session.result["exit_status"] == "Submitted"
    assert (session.repo / "README.md").read_text() == "foo\n", "run_check must not have actually run the edit"
    assert "rejected" in _first_check_output(session)


def test_redirect_write_is_rejected(tmp_path):
    steps = [
        Tool("run_check", {"checks": ["echo new-content > README.md"]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "original\n"})

    assert (session.repo / "README.md").read_text() == "original\n"
    assert "rejected" in _first_check_output(session)


def test_python_write_is_rejected(tmp_path):
    steps = [
        Tool("run_check", {"checks": ["python3 -c \"open('README.md', 'w').write('new')\""]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "original\n"})

    assert (session.repo / "README.md").read_text() == "original\n"
    assert "rejected" in _first_check_output(session)


def test_read_only_check_still_runs_for_real(tmp_path):
    """The enforcement must not overreach — genuine verification commands (grep, cat,
    pytest, ...) are the whole point of run_check and must still execute."""
    steps = [
        Tool("run_check", {"checks": ["grep -c needle README.md"]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "needle\nneedle\n"})

    check_output = _first_check_output(session)
    assert "rejected" not in check_output
    assert "Checks: PASS" in check_output


def test_write_to_tmp_is_allowed(tmp_path):
    """Scratch files under /tmp are not a repository change — a minion/Gru writing a
    reproduction script or notes there must not be caught by the same rule that blocks
    editing the actual repo."""
    steps = [
        Tool("run_check", {"checks": ["echo scratch > /tmp/repro.txt && cat /tmp/repro.txt"]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps)

    check_output = _first_check_output(session)
    assert "rejected" not in check_output
    assert "Checks: PASS" in check_output
