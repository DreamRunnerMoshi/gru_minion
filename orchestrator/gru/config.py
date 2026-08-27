"""Loads a Gru agent config from orchestrator/config/, resolving two things a plain
`yaml.safe_load` doesn't know about:

- `agent.system_template_fragments` (a list of names under orchestrator/gru/prompts/),
  composed into the actual `system_template` string via orchestrator.gru.prompts.
  A config may still use a literal `agent.system_template` block instead — that path
  is left untouched, for any config not yet converted to fragments.
- `tool_policy` (a dict of ToolPolicy fields), normalized into an actual ToolPolicy.
  Absent entirely, it defaults to the original fully-permissive behavior.

Added 2026-08-24 alongside orchestrator/gru/prompts.py, so gru.yaml's prompt could
be split into a few topic files instead of one long block.
"""

from orchestrator.configs import load_yaml
from orchestrator.gru.prompts import compose
from orchestrator.gru.toolcall import ToolPolicy


def load_gru_config(filename: str) -> dict:
    """filename is a path under orchestrator/config/, e.g. 'swe_bench/gru.yaml'. Returns the raw dict
    with agent.system_template guaranteed present and top-level 'tool_policy' replaced
    by an actual ToolPolicy instance (not the raw dict)."""
    raw = load_yaml(filename)
    agent = raw["agent"]
    if "system_template_fragments" in agent:
        agent["system_template"] = compose(agent.pop("system_template_fragments"))
    raw["tool_policy"] = ToolPolicy.from_dict(raw.get("tool_policy"))
    return raw
