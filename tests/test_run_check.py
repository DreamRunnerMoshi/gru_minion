"""`run_check` runs whatever Gru asks, unrestricted — including writes.

Earlier (2026-08-23) this rejected commands that looked like a repository edit
(`_looks_like_repo_write`), added after exp3 arm B showed Gru doing real edits through
`run_check` instead of delegating. Removed 2026-08-24 on an explicit design decision:
don't force Gru's delegation behavior at the harness level, even against a smaller model
that may under-delegate — if it chooses to do work itself rather than delegate, that's a
finding about this model's behavior, not something to engineer around. See
prompts/gru-loop.md for the fuller rationale.

These tests exist to keep that decision from silently regressing — if someone adds
enforcement back to `_run_checks` without an explicit call, one of these breaks.
"""

from tests.harness import run_session
from tests.mock_llm import Tool


def _finish(summary="done"):
    return Tool("finish", {"summary": summary, "final_verification": {"checks": ["true"]}})


def test_run_check_can_write_to_the_repo(tmp_path):
    """The behavior exp3's enforcement used to block, now deliberately allowed. Edit
    command is BSD/GNU-portable (plain `sed -i` differs between them) since this runs
    as a real subprocess on whatever host runs the test — see tests/harness.py."""
    steps = [
        Tool(
            "run_check",
            {"checks": ["python3 -c \"import pathlib; p = pathlib.Path('README.md'); p.write_text(p.read_text().replace('foo', 'bar'))\""]},
        ),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "foo\n"})

    assert session.result["exit_status"] == "Submitted"
    assert (session.repo / "README.md").read_text().strip() == "bar"


def test_run_check_executes_read_only_commands(tmp_path):
    steps = [
        Tool("run_check", {"checks": ["grep -c needle README.md"]}),
        _finish(),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "needle\nneedle\n"})

    check_output = next(
        str(m["content"]) for m in session.gru_agent.messages if isinstance(m.get("content"), str) and "Checks:" in m["content"]
    )
    assert "Checks: PASS" in check_output
