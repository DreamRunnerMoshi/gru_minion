"""gru-solo.yaml (2026-08-25, exp5): a genuine no-minion baseline, for the comparison
this project has never actually run — the same model working a task alone vs. as Gru
with a minion. `tool_policy.allow_delegate: false` removes delegate_to_minion from the
tool set entirely (orchestrator/gru/toolcall.py), not just discourages it.
"""

from orchestrator.gru.config import load_gru_config
from tests.harness import run_session
from tests.mock_llm import Text, Tool


def test_solo_config_never_offers_delegate_to_minion():
    cfg = load_gru_config("swe_bench/gru-solo.yaml")
    assert cfg["tool_policy"].allow_delegate is False
    assert "delegate_to_minion" not in cfg["agent"]["system_template"]
    assert "minion" not in cfg["agent"]["system_template"].lower()


def test_solo_session_completes_without_ever_delegating(tmp_path):
    steps = [
        bash_like := Tool("run_check", {"checks": ["grep -q foo README.md"]}),
        Tool(
            "run_check",
            {"checks": ["python3 -c \"import pathlib; p = pathlib.Path('README.md'); p.write_text(p.read_text().replace('foo', 'FIXED'))\""]},
        ),
        Tool("finish", {"summary": "fixed", "final_verification": {"checks": ["grep -q FIXED README.md"]}}),
    ]
    session = run_session(
        tmp_path=tmp_path, steps=steps, repo_files={"README.md": "foo\n"}, gru_config="swe_bench/gru-solo.yaml"
    )

    assert session.result["exit_status"] == "Submitted"
    assert (session.repo / "README.md").read_text().strip() == "FIXED"
    assert session.gru_env.minion_records == []


def test_solo_session_rejects_a_delegate_to_minion_attempt(tmp_path):
    steps = [
        Tool(
            "delegate_to_minion",
            {
                "description": "do something",
                "returns": "findings",
                "mode": "oneshot",
                "inputs": {"scope": "README.md"},
                "output_contract": "one sentence",
            },
        ),
        Text("Understood, I'll work this myself."),
        Tool("finish", {"summary": "fixed", "final_verification": {"checks": ["true"]}}),
    ]
    session = run_session(
        tmp_path=tmp_path, steps=steps, repo_files={"README.md": "foo\n"}, gru_config="swe_bench/gru-solo.yaml"
    )

    # The FormatError correction (a "user" role message) must have told the model
    # delegate_to_minion isn't one of the tools this session offers.
    correction = next(
        m for m in session.gru_agent.messages if m.get("role") == "user" and "Unknown tool" in str(m.get("content", ""))
    )
    assert "delegate_to_minion" in correction["content"]
    assert session.gru_env.minion_records == []
