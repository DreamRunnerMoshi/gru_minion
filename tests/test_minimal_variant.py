"""Covers gru-minimal.yaml (2026-08-24) — step 1 of a bit-by-bit prompt ablation:
just delegate_to_minion and a bare finish, no verification, no failure handling. The
mechanism behind it (orchestrator/gru_toolcall.py's ToolPolicy) is what these tests
actually exercise: that the excluded actions/fields aren't just absent from the prompt
text but are genuinely rejected if the model tries them anyway, and that `finish`
without a verification step really does end the session unconditionally.
"""

from tests.harness import run_session
from tests.mock_llm import Text, Tool


def test_bare_finish_ends_the_session_without_any_check(tmp_path):
    """No final_verification field at all — not even a trivial `true` check — and the
    session still ends cleanly. This is the mechanical heart of "no verification step":
    orchestrator/gru_environment.py's _run_checks([]) already treats an empty/absent
    checks list as an automatic pass, so no code path was even needed to special-case
    this — removing the field from the tool schema (ToolPolicy) was enough."""
    steps = [Tool("finish", {"summary": "nothing to do here"})]
    session = run_session(tmp_path=tmp_path, steps=steps, gru_config="gru-minimal.yaml")

    assert session.result["exit_status"] == "Submitted"


def test_delegation_only_returns_findings_never_verdict(tmp_path):
    steps = [
        Tool(
            "delegate_to_minion",
            {
                "description": "Summarize this file.",
                "returns": "findings",
                "mode": "oneshot",
                "inputs": {"scope": "README.md", "read_paths": ["README.md"]},
                "output_contract": "one sentence",
            },
        ),
        Text("It says hello."),
        Tool("finish", {"summary": "done"}),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, gru_config="gru-minimal.yaml", repo_files={"README.md": "hello\n"})

    assert session.result["exit_status"] == "Submitted"
    [record] = session.gru_env.minion_records
    assert record["returns"] == "findings"


def test_verdict_is_rejected_as_an_unknown_option(tmp_path):
    """A model that tries returns='verdict' anyway (e.g. copying behavior from a
    different session) must be bounced the same way an invalid enum value always is —
    not silently accepted into a policy that doesn't offer it."""
    bad_delegate = Tool(
        "delegate_to_minion",
        {
            "description": "Fix it.",
            "returns": "verdict",
            "mode": "agentic",
            "inputs": {"scope": "README.md"},
            "output_contract": "confirm",
            "verification": {"checks": ["true"]},
        },
    )
    good_delegate = Tool(
        "delegate_to_minion",
        {
            "description": "Fix it.",
            "returns": "findings",
            "mode": "agentic",
            "inputs": {"scope": "README.md"},
            "output_contract": "confirm",
        },
    )
    steps = [
        bad_delegate,
        good_delegate,
        Tool("bash", {"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && echo done"}),
        Tool("finish", {"summary": "done"}),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, gru_config="gru-minimal.yaml")

    assert session.result["exit_status"] == "Submitted"
    rejection = next(
        str(m["content"]) for m in session.gru_agent.messages
        if isinstance(m.get("content"), str) and "must be one of" in m["content"]
    )
    assert "'verdict'" in rejection or "verdict" in rejection


def test_think_and_run_check_are_not_offered(tmp_path):
    """Calling think/run_check in this variant must fail the same way any unknown tool
    name would — they were never advertised (ToolPolicy.allow_think/allow_run_check are
    False), so a model reaching for them anyway needs the same correction a typo would get."""
    steps = [
        Tool("think", {"note": "let me consider this"}),
        Tool("finish", {"summary": "done"}),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, gru_config="gru-minimal.yaml")

    assert session.result["exit_status"] == "Submitted"
    rejection = next(
        str(m["content"]) for m in session.gru_agent.messages
        if isinstance(m.get("content"), str) and "Unknown tool" in m["content"]
    )
    assert "think" in rejection
    assert "run_check" not in rejection.split("Must be one of")[1]  # not offered as an alternative either
