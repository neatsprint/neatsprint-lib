"""UUIDv7 helpers.

Every primary key in NeatSprint is a time-ordered UUIDv7. Client-generated ids are
used as idempotency keys for offline-capable entities (ADR-004).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from uuid6 import uuid7


def new_id() -> UUID:
    """Return a new UUIDv7."""
    return uuid7()


def parse_id(value: str | UUID) -> UUID:
    """Parse a string into a UUID, raising ValueError on malformed input."""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def is_uuid7(value: str | UUID) -> bool:
    """Return True when the value is a version-7 UUID.

    Python's ``UUID.version`` returns 7 for v7 values. This is used by tests and
    by validators that must reject v4 ids on offline-capable endpoints.
    """
    try:
        return parse_id(value).version == 7
    except (ValueError, AttributeError, TypeError):
        return False


def coerce_id(value: Any) -> UUID:
    """Coerce a request value to UUID, raising ValueError when impossible."""
    return parse_id(value)
