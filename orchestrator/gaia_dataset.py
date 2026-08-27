"""Loads GAIA (huggingface.co/datasets/gaia-benchmark/GAIA) and picks the pilot set.

GAIA is a gated HF dataset — needs an HF_TOKEN with approved access (a manual HF-side
review, not something this script can do). See experiments/exp6/NOTES.md.

There's no "long horizon" split in the standard release. Approximated here by filtering
to Level 2/3 (GAIA's own harder, more multi-step tiers) and excluding any instance with
an attached file — the exp6 pilot's tool budget is web search + code execution only, no
file/image/audio parsing, so an instance requiring a file is unanswerable by construction,
not a fair test of the architecture.
"""

import os

from datasets import load_dataset

DATASET = "gaia-benchmark/GAIA"
CONFIG = "2023_all"


def load_gaia(split: str = "validation", token: str | None = None):
    token = token or os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set — GAIA is gated, need an approved-access token in the environment")
    return load_dataset(DATASET, CONFIG, split=split, token=token)


def filter_no_file_multi_step(ds, levels: tuple[str, ...] = ("2", "3")):
    """Instances answerable with search + code execution alone: no attached file, Level
    2 or 3 (GAIA's harder, more multi-step tiers — the closest proxy this release has
    for "long horizon")."""
    return [r for r in ds if not r["file_name"] and r["Level"] in levels]


def pick_pilot(ds, n: int = 5, levels: tuple[str, ...] = ("2", "3"), seed: int = 0):
    """Deterministic pilot selection — same n instances every time this is called with
    the same seed, so re-running the pilot script doesn't silently drift to a different
    sample."""
    import random

    candidates = filter_no_file_multi_step(ds, levels)
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:n]


if __name__ == "__main__":
    ds = load_gaia()
    pilot = pick_pilot(ds)
    for r in pilot:
        print(f"{r['task_id']}  L{r['Level']}  {r['Question'][:100]!r}  -> {r['Final answer']!r}")
