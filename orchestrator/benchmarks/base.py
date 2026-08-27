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
orchestrator/config/<benchmark>/benchmark.yaml — see BenchmarkSpec.load() below and
orchestrator/benchmarks/__init__.py's registry.
"""

from dataclasses import dataclass, field
from typing import Any

from orchestrator.configs import CONFIG_DIR, load_yaml
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
    """A loaded orchestrator/config/<benchmark>/benchmark.yaml — one spec per benchmark,
    sitting alongside the configs it names. Config is grouped by benchmark (everything a
    GAIA run needs lives in orchestrator/config/gaia/), so a spec names its siblings by
    bare filename and this class resolves them against its own directory. `dataset` is
    passed through to the benchmark as-is: its shape is the loader's own business
    (SWE-bench wants a subset and split, GAIA only a split).

    `name` is what --benchmark was given: a bare benchmark ("gaia", the file's own
    defaults) or a named variant after a slash ("gaia/solo", those defaults with the
    spec's `variants.solo` block merged over them). A variant states only what it
    changes, so the dataset and container are declared once per benchmark and can't
    drift between arms of the same comparison — which they could when each arm was a
    separate spec file repeating them."""

    name: str
    benchmark: str  # the config directory: "gaia" for both "gaia" and "gaia/solo"
    loader: str
    dataset: dict[str, Any] = field(default_factory=dict)
    environment: str = "environment.yaml"
    gru: str = "gru.yaml"
    minion: str = "minion.yaml"

    @classmethod
    def load(cls, name: str) -> "BenchmarkSpec":
        benchmark, _, variant = name.partition("/")
        path = CONFIG_DIR / benchmark / "benchmark.yaml"
        if not path.exists():
            known = sorted(d.name for d in CONFIG_DIR.iterdir() if (d / "benchmark.yaml").exists())
            raise SystemExit(f"no benchmark config at {path} — known benchmarks: {', '.join(known)}")
        raw = load_yaml(f"{benchmark}/benchmark.yaml")["benchmark"]
        variants = raw.pop("variants", None) or {}
        if variant:
            if variant not in variants:
                raise SystemExit(
                    f"benchmark {benchmark!r} has no variant {variant!r} — "
                    f"known: {', '.join(sorted(variants)) or '(none)'}"
                )
            overrides = variants[variant]
            # `dataset` merges key-by-key so a variant can change just the split without
            # having to restate the subset; everything else is a plain override.
            raw = {**raw, **overrides, "dataset": {**raw.get("dataset", {}), **overrides.get("dataset", {})}}
        spec = cls(name=name, benchmark=benchmark, **raw)
        # Sibling filenames -> paths under orchestrator/config/, so every caller can hand
        # them straight to load_yaml/load_gru_config.
        spec.environment = f"{benchmark}/{spec.environment}"
        spec.gru = f"{benchmark}/{spec.gru}"
        spec.minion = f"{benchmark}/{spec.minion}"
        return spec


class Benchmark:
    """Subclass per dataset; see swebench.py and gaia.py. A subclass supplies an
    `environment_class` (a GruEnvironment subclass) and implements the three methods
    below — it must not touch how Gru's loop, prompts or delegations work."""

    environment_class: type[GruEnvironment] = GruEnvironment

    def __init__(self, spec: BenchmarkSpec):
        self.spec = spec
        self.environment_config = load_yaml(spec.environment)

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
        """Start the one shared container the whole session runs against, configured by
        the spec's `environment` file. The returned object must have DockerEnvironment's
        `execute()`/`cleanup()` shape."""
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
