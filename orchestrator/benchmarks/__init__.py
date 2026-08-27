"""Registry: benchmark name -> the Benchmark subclass that implements it.

`loader` in orchestrator/config/<benchmark>/benchmark.yaml picks the entry, so pointing
the orchestrator at a different dataset is a config change, not a code change — and
adding a third benchmark means adding a module here plus its config directory, with
nothing in orchestrator/run_session.py to touch.

Imports are deferred: each loader pulls in its own dataset machinery (`datasets`,
mini-swe-agent's SWE-bench harness), and a GAIA run has no reason to pay for SWE-bench's.
"""

from importlib import import_module

from orchestrator.benchmarks.base import Benchmark, BenchmarkSpec, Outcome, Task

__all__ = ["Benchmark", "BenchmarkSpec", "Outcome", "Task", "LOADERS", "get_benchmark"]

# loader name -> "module:class"
LOADERS = {
    "swe_bench": "orchestrator.benchmarks.swebench:SWEBenchBenchmark",
    "gaia": "orchestrator.benchmarks.gaia:GaiaBenchmark",
}


def get_benchmark(name: str) -> Benchmark:
    """`name` is a benchmark's config directory, optionally with a variant after a slash:
    "gaia" -> config/gaia/benchmark.yaml's defaults, "gaia/solo" -> those defaults with
    its `variants.solo` block merged over them."""
    spec = BenchmarkSpec.load(name)
    if spec.loader not in LOADERS:
        raise SystemExit(f"unknown benchmark loader {spec.loader!r} — known: {', '.join(sorted(LOADERS))}")
    module_name, _, class_name = LOADERS[spec.loader].partition(":")
    return getattr(import_module(module_name), class_name)(spec)
