"""Async SQLAlchemy primitives and the tenant-scoping contract.

Every tenant-owned table inherits ``TenantMixin``. Repositories must always filter by
``tenant_id``; ``TenantScopedRepository`` makes that the default path.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, MetaData, event, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import Session as SASession

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)


class TenantMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    if not database_url:
        raise ValueError("database_url is required")
    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency returning a request-scoped session from app state."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


async def get_tenant_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Session bound to the caller's tenant for PostgreSQL RLS.

    Every transaction started on this session sets ``app.tenant_id``; policies on
    tenant-owned tables compare it with ``tenant_id`` and return no rows otherwise.
    """
    from neatsprint_lib.auth import get_principal

    principal = await get_principal(request)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        session.info["tenant_id"] = str(principal.tenant_id)
        yield session


def bind_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind a session used outside a user request (internal service calls)."""
    session.info["tenant_id"] = str(tenant_id)


@event.listens_for(SASession, "after_begin")
def _apply_tenant_setting(session: SASession, transaction: object, connection: object) -> None:
    tenant_id = session.info.get("tenant_id")
    if tenant_id:
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )


async def check_database(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness must never raise
        return False


class TenantScopedRepository[ModelT: Base]:
    """Minimal repository that makes the tenant filter unavoidable.

    Subclasses set ``model``. ``tenant_id`` is required at construction time so an
    unscoped query cannot be written by accident.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id

    def _base_query(self) -> Any:
        return select(self.model).where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(self._base_query().where(self.model.id == entity_id))  # type: ignore[attr-defined]
        return result.scalar_one_or_none()

    async def add(self, entity: ModelT) -> ModelT:
        if getattr(entity, "tenant_id", None) != self.tenant_id:
            raise ValueError("entity tenant_id does not match repository scope")
        self.session.add(entity)
        await self.session.flush()
        return entity
