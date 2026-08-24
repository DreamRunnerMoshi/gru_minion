"""End-to-end delegation flows against a scripted model — the thing exp3's whole
architecture is meant to produce (Gru delegates the token-heavy work, keeps the
judgement calls) exercised without needing a live model to actually make good
delegation decisions. These pin the *mechanics*: an agentic/verdict delegation really
runs a minion against the repo and Gru's own check re-verifies independently (the
"verifiability trap" principle — a real command decides pass/fail, never the minion's
self-report); a oneshot/findings delegation makes exactly one model call with the
requested material and returns the minion's raw text untouched.
"""

from tests.harness import run_session
from tests.mock_llm import Text, Tool, bash, submit


def test_agentic_verdict_delegation_runs_for_real_and_gru_reverifies(tmp_path):
    delegate = Tool(
        "delegate_to_minion",
        {
            "description": "Replace 'foo' with 'FIXED' in README.md.",
            "returns": "verdict",
            "mode": "agentic",
            "inputs": {"scope": "README.md only"},
            "output_contract": "confirm the edit is done",
            "verification": {"checks": ["grep -q FIXED README.md"]},
        },
    )
    steps = [
        delegate,
        bash("python3 -c \"import pathlib; p = pathlib.Path('README.md'); p.write_text(p.read_text().replace('foo', 'FIXED'))\""),
        submit("echo edited"),
        Tool("finish", {"summary": "fixed", "final_verification": {"checks": ["grep -q FIXED README.md"]}}),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "foo\n"})

    assert session.result["exit_status"] == "Submitted"
    assert (session.repo / "README.md").read_text().strip() == "FIXED"
    assert "FIXED" in session.result["submission"]  # the git diff patch

    # returns="verdict" delegations must not show the minion's own claim to Gru — only
    # a real check's pass/fail (orchestrator/gru_environment.py's returns=="verdict" branch).
    [record] = session.gru_env.minion_records
    assert record["returns"] == "verdict"
    assert record["mode"] == "agentic"


def test_agentic_delegation_that_fails_its_check_is_routine_not_fatal(tmp_path):
    """A delegation's check failing must not end the session — prompts/gru-loop.md's
    'On failure' section: routine, Gru keeps working. Here Gru retries with a corrected
    delegation after seeing the failure."""
    bad_delegate = Tool(
        "delegate_to_minion",
        {
            "description": "Replace 'foo' with 'FIXED' in README.md.",
            "returns": "verdict",
            "mode": "agentic",
            "inputs": {"scope": "README.md only"},
            "output_contract": "confirm the edit is done",
            "verification": {"checks": ["grep -q FIXED README.md"]},
        },
    )
    retry_delegate = Tool(
        "delegate_to_minion",
        {
            "description": "Actually replace 'foo' with 'FIXED' in README.md this time.",
            "returns": "verdict",
            "mode": "agentic",
            "inputs": {"scope": "README.md only"},
            "output_contract": "confirm the edit is done",
            "verification": {"checks": ["grep -q FIXED README.md"]},
        },
    )
    steps = [
        bad_delegate,
        submit("echo did nothing useful"),  # minion submits without ever editing the file
        retry_delegate,
        bash("python3 -c \"import pathlib; p = pathlib.Path('README.md'); p.write_text(p.read_text().replace('foo', 'FIXED'))\""),
        submit("echo edited for real"),
        Tool("finish", {"summary": "fixed", "final_verification": {"checks": ["grep -q FIXED README.md"]}}),
    ]
    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "foo\n"})

    assert session.result["exit_status"] == "Submitted"
    assert len(session.gru_env.minion_records) == 2
    assert session.gru_env.minion_records[0]["returns"] == "verdict"


def test_oneshot_findings_delegation_makes_one_call_with_the_requested_material(tmp_path):
    delegate = Tool(
        "delegate_to_minion",
        {
            "description": "Summarize what this file says.",
            "returns": "findings",
            "mode": "oneshot",
            "inputs": {"scope": "README.md", "read_paths": ["README.md"]},
            "output_contract": "one sentence",
        },
    )
    # A oneshot minion call is a plain text completion (GruEnvironment._run_oneshot reads
    # response.choices[0].message.content directly, no tool_calls involved) — Text, not Tool.
    steps = [
        delegate,
        Text("The file marks this build as UNIQUE_MARKER_42."),
        Tool("finish", {"summary": "noted", "final_verification": {"checks": ["true"]}}),
    ]

    session = run_session(tmp_path=tmp_path, steps=steps, repo_files={"README.md": "UNIQUE_MARKER_42\n"})

    assert session.result["exit_status"] == "Submitted"
    [record] = session.gru_env.minion_records
    assert record["mode"] == "oneshot"
    assert record["api_calls"] == 1
    assert session.gru_env.delegation_outputs["t1"] == "The file marks this build as UNIQUE_MARKER_42."

    # inputs.read_paths must have actually handed the file content to the model.
    oneshot_call = session.llm.calls[1]
    assert "UNIQUE_MARKER_42" in str(oneshot_call["messages"])
