"""The benchmark interface: everything that changes when the Gru/minion architecture is
pointed at a different dataset, and nothing that doesn't.

Added 2026-08-26. Before this, SWE-bench and GAIA each had their own run script and their
own environment class, ~90% of both being the same code — the second benchmark was added
by copying the first. That made "one architecture, one prompt, only the benchmark
underneath changes" (the project's own stated invariant) something maintained by hand
rather than by construction. Now `orchestrator/run_session.py` is benchmark-agnostic and
a benchmark is four things:

1. **A dataset loader** — `load_task()`, turning an instance id into the record plus the
   prompt variables Gru's instance_template expects.
2. **A shell environment** — `open_environment()`, the one shared container a whole
   session runs against (SWE-bench: the instance's testbed image; GAIA: a network-enabled
   sandbox).
3. **A submission** — the `GruEnvironment` subclass whose `build_submission()` says what
   a passing `finish()` actually hands in (SWE-bench: a git diff; GAIA: an answer string).
4. **A verdict** — `finalize()`, producing prediction.json's payload and the
   benchmark-specific half of cost_summary.json.

Which benchmark runs, and which config files it uses, comes from
orchestrator/config/benchmarks/<name>.yaml — see load_spec() below and
orchestrator/benchmarks/__init__.py's registry.
"""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.configs import load_yaml
from orchestrator.gru.environment import GruEnvironment


@dataclass
class Task:
    """One benchmark instance, resolved into the two things the session needs: an id to
    key results by, and the template variables Gru's instance_template renders with."""

    instance_id: str
    prompt_vars: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    """What a finished session is worth. `prediction` is written verbatim into
    prediction.json under the instance id; `summary_fields` is merged into
    cost_summary.json alongside the shared cost/token/cache accounting."""

    submission: str
    prediction: dict[str, Any]
    summary_fields: dict[str, Any] = field(default_factory=dict)
    log_line: str = ""


@dataclass
class BenchmarkSpec:
    """A loaded orchestrator/config/benchmarks/<name>.yaml. `dataset` is passed through
    to the benchmark as-is — its shape is the loader's own business (SWE-bench wants a
    subset and split, GAIA only a split)."""

    name: str
    loader: str
    dataset: dict[str, Any] = field(default_factory=dict)
    session_config: str = "session.yaml"
    gru_config: str = "gru.yaml"
    minion_config: str = "minion.yaml"

    @classmethod
    def load(cls, name: str) -> "BenchmarkSpec":
        raw = load_yaml(f"benchmarks/{name}.yaml")["benchmark"]
        return cls(name=name, **raw)


class Benchmark:
    """Subclass per dataset; see swebench.py and gaia.py. A subclass supplies an
    `environment_class` (a GruEnvironment subclass) and implements the three methods
    below — it must not touch how Gru's loop, prompts or delegations work."""

    environment_class: type[GruEnvironment] = GruEnvironment

    def __init__(self, spec: BenchmarkSpec):
        self.spec = spec
        self.session_config = load_yaml(spec.session_config)

    @property
    def name(self) -> str:
        return self.spec.name

    # -- 1. dataset --

    def load_task(self, instance_id: str, **overrides) -> Task:
        """Resolve one instance id against the dataset named in the spec. `overrides` are
        the CLI's own dataset overrides (e.g. --split), applied over spec.dataset."""
        raise NotImplementedError

    # -- 2. shell environment --

    def open_environment(self, task: Task) -> Any:
        """Start the one shared container the whole session runs against. The returned
        object must have DockerEnvironment's `execute()`/`cleanup()` shape."""
        raise NotImplementedError

    # -- 3. Gru's environment (shared; the subclass only varies build_submission) --

    def make_gru_environment(self, **kwargs) -> GruEnvironment:
        return self.environment_class(**kwargs)

    # -- 4. verdict --

    def finalize(self, *, task: Task, result: dict, env: GruEnvironment, model_name: str) -> Outcome:
        """Turn the raw session result into a submission and a prediction record. Called
        whether or not the session ended cleanly — a benchmark that can recover a
        submission from the environment after a crash (SWE-bench reads the testbed's
        working tree) does that here."""
        raise NotImplementedError
