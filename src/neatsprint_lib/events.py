"""Transactional outbox and Redis Streams relay (ADR-009).

Producers call :func:`enqueue` in the same transaction as the state change. A relay
loop publishes unpublished rows at-least-once; consumers must be idempotent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from neatsprint_lib.db import Base
from neatsprint_lib.ids import new_id

logger = logging.getLogger(__name__)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=new_id
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(tz=UTC)
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


def enqueue(
    session: AsyncSession,
    *,
    event_type: str,
    tenant_id: uuid.UUID | None,
    payload: dict[str, Any],
    actor_id: uuid.UUID | None = None,
    event_version: int = 1,
) -> OutboxEvent:
    event = OutboxEvent(
        tenant_id=tenant_id,
        actor_id=actor_id,
        event_type=event_type,
        event_version=event_version,
        payload=payload,
    )
    session.add(event)
    return event


def to_message(event: OutboxEvent) -> dict[str, str]:
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "event_version": str(event.event_version),
        "tenant_id": str(event.tenant_id) if event.tenant_id else "",
        "actor_id": str(event.actor_id) if event.actor_id else "",
        "occurred_at": event.occurred_at.isoformat(),
        "data": json.dumps(event.payload, default=str),
    }


async def relay_once(
    session: AsyncSession, redis: Redis, stream: str, *, limit: int = 100
) -> int:
    """Publish up to ``limit`` unpublished events. Returns the number published."""
    result = await session.execute(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.occurred_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    events = list(result.scalars().all())
    if not events:
        return 0

    published = 0
    for event in events:
        try:
            await redis.xadd(stream, to_message(event), maxlen=100_000, approximate=True)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 - retried on the next pass
            event.attempts += 1
            event.last_error = str(exc)[:500]
            logger.warning("outbox_publish_failed", extra={"event_id": str(event.id)})
            continue
        event.published_at = datetime.now(tz=UTC)
        event.attempts += 1
        event.last_error = None
        published += 1

    await session.commit()
    return published


async def run_relay(
    session_factory: async_sessionmaker[AsyncSession],
    redis_url: str,
    stream: str,
    stop: asyncio.Event,
    *,
    interval_seconds: float = 2.0,
) -> None:
    """Background loop used by services in development and single-node deployments."""
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        while not stop.is_set():
            try:
                async with session_factory() as session:
                    await relay_once(session, redis, stream)
            except Exception:  # noqa: BLE001 - the relay must survive transient failures
                logger.exception("outbox_relay_error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
    finally:
        await redis.aclose()
