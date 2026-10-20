"""The log scrubber keeps a bounded set of recent PII values and scans each string cheaply."""

import time
import tracemalloc

import pytest

from claimpilot_core import logging as cp_logging
from claimpilot_core.logging import redact_vault_values, register_secret


@pytest.fixture(autouse=True)
def clean_secrets():
    cp_logging.clear_secrets()
    yield
    cp_logging.clear_secrets()


def scrub(text: str) -> str:
    return redact_vault_values(None, "info", {"event": text})["event"]


def test_registered_value_is_redacted_in_nested_structures():
    register_secret("Zuzana Testovacia")
    out = redact_vault_values(
        None, "info", {"event": "x", "who": ["a Zuzana Testovacia b", {"k": "Zuzana Testovacia"}]}
    )
    assert out["who"] == ["a [REDACTED] b", {"k": "[REDACTED]"}]


def test_longer_secret_wins_over_its_prefix():
    register_secret("Jana")
    register_secret("Jana Kováčová")
    assert scrub("client Jana Kováčová called") == "client [REDACTED] called"


def test_short_values_are_not_registered():
    register_secret("ab")
    assert cp_logging.secret_count() == 0


def test_cap_evicts_the_oldest_and_keeps_the_recent(monkeypatch):
    monkeypatch.setattr(cp_logging, "MAX_SECRETS", 100)
    for i in range(250):
        register_secret(f"secret-value-{i:04d}")
    assert cp_logging.secret_count() == 100
    assert scrub("secret-value-0249") == "[REDACTED]"
    assert scrub("secret-value-0150") == "[REDACTED]"
    assert scrub("secret-value-0000") == "secret-value-0000"  # evicted


def test_reregistering_keeps_a_value_young(monkeypatch):
    monkeypatch.setattr(cp_logging, "MAX_SECRETS", 10)
    register_secret("keep-me-please")
    for i in range(9):
        register_secret(f"filler-{i:04d}")
    register_secret("keep-me-please")  # used again: now the youngest
    register_secret("one-more-value")
    assert scrub("keep-me-please") == "[REDACTED]"
    assert scrub("filler-0000") == "filler-0000"


def test_flood_of_registrations_is_bounded_in_memory_and_log_time():
    tracemalloc.start()
    start = tracemalloc.take_snapshot()
    for i in range(100_000):
        register_secret(f"person-{i:07d}-name")
    current, _peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del start
    assert cp_logging.secret_count() <= cp_logging.MAX_SECRETS
    assert current < 20 * 1024 * 1024  # a few MB, not 100k values' worth

    recent = "person-0099999-name"
    line = "step.ok " + "lorem ipsum dolor sit amet " * 40 + recent
    began = time.perf_counter()
    for _ in range(50):
        out = scrub(line)
    per_call = (time.perf_counter() - began) / 50
    assert recent not in out
    assert per_call < 0.01  # 10 ms for a 1 KB line, whatever was registered before
