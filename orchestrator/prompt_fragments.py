"""Composes Gru's system_template from small, reusable fragments under
orchestrator/prompts/gru/, instead of one long hand-written string per config.

Added 2026-08-24 to support bit-by-bit prompt experimentation: the previous design had
each variant (gru.yaml, gru-taxonomy.yaml) embed its own complete system_template, so
trying a new combination (e.g. "just delegation, no verification, no failure handling")
meant either hand-editing a copy of the full text or duplicating shared paragraphs
across files. A config now lists which fragments it wants — orchestrator/config/gru.yaml
still renders to the same prompt it always did, just built from parts instead of typed
once as a block; orchestrator/config/gru-minimal.yaml renders a much shorter prompt from
a subset of the same parts, sharing role.md and one delegation_shape variant with it.

See orchestrator/prompts/gru/ for the fragments themselves and orchestrator/gru_config.py
for how a config's fragment list turns into the agent's actual system_template.
"""

from pathlib import Path

FRAGMENT_DIR = Path(__file__).parent / "prompts" / "gru"


def compose(fragment_names: list[str]) -> str:
    parts = [(FRAGMENT_DIR / f"{name}.md").read_text().strip() for name in fragment_names]
    return "\n\n".join(parts) + "\n"
