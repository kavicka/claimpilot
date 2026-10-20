"""Structured logging with claim_id and trace_id bound per pipeline step.

`redact_vault_values` drops any string registered as PII during the run, so a value that slipped
into a log call never reaches the log output.
"""

import logging
import sys
from collections import OrderedDict
from typing import Any

import structlog
from structlog.typing import EventDict

# The most recent PII values, oldest first. A long-running process registers one set of values per
# claim it loads; the cap keeps memory flat and the scan short. Values of the claim in hand are
# the youngest, so they are the last to go.
MAX_SECRETS = 5000
PREFIX = 3  # secrets are indexed by their first characters; a scan looks up each position once
_SECRET_VALUES: OrderedDict[str, None] = OrderedDict()
_INDEX: dict[str, set[str]] = {}


def register_secret(value: str) -> None:
    """Called by the PII vault for every value it stores; only values of 3+ characters."""
    if len(value) < PREFIX:
        return
    if value in _SECRET_VALUES:
        _SECRET_VALUES.move_to_end(value)
        return
    _SECRET_VALUES[value] = None
    _INDEX.setdefault(value[:PREFIX], set()).add(value)
    while len(_SECRET_VALUES) > MAX_SECRETS:
        oldest, _ = _SECRET_VALUES.popitem(last=False)
        bucket = _INDEX[oldest[:PREFIX]]
        bucket.discard(oldest)
        if not bucket:
            del _INDEX[oldest[:PREFIX]]


def secret_count() -> int:
    return len(_SECRET_VALUES)


def clear_secrets() -> None:
    _SECRET_VALUES.clear()
    _INDEX.clear()


def _scrub_string(value: str) -> str:
    found: set[str] = set()
    for i in range(len(value) - PREFIX + 1):
        bucket = _INDEX.get(value[i : i + PREFIX])
        if bucket:
            found.update(s for s in bucket if value.startswith(s, i))
    # Longest first, so "Jana Kováčová" goes whole before "Jana" can leave its surname behind.
    for secret in sorted(found, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return value


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub_string(value)
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_scrub(v) for v in value)
    return value


def redact_vault_values(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    if not _SECRET_VALUES:
        return event_dict
    return {k: _scrub(v) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO", *, json: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    renderer: Any = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_vault_values,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=False,
    )
