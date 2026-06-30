import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


async def get_db() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_job(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.get(Job, uuid.UUID(job_id))
    return result


async def create_job(
    db: AsyncSession,
    filename: str,
    storage_key: str,
    content_type: str,
) -> Job:
    job = Job(
        filename=filename,
        storage_key=storage_key,
        content_type=content_type,
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def update_job(db: AsyncSession, job_id: str, **kwargs: Any) -> Job | None:
    job = await get_job(db, job_id)
    if job is None:
        return None
    for key, value in kwargs.items():
        setattr(job, key, value)
    await db.commit()
    await db.refresh(job)
    return job
