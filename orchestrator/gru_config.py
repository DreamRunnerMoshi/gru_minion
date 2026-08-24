"""Loads a Gru agent config from orchestrator/config/, resolving two things a plain
`yaml.safe_load` doesn't know about:

- `agent.system_template_fragments` (a list of names under orchestrator/prompts/gru/),
  composed into the actual `system_template` string via orchestrator.prompt_fragments.
  A config may still use a literal `agent.system_template` block instead (e.g.
  gru-taxonomy.yaml, not yet converted) — that path is untouched.
- `tool_policy` (a dict of ToolPolicy fields), normalized into an actual ToolPolicy.
  Absent entirely, it defaults to the original fully-permissive behavior.

Added 2026-08-24 alongside orchestrator/prompt_fragments.py, for bit-by-bit prompt
experimentation — see orchestrator/config/gru-minimal.yaml for the first variant this
was built for.
"""

from pathlib import Path

import yaml

from orchestrator.gru_toolcall import ToolPolicy
from orchestrator.prompt_fragments import compose

CONFIG_DIR = Path(__file__).parent / "config"


def load_gru_config(filename: str) -> dict:
    """filename is e.g. 'gru.yaml', under orchestrator/config/. Returns the raw dict
    with agent.system_template guaranteed present and top-level 'tool_policy' replaced
    by an actual ToolPolicy instance (not the raw dict)."""
    raw = yaml.safe_load((CONFIG_DIR / filename).read_text())
    agent = raw["agent"]
    if "system_template_fragments" in agent:
        agent["system_template"] = compose(agent.pop("system_template_fragments"))
    raw["tool_policy"] = ToolPolicy.from_dict(raw.get("tool_policy"))
    return raw
