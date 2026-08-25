"""Composes Gru's system_template from a handful of fragments under
orchestrator/prompts/gru/, instead of one long hand-written string in the config
itself. orchestrator/config/gru.yaml lists which fragments it wants and renders to the
same prompt it always did, just built from a few parts instead of typed as one block —
editing the prompt means editing one topic's file, not hunting through a monolith.

See orchestrator/prompts/gru/ for the fragments themselves and orchestrator/gru_config.py
for how a config's fragment list turns into the agent's actual system_template.
"""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
FRAGMENT_DIR = PROMPTS_DIR / "gru"


def compose(fragment_names: list[str], fragment_dir: Path = FRAGMENT_DIR) -> str:
    """fragment_dir defaults to prompts/gru/ (SWE-bench Gru) — pass prompts/gaia/ for
    the GAIA sibling (see orchestrator/gaia_config.py)."""
    parts = [(fragment_dir / f"{name}.md").read_text().strip() for name in fragment_names]
    return "\n\n".join(parts) + "\n"
