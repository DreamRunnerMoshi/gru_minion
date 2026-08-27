"""orchestrator/delegate.py — issuing delegations by hand, with a human or an agent
playing Gru instead of a model.

The delegation itself is the same code path the automated loop uses (GruEnvironment's
own `_delegate`), already covered by tests/test_delegation_flow.py. What's new and worth
pinning is the part that only exists because each CLI call is a separate process: session
state has to survive between invocations, or a second delegation would restart the
counter at t1 and `inputs.from` could never reach an earlier delegation's output.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from litellm.types.utils import Choices, Message, ModelResponse, Usage

from orchestrator import delegate


def _canned(text: str):
    def fake_completion(**kwargs):
        fake_completion.calls.append(kwargs)
        return ModelResponse(
            choices=[Choices(message=Message(role="assistant", content=text))],
            usage=Usage(prompt_tokens=100, completion_tokens=10, total_tokens=110),
        )

    fake_completion.calls = []
    return fake_completion


def run_delegation(tmp_path: Path, spec: dict, llm, session: str = "s1", cwd: Path | None = None) -> None:
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec))
    argv = [
        "delegate",
        "--session", str(tmp_path / session),
        "--spec", str(spec_file),
        "--cwd", str(cwd or tmp_path),
        "--model", "mock/minion",
    ]
    with patch("litellm.completion", llm), patch.object(sys, "argv", argv):
        delegate.main()


def oneshot(description: str, **inputs) -> dict:
    return {
        "description": description,
        "returns": "findings",
        "mode": "oneshot",
        "inputs": {"scope": ".", **inputs},
        "output_contract": "one line",
    }


def test_session_state_survives_across_separate_invocations(tmp_path):
    """Two delegations, two processes' worth of CLI entry: the second must be t2, and
    must be able to reference t1's output through inputs.from."""
    (tmp_path / "note.txt").write_text("the answer is 42\n")

    first = _canned("FINDINGS-FROM-T1")
    run_delegation(tmp_path, oneshot("Read the note", read_paths=["note.txt"]), first)

    second = _canned("FINDINGS-FROM-T2")
    run_delegation(tmp_path, oneshot("Restate t1", **{"from": ["t1"]}), second)

    outputs = sorted(p.stem for p in (tmp_path / "s1" / "delegations").glob("t*.txt"))
    assert outputs == ["t1", "t2"], "ids must continue across processes, not restart"

    handed_to_t1 = first.calls[0]["messages"][-1]["content"]
    assert "the answer is 42" in handed_to_t1, "read_paths content must reach the minion"

    handed_to_t2 = second.calls[0]["messages"][-1]["content"]
    assert "FINDINGS-FROM-T1" in handed_to_t2, "inputs.from must resolve a prior delegation's output"

    records = json.loads((tmp_path / "s1" / "minions.json").read_text())
    assert [r["delegation_id"] for r in records] == ["t1", "t2"]
    assert sum(r["total_tokens"] for r in records) == 220, "cost accounting accumulates across invocations"


def test_a_delegation_the_real_tool_would_reject_is_rejected_here_too(tmp_path):
    """No privileged hand-written path: the CLI runs the same validator a model's tool
    call goes through. A verdict delegation with no checks has nothing to compute a
    verdict from, so it must be refused before any minion is charged."""
    llm = _canned("never reached")
    bad = {
        "description": "Fix it",
        "returns": "verdict",
        "mode": "oneshot",
        "inputs": {"scope": "."},
        "output_contract": "a patch",
    }
    with pytest.raises(SystemExit) as excinfo:
        run_delegation(tmp_path, bad, llm)
    assert excinfo.value.code == 2
    assert llm.calls == [], "no model call may be made for a spec that failed validation"


def test_summary_reports_what_the_session_spent(tmp_path, capsys):
    run_delegation(tmp_path, oneshot("Do a thing", read_paths=["/dev/null"]), _canned("done"))
    with patch.object(sys, "argv", ["delegate", "--session", str(tmp_path / "s1"), "--summary"]):
        delegate.main()
    out = capsys.readouterr().out
    assert "t1" in out and "Do a thing" in out
    assert "1 delegations, 1 model calls, 110 minion tokens" in out


def test_working_tree_is_snapshotted_before_a_delegation_runs(tmp_path):
    """A minion told to tidy the working tree (config/*/minion.yaml's verdict Submission
    step) will revert changes that aren't its own. In the real harness that is safe —
    fresh container, no one else's work present. Here the tree is the operator's real
    repository, and the first live verdict delegation duly reverted an uncommitted
    function that this CLI itself imported. So the tree is captured first, and anything
    reverted stays recoverable."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)

    (repo / "keep.py").write_text("committed = 1\n")
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-q", "-m", "initial")

    # the operator's in-flight, uncommitted work
    (repo / "keep.py").write_text("committed = 1\nWORK_IN_PROGRESS = 2\n")

    run_delegation(tmp_path, oneshot("touch nothing", read_paths=["keep.py"]), _canned("ok"), cwd=repo)

    snapshots = json.loads((tmp_path / "s1" / "snapshots.json").read_text())
    assert "t1" in snapshots, "a snapshot must be taken before the delegation runs"

    # simulate the minion reverting the operator's work, as it really did
    git("checkout", "--", "keep.py")
    assert "WORK_IN_PROGRESS" not in (repo / "keep.py").read_text()

    git("checkout", snapshots["t1"], "--", "keep.py")
    assert "WORK_IN_PROGRESS" in (repo / "keep.py").read_text(), "snapshot must make it recoverable"


def test_verdict_delegation_refuses_a_dirty_working_tree(tmp_path):
    """The guard for the incident in this module's docstring: a verdict minion reverts
    what isn't its own, so it must not be pointed at a tree holding uncommitted work
    unless the operator explicitly accepts that."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)

    (repo / "a.py").write_text("x = 1\n")
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-q", "-m", "initial")

    verdict = {
        "description": "change a.py",
        "returns": "verdict",
        "mode": "agentic",
        "inputs": {"scope": "a.py"},
        "output_contract": "summary.md",
        "verification": {"checks": ["true"]},
    }
    llm = _canned("never reached")

    # clean tree: the guard does not fire (the delegation proceeds to the model)
    run_delegation(tmp_path, verdict, llm, session="clean", cwd=repo)
    assert llm.calls, "a clean tree must not be blocked"

    # dirty tree: refused before any model call
    (repo / "a.py").write_text("x = 1\nWORK_IN_PROGRESS = 2\n")
    blocked = _canned("never reached")
    with pytest.raises(SystemExit) as excinfo:
        run_delegation(tmp_path, verdict, blocked, session="dirty", cwd=repo)
    assert excinfo.value.code == 2
    assert blocked.calls == [], "nothing may be charged when the tree is refused"


def test_benchmark_minion_configs_are_refused_by_default(tmp_path):
    """The benchmark minion configs ship in the same wheel as the general-purpose one and
    their names read as authoritative, but their Submission steps tell the minion to
    revert anything in the tree unrelated to its own task — correct in a throwaway scoring
    container, destructive against a real checkout. Reaching one by accident must not be
    possible."""
    llm = _canned("never reached")
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(oneshot("x", read_paths=["/dev/null"])))

    def invoke(*extra):
        argv = ["delegate", "--session", str(tmp_path / "s"), "--spec", str(spec_file),
                "--cwd", str(tmp_path), "--model", "mock/minion", *extra]
        with patch("litellm.completion", llm), patch.object(sys, "argv", argv):
            delegate.main()

    for unsafe in ("swe_bench/minion.yaml", "gaia/minion.yaml"):
        with pytest.raises(SystemExit) as excinfo:
            invoke("--minion-config", unsafe)
        assert excinfo.value.code == 2
    assert llm.calls == [], "nothing may be charged for a refused config"

    # the escape hatch exists for the benchmark harness, and works
    invoke("--minion-config", "swe_bench/minion.yaml", "--benchmark-minion-config")
    assert llm.calls, "--benchmark-minion-config must permit it"
