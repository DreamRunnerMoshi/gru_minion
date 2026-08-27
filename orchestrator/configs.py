"""One place that knows where orchestrator/config/ is, and how to read a plain YAML
config out of it.

Both run entrypoints and both test harnesses used to carry their own
`CONFIG_DIR = Path(...) / "config"` plus a two-line `load_yaml`. Gru's own config
needs more than that (fragment composition, tool policy — see gru/config.py); the
session and minion configs are plain YAML and just need loading.
"""

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).parent / "config"


def load_yaml(name: str) -> dict:
    """`name` is a path relative to orchestrator/config/, which groups config by
    benchmark: 'swe_bench/minion.yaml', 'gaia/benchmark.yaml'."""
    return yaml.safe_load((CONFIG_DIR / name).read_text())
