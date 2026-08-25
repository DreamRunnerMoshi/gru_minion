"""Loads a Gru agent config for GAIA — sibling of orchestrator/gru_config.py, same
fragment-composition mechanism, pointed at orchestrator/prompts/gaia/ and
orchestrator.gaia_tools.GaiaToolPolicy instead of the SWE-bench pair.
"""

from pathlib import Path

import yaml

from orchestrator.gaia_tools import GaiaToolPolicy
from orchestrator.prompt_fragments import PROMPTS_DIR, compose

CONFIG_DIR = Path(__file__).parent / "config"
GAIA_FRAGMENT_DIR = PROMPTS_DIR / "gaia"


def load_gaia_config(filename: str) -> dict:
    raw = yaml.safe_load((CONFIG_DIR / filename).read_text())
    agent = raw["agent"]
    if "system_template_fragments" in agent:
        agent["system_template"] = compose(agent.pop("system_template_fragments"), fragment_dir=GAIA_FRAGMENT_DIR)
    raw["tool_policy"] = GaiaToolPolicy.from_dict(raw.get("tool_policy"))
    return raw
