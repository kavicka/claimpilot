"""Structured logging with claim_id and trace_id bound per pipeline step.

`redact_vault_values` drops any string registered as PII during the run, so a value that slipped
into a log call never reaches the log output.
"""

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict

_SECRET_VALUES: set[str] = set()


def register_secret(value: str) -> None:
    """Called by the PII vault for every value it stores; only values of 3+ characters."""
    if len(value) >= 3:
        _SECRET_VALUES.add(value)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        for secret in _SECRET_VALUES:
            if secret in value:
                value = value.replace(secret, "[REDACTED]")
        return value
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
