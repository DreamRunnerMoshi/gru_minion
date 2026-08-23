"""Localization coverage: did the delegations actually surface the code the fix needed?

Why this exists. Resolve/not-resolve is one bit per instance, which is why a 5-instance
run has no statistical power (review.md R4: exp2 vs exp1 differ on one instance, Fisher
p=1.0). Delegations are the better unit of analysis — exp2 produced 29 of them — and
localization coverage is measurable per delegation, continuous, and computed post-hoc
against the gold patch the SWE-bench instance already ships.

It also tests review.md R2 directly rather than by citation. If coverage is high while
resolve rate is low, localization is not the bottleneck and the ORACLE-SWE reading this
project inherited is wrong for this task set. If coverage is low on exactly the failing
instances, it is right.

AI21 report the same metric for their own pipeline (~90% of gold-patch removed lines,
~71% of added lines covered before frontier generation) — so this is directly comparable
to published numbers, not a bespoke score.

**Post-hoc only.** The gold patch is not available at inference time; nothing here is
visible to Gru or a minion.
"""

import json
import re
from pathlib import Path
from typing import Any

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")

# Identifiers too generic to count as evidence that the right code was found.
_STOP = {
    "self", "return", "import", "from", "None", "True", "False", "class", "def",
    "else", "elif", "with", "assert", "raise", "print", "value", "values", "data",
    "test", "tests", "result", "results", "name", "type", "list", "dict", "args",
    "kwargs", "index", "shape", "array", "np", "numpy", "for", "while", "not", "and",
    "the", "this", "that", "file", "line", "lines", "output", "input", "format",
}


def parse_gold_patch(patch: str) -> dict[str, dict[str, Any]]:
    """gold patch -> {file: {removed_lines, added_lines, symbols}}. Test files are kept
    but flagged: an agent touching them is a different signal from finding source."""
    files: dict[str, dict[str, Any]] = {}
    current = None
    old_ln = new_ln = 0
    for line in patch.splitlines():
        m = _FILE.match(line)
        if m:
            current = m.group(2)
            files[current] = {"removed_lines": set(), "added_lines": set(), "symbols": set(),
                             "is_test": "test" in current.lower()}
            continue
        if current is None:
            continue
        h = _HUNK.match(line)
        if h:
            old_ln, new_ln = int(h.group(1)), int(h.group(3))
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            files[current]["removed_lines"].add(old_ln)
            files[current]["symbols"].update(_IDENT.findall(line[1:]))
            old_ln += 1
        elif line.startswith("+"):
            files[current]["added_lines"].add(new_ln)
            files[current]["symbols"].update(_IDENT.findall(line[1:]))
            new_ln += 1
        else:
            old_ln += 1
            new_ln += 1
    for f in files.values():
        f["symbols"] = {s for s in f["symbols"] if s not in _STOP}
    return files


def score_text(text: str, gold: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """How much of the gold patch's surface does one delegation's output name?"""
    per_file = {}
    for path, info in gold.items():
        basename = Path(path).name
        file_hit = path in text or basename in text
        symbols = info["symbols"]
        hit_syms = {s for s in symbols if re.search(rf"\b{re.escape(s)}\b", text)}
        per_file[path] = {
            "is_test": info["is_test"],
            "file_named": file_hit,
            "symbols_total": len(symbols),
            "symbols_named": len(hit_syms),
            "symbol_coverage": round(len(hit_syms) / len(symbols), 3) if symbols else None,
        }
    source = {p: v for p, v in per_file.items() if not v["is_test"]}
    return {
        "per_file": per_file,
        "source_files_named": sum(1 for v in source.values() if v["file_named"]),
        "source_files_total": len(source),
        "source_symbol_coverage": round(
            sum(v["symbols_named"] for v in source.values())
            / max(1, sum(v["symbols_total"] for v in source.values())), 3),
    }


def score_run(result_dir: Path, gold_patch: str) -> dict[str, Any]:
    """Score every delegation in one instance's result directory, in order.

    `first_hit_delegation` is the interesting one: how many delegations it took before
    the gold-patch source file was named at all. A run that finds it on t1 and a run
    that finds it on t6 can have identical final coverage and very different cost.
    """
    gold = parse_gold_patch(gold_patch)
    summary = json.loads((result_dir / "cost_summary.json").read_text())
    delegations, cumulative, first_hit = [], "", None
    for rec in summary.get("minions", []):
        path = rec.get("output_path")
        text = Path(path).read_text() if path and Path(path).exists() else ""
        s = score_text(text, gold)
        cumulative += "\n" + text
        if first_hit is None and s["source_files_named"] > 0:
            first_hit = rec["delegation_id"]
        delegations.append({
            "delegation_id": rec["delegation_id"],
            "returns": rec.get("returns"), "mode": rec.get("mode"),
            "total_tokens": rec.get("total_tokens", 0),
            "output_chars": len(text),
            **{k: v for k, v in s.items() if k != "per_file"},
        })
    combined = score_text(cumulative, gold)
    total_tokens = sum(d["total_tokens"] for d in delegations)
    return {
        "instance_id": summary.get("instance_id"),
        "gold_source_files": [p for p, v in gold.items() if not v["is_test"]],
        "gold_test_files": [p for p, v in gold.items() if v["is_test"]],
        "first_hit_delegation": first_hit,
        "n_delegations": len(delegations),
        "combined_source_files_named": combined["source_files_named"],
        "combined_source_files_total": combined["source_files_total"],
        "combined_source_symbol_coverage": combined["source_symbol_coverage"],
        # the cost-efficiency number: coverage bought per million delegation tokens
        "symbol_coverage_per_mtok": round(
            combined["source_symbol_coverage"] / (total_tokens / 1e6), 2) if total_tokens else None,
        "delegation_tokens": total_tokens,
        "per_delegation": delegations,
    }
