"""Starting data for a new client, contributed by each app (a registry, so provisioning never
imports business apps).

    # apps/policies/apps.py
    def ready(self):
        from apps.core.seeding import register_seed
        register_seed("policies.insurance", seed_insurance_rates, after=("org.branches",))

Seeds run inside the new client's `tenant_context`, in its language, in registration order
adjusted so each one runs after the seeds it names in `after`. A seed receives the
provisioning values it may need as keyword arguments (`country`, `currency`…) and ignores the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Seed:
    key: str
    run: Callable[..., None]
    after: tuple[str, ...] = ()


_seeds: dict[str, Seed] = {}


def register_seed(key: str, run: Callable[..., None], *, after: tuple[str, ...] = ()) -> None:
    if key in _seeds:
        raise ValueError(f"Seed {key} registered twice")
    _seeds[key] = Seed(key, run, after)


def ordered_seeds() -> list[Seed]:
    """Every seed, each after the ones it names (unknown names are ignored)."""
    done: dict[str, Seed] = {}

    def visit(seed: Seed, path: tuple[str, ...]) -> None:
        if seed.key in done:
            return
        if seed.key in path:
            raise ValueError(f"Seeds depend on each other in a cycle: {' → '.join(path)}")
        for name in seed.after:
            if name in _seeds:
                visit(_seeds[name], (*path, seed.key))
        done[seed.key] = seed

    for seed in _seeds.values():
        visit(seed, ())
    return list(done.values())


def run_seeds(**values) -> None:
    """Run every seed. Must be called inside the new client's tenant_context."""
    for seed in ordered_seeds():
        seed.run(**values)
