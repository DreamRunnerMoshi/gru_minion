"""Assemble one exp3 arm's results: merge predictions, score coverage, emit the table.

Run on the harness VM (needs `datasets` for the gold patches) or anywhere the dataset
is reachable. Produces predictions_<arm>.json for the SWE-bench harness plus a
coverage report and a ready-to-paste LOG.md Results table.

The gold patch is used only here, after the run — never at inference time.
"""

import argparse
import json
from pathlib import Path

from orchestrator.metrics.coverage import score_run

DATASET = "SWE-bench/SWE-bench_Lite"


def load_gold(instance_ids: list[str], split: str) -> dict[str, str]:
    from datasets import load_dataset

    ds = load_dataset(DATASET, split=split)
    return {r["instance_id"]: r["patch"] for r in ds if r["instance_id"] in set(instance_ids)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-dir", required=True, type=Path, help="e.g. experiments/exp3/results/B")
    ap.add_argument("--split", default="test")
    ap.add_argument("--eval-report", type=Path, help="run_evaluation report json, if already produced")
    args = ap.parse_args()

    dirs = sorted(d for d in args.results_dir.iterdir() if d.is_dir() and (d / "cost_summary.json").exists())
    if not dirs:
        raise SystemExit(f"no completed instance dirs under {args.results_dir}")

    summaries = {d.name: json.loads((d / "cost_summary.json").read_text()) for d in dirs}
    instance_ids = [s["instance_id"] for s in summaries.values()]

    # 1. merged predictions for the SWE-bench harness
    preds = {}
    for d in dirs:
        pf = d / "prediction.json"
        if pf.exists():
            preds.update(json.loads(pf.read_text()))
    out_preds = args.results_dir / f"predictions_{args.results_dir.name}.json"
    out_preds.write_text(json.dumps(preds, indent=2))

    # 2. localization coverage
    gold = load_gold(instance_ids, args.split)
    coverage = {}
    for d in dirs:
        iid = summaries[d.name]["instance_id"]
        if iid in gold:
            coverage[d.name] = score_run(d, gold[iid])
    (args.results_dir / "coverage.json").write_text(json.dumps(coverage, indent=2))

    # 3. resolved verdicts, only if a real harness report is supplied — never inferred
    resolved: dict[str, str] = {}
    if args.eval_report and args.eval_report.exists():
        rep = json.loads(args.eval_report.read_text())
        for d in dirs:
            iid = summaries[d.name]["instance_id"]
            resolved[d.name] = "✅" if iid in rep.get("resolved_ids", []) else "❌"

    # 4. the LOG.md Results table
    hdr = ("| Instance | Resolved | Gru turns | think | run_check | Delegations | oneshot | "
           "Gru tok | Minion tok | Est. cache-hit% | Cov (files) | Cov (symbols) | First hit | Wall-clock |")
    rows = [hdr, "|" + "---|" * 14]
    tot = dict(gru_turns=0, think=0, run_check=0, dels=0, oneshot=0, gru_tok=0, min_tok=0, wall=0.0)
    for d in dirs:
        s = summaries[d.name]
        acts = [a["kind"] for a in (s.get("gru_action_log") or [])]
        mins = s.get("minions", [])
        cov = coverage.get(d.name, {})
        cache = (s.get("cache_totals") or {}).get("estimated_cache_hit_pct")
        tot["gru_turns"] += s["gru"]["api_calls"]; tot["think"] += acts.count("think")
        tot["run_check"] += acts.count("run_check"); tot["dels"] += len(mins)
        tot["oneshot"] += sum(1 for m in mins if m.get("mode") == "oneshot")
        tot["gru_tok"] += s["gru"]["total_tokens"]
        tot["min_tok"] += sum(m["total_tokens"] for m in mins); tot["wall"] += s["wall_clock_seconds"]
        rows.append(
            f"| {d.name} | {resolved.get(d.name,'—')} | {s['gru']['api_calls']} | {acts.count('think')} | "
            f"{acts.count('run_check')} | {len(mins)} | {sum(1 for m in mins if m.get('mode')=='oneshot')} | "
            f"{s['gru']['total_tokens']:,} | {sum(m['total_tokens'] for m in mins):,} | "
            f"{cache if cache is not None else '—'} | "
            f"{cov.get('combined_source_files_named','—')}/{cov.get('combined_source_files_total','—')} | "
            f"{cov.get('combined_source_symbol_coverage','—')} | {cov.get('first_hit_delegation','—')} | "
            f"{s['wall_clock_seconds']:.0f}s |")
    n_res = sum(1 for v in resolved.values() if v == "✅") if resolved else None
    rows.append(
        f"| **Total** | {f'{n_res}/{len(dirs)}' if resolved else '—'} | {tot['gru_turns']} | {tot['think']} | "
        f"{tot['run_check']} | {tot['dels']} | {tot['oneshot']} | {tot['gru_tok']:,} | {tot['min_tok']:,} | | | | | "
        f"~{tot['wall']/60:.0f}m |")
    table = "\n".join(rows)
    (args.results_dir / "results_table.md").write_text(table + "\n")

    print(table)
    print(f"\nwrote: {out_preds.name}, coverage.json, results_table.md")
    if not resolved:
        print("NOTE: Resolved column is empty — pass --eval-report from run_evaluation. "
              "Never fill it by hand (exp2 did; see review.md R3).")


if __name__ == "__main__":
    main()
