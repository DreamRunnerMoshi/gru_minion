#!/usr/bin/env python3
"""Issue one delegation by hand, as Gru would — for sessions where a human (or an agent
like Claude Code) plays the planning role and an OpenRouter model plays the minion.

Added 2026-08-27. Every earlier experiment drove Gru with a model, which conflated two
questions the architecture actually raises separately:

1. *Will a planner choose to delegate?* exp3/exp4 kept answering "barely" — DeepSeek V4
   Pro delegated zero times in 80 turns, and exp3 arm B did real edits through run_check
   instead. That is a finding about those models, deliberately not engineered around
   (see prompts/gru-loop.md).
2. *When work is delegated, is the cheap minion actually good and cheap enough?* That is
   the architecture's real premise, and question 1 has been drowning it out.

Driving delegations from here removes question 1 from the picture: the planner delegates
because the operator decided to, so what comes back measures the minion alone.

This is deliberately NOT a reimplementation. It builds the same `GruEnvironment` the
automated loop uses and calls the same `_delegate`, so delegations go through the real
input-gathering, the real minion runner, the real independent check re-runs, and the
real cost accounting. The only things it adds are (a) a CLI, and (b) session state that
survives between invocations, since each shell command is a fresh process where the
automated loop is one long-lived object.

No Docker required: delegations run against mini-swe-agent's LocalEnvironment, in a real
working directory. That is the same class the test harness uses — real shell commands,
real edits, real `git diff` — so it exercises the minion exactly as a container would,
against whatever repository you point `--cwd` at.

**That difference is not free, and it cost real work the first time this ran.** A
verdict-mode minion is told (config/*/minion.yaml, Submission step 1) to make sure the
working tree holds only changes relevant to its own delegation, and to revert anything
else. In the real harness that is correct and safe: every run gets a fresh container
whose only uncommitted changes are the minion's own. Here the working tree is the
operator's real repository, and "revert what isn't mine" means reverting the planner's
in-flight, uncommitted edits — which is exactly what happened on the first live verdict
delegation, taking out an uncommitted function that the CLI itself imported.

So every delegation is preceded by `git stash create`, which writes a commit object
capturing the current index and working tree *without touching either*, kept alive under
`refs/gru-snapshots/` so it cannot be garbage-collected. Nothing the minion reverts is
lost: `git checkout <snapshot> -- <path>` brings any file back. Committing (or stashing)
your own work before delegating is still the better habit; this is the safety net for
when you don't.

Usage:
    # findings: send the minion to go read something and report back
    cat > /tmp/d.json <<'EOF'
    {
      "description": "Find every call site of load_gru_config and report file:line for each.",
      "returns": "findings",
      "mode": "agentic",
      "inputs": {"scope": "orchestrator/ and tests/"},
      "output_contract": "findings.md: a bulleted list of file:line, one per call site."
    }
    EOF
    python -m orchestrator.delegate --spec /tmp/d.json --session .gru/s1

    # verdict: have the minion make a change, judged by checks re-run independently here
    python -m orchestrator.delegate --spec /tmp/fix.json --session .gru/s1

    python -m orchestrator.delegate --session .gru/s1 --summary   # what this session cost

Installed as a console script (see pyproject.toml), the same commands read:

    gru-delegate --spec /tmp/d.json --session .gru/s1
    uvx --from git+https://github.com/DreamRunnerMoshi/gru_minion gru-delegate --help
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

from minisweagent.environments.local import LocalEnvironment  # noqa: E402

from orchestrator.configs import load_yaml  # noqa: E402
from orchestrator.gru.environment import GruEnvironment  # noqa: E402
from orchestrator.gru.toolcall import validate_delegation  # noqa: E402
from orchestrator.minion.runner import MinionRunner  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("delegate")

RECORDS_FILE = "minions.json"


class LocalEnvironmentWithCleanup(LocalEnvironment):
    """LocalEnvironment plus the no-op cleanup() a container-shaped caller expects."""

    def cleanup(self) -> None:
        pass


def _resume(env: GruEnvironment, session: Path) -> None:
    """Rehydrate the state the automated loop keeps in memory. Each CLI call is its own
    process, so without this a second delegation would restart the counter at t1 and
    `inputs.from` could never reference an earlier delegation's output."""
    delegations = session / "delegations"
    if delegations.is_dir():
        for path in delegations.glob("t*.txt"):
            env.delegation_outputs[path.stem] = path.read_text()
        ids = [int(m.group(1)) for p in delegations.glob("t*.txt") if (m := re.fullmatch(r"t(\d+)", p.stem))]
        env.delegation_counter = max(ids, default=0)
    records = session / RECORDS_FILE
    if records.is_file():
        env.minion_records = json.loads(records.read_text())


def snapshot_working_tree(cwd: Path, session: Path, delegation_id: str) -> str | None:
    """Capture the working tree so a minion that "cleans" it can't destroy the operator's
    own uncommitted work — see this module's docstring for the incident that motivated
    this. `git stash create` builds the commit object but does not modify the tree, the
    index, or the stash list, so it is invisible to whatever the minion then does. The
    ref keeps it from being garbage-collected. Returns None outside a git repo, or when
    the tree is clean and there is nothing to capture."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)

    if git("rev-parse", "--git-dir").returncode != 0:
        return None
    created = git("stash", "create")
    sha = created.stdout.strip()
    if created.returncode != 0 or not sha:
        return None  # clean tree: nothing to lose
    git("update-ref", f"refs/gru-snapshots/{session.name}-{delegation_id}", sha)
    (session / "snapshots.json").write_text(
        json.dumps({**_snapshots(session), delegation_id: sha}, indent=2)
    )
    return sha


def uncommitted_paths(cwd: Path) -> list[str]:
    """Files with uncommitted changes, as `git status --porcelain` short codes. Empty
    outside a git repo or when the tree is clean."""
    r = subprocess.run(["git", "-C", str(cwd), "status", "--porcelain"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip() and not line.startswith("??")]


def _snapshots(session: Path) -> dict:
    path = session / "snapshots.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def build_environment(*, session: Path, cwd: Path, model: str, cost_limit: float, minion_config: str) -> GruEnvironment:
    session.mkdir(parents=True, exist_ok=True)
    shell = LocalEnvironmentWithCleanup(cwd=str(cwd))
    env = GruEnvironment(
        env=shell,
        minions=MinionRunner.from_config(
            load_yaml(minion_config),
            env=shell,
            model_name=model,
            cost_limit=cost_limit,
            output_dir=session,
            run_id=session.name,
        ),
        output_dir=session,
        logger=logger,
    )
    _resume(env, session)
    return env


def print_summary(session: Path) -> None:
    records = session / RECORDS_FILE
    if not records.is_file():
        print(f"no delegations recorded in {session}")
        return
    rows = json.loads(records.read_text())
    total_tokens = sum(r["total_tokens"] for r in rows)
    total_calls = sum(r["api_calls"] for r in rows)
    print(f"{'id':>4}  {'mode':<8} {'returns':<9} {'calls':>5} {'tokens':>9}  description")
    for r in rows:
        print(
            f"{r['delegation_id']:>4}  {r['mode']:<8} {r['returns']:<9} {r['api_calls']:>5} "
            f"{r['total_tokens']:>9,}  {r['description'][:60]}"
        )
    print(f"\n{len(rows)} delegations, {total_calls} model calls, {total_tokens:,} minion tokens")
    print(f"trajectories: {session}/minions/    outputs: {session}/delegations/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", required=True, type=Path, help="Session directory: holds delegation outputs, minion trajectories and the cost record. Reuse the same one across a working session so inputs.from can reference earlier delegations.")
    parser.add_argument("--spec", type=Path, help="JSON file holding one delegate_to_minion args object (same schema as the real tool — see orchestrator/gru/toolcall.py). Omit to read it from stdin.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Working directory the minion operates in (default: current directory)")
    parser.add_argument("--model", default="openrouter/z-ai/glm-4.5-air", help="litellm model string for the minion")
    parser.add_argument("--minion-config", default="general/minion.yaml", help="Minion config under orchestrator/config/. The default is the general-purpose one: real repository, no patch ritual, and forbidden from touching anything it did not create. The benchmark variants (swe_bench/minion.yaml, gaia/minion.yaml) exist to score instances and are not safe against a working tree you care about.")
    parser.add_argument("--cost-limit", type=float, default=0.15, help="Hard dollar cap on this one delegation's agentic session (0 leaves the config's own)")
    parser.add_argument("--summary", action="store_true", help="Print what this session's delegations have cost so far, and exit")
    parser.add_argument("--benchmark-minion-config", action="store_true", help="Permit a --minion-config outside general/. The benchmark configs instruct the minion to revert changes unrelated to its own task, which is correct in a throwaway scoring container and destructive against a working tree you care about. Only the benchmark harness should pass this.")
    parser.add_argument("--allow-dirty", action="store_true", help="Permit a verdict delegation against a working tree with uncommitted changes. Refused by default — a verdict-mode minion is instructed to revert changes unrelated to its own work, which in a shared tree means yours. See this module's docstring.")
    args = parser.parse_args()

    if args.summary:
        print_summary(args.session)
        return

    raw = (args.spec.read_text() if args.spec else sys.stdin.read()).strip()
    if not raw:
        parser.error("no delegation spec given: pass --spec FILE or pipe JSON on stdin")
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as e:
        parser.error(f"--spec is not valid JSON: {e}")

    # The same validation the real tool call goes through, so a spec that would have been
    # rejected from a model is rejected here too — no privileged hand-written path.
    if error := validate_delegation(spec):
        parser.error(error)

    # The benchmark minion configs (swe_bench/, gaia/) ship in the same wheel as the
    # general-purpose one, and their names read as authoritative. They are not safe here:
    # their Submission steps tell the minion to revert anything in the tree unrelated to
    # its own delegation, which in a scoring container is correct and against a real
    # checkout destroyed uncommitted work on the first live run. Reaching one by accident
    # should not be possible.
    if not args.minion_config.startswith("general/") and not args.benchmark_minion_config:
        parser.error(
            f"refusing --minion-config {args.minion_config!r}: only configs under general/ are safe against a "
            "working tree you care about. The benchmark configs (swe_bench/, gaia/) instruct the minion to "
            "revert changes unrelated to its own task — correct when every run gets a throwaway container, "
            "destructive against a real checkout. Pass --benchmark-minion-config only if you are running the "
            "benchmark harness."
        )

    # A verdict-mode minion is told to leave the working tree containing only its own
    # changes, and to revert anything else (config/*/minion.yaml, Submission step 1).
    # That is right in a throwaway container and wrong here, where "anything else" is the
    # operator's uncommitted work. Refuse rather than rely on the snapshot: recovering
    # from a dangling commit is a worse experience than being told to commit first.
    if spec["returns"] == "verdict" and not args.allow_dirty:
        if dirty := uncommitted_paths(args.cwd):
            listed = "\n  ".join(dirty[:10])
            more = f"\n  ... and {len(dirty) - 10} more" if len(dirty) > 10 else ""
            parser.error(
                f"{len(dirty)} uncommitted change(s) in {args.cwd}:\n  {listed}{more}\n\n"
                "A verdict delegation instructs the minion to revert anything in the working tree that "
                "isn't part of its own task — in a shared tree that means your work. Commit or stash "
                "first, or pass --allow-dirty to accept the risk (a recoverable snapshot is taken either way)."
            )

    env = build_environment(
        session=args.session,
        cwd=args.cwd,
        model=args.model,
        cost_limit=args.cost_limit,
        minion_config=args.minion_config,
    )
    next_id = f"t{env.delegation_counter + 1}"
    if snapshot := snapshot_working_tree(args.cwd, args.session, next_id):
        logger.info(
            f"working tree snapshot before {next_id}: {snapshot} — if this delegation reverts "
            f"anything of yours, recover it with: git checkout {snapshot} -- <path>"
        )
    result = env.execute({"kind": "delegate_to_minion", "args": spec})
    (args.session / RECORDS_FILE).write_text(json.dumps(env.minion_records, indent=2))

    print(result["output"])
    if result["returncode"] != 0:
        sys.exit(result["returncode"])


if __name__ == "__main__":
    main()
