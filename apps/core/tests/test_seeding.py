"""The seeding registry: each app's starting data for a new client, in dependency order."""

import pytest

from apps.core import seeding


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(seeding, "_seeds", {})


def test_seeds_run_after_the_ones_they_name(registry):
    ran = []
    seeding.register_seed("policies", lambda **_: ran.append("policies"), after=("org",))
    seeding.register_seed("org", lambda **_: ran.append("org"))
    seeding.register_seed("leave", lambda **_: ran.append("leave"),
                          after=("policies", "not-installed"))
    seeding.run_seeds(country="EG")
    assert ran == ["org", "policies", "leave"]


def test_seeds_receive_the_provisioning_values(registry):
    seen = {}
    seeding.register_seed("tax", lambda *, country, **_: seen.update(country=country))
    seeding.run_seeds(country="EG", currency="EGP")
    assert seen == {"country": "EG"}


def test_a_seed_is_registered_once_and_cycles_are_refused(registry):
    seeding.register_seed("a", lambda **_: None, after=("b",))
    with pytest.raises(ValueError):
        seeding.register_seed("a", lambda **_: None)
    seeding.register_seed("b", lambda **_: None, after=("a",))
    with pytest.raises(ValueError, match="cycle"):
        seeding.ordered_seeds()
