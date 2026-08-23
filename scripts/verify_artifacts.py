#!/usr/bin/env python3
"""Completeness gate. Exit 0 only if every artifact exp3 needs is actually present.

Run this before `vastai destroy`, every time, no exceptions. exp2 destroyed its
instances with 4 of 5 trajectory sets unpulled; that data cannot be regenerated, and
for exp3 the trajectories are the measurement rather than a debugging aid.
"""

import json
import sys
from pathlib import Path

EXPECTED = {"astropy-12907", "astropy-14182", "astropy-14365", "astropy-14995", "astropy-6938"}


def check(root: Path) -> int:
    problems: list[str] = []
    found = {d.name for d in root.iterdir() if d.is_dir()}
    for missing in sorted(EXPECTED - found):
        problems.append(f"{missing}: no results directory at all")

    for name in sorted(found & EXPECTED):
        d = root / name
        for required in ("cost_summary.json", "prediction.json", "gru.traj.json"):
            if not (d / required).exists():
                problems.append(f"{name}: missing {required}")
        cs = d / "cost_summary.json"
        if not cs.exists():
            continue
        s = json.loads(cs.read_text())
        if not (s.get("gru", {}).get("cache")):
            problems.append(f"{name}: no per-role cache stats (review.md R12) — old harness?")
        if s.get("gru_action_log") is None:
            problems.append(f"{name}: no gru_action_log — think/run_check turns unmeasurable")
        for m in s.get("minions", []):
            did = m["delegation_id"]
            op = m.get("output_path")
            if not op or not Path(op).exists():
                problems.append(f"{name}/{did}: delegation output missing — coverage unscoreable")
            if m.get("mode") == "agentic":
                tp = m.get("trajectory_path")
                if not tp or not Path(tp).exists():
                    problems.append(f"{name}/{did}: agentic trajectory missing")
        patch = json.loads((d / "prediction.json").read_text()) if (d / "prediction.json").exists() else {}
        for v in patch.values():
            if not (v.get("model_patch") or "").strip():
                problems.append(f"{name}: EMPTY PATCH — will score as unresolved")

    if problems:
        print(f"NOT SAFE TO DESTROY — {len(problems)} problem(s):\n")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print(f"All artifacts present for {len(found & EXPECTED)}/{len(EXPECTED)} instances under {root}.")
    print("Safe to destroy the instances.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: verify_artifacts.py <experiments/exp3/results/ARM>")
    sys.exit(check(Path(sys.argv[1])))
