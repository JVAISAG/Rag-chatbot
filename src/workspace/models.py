"""Database model metadata for the research workspace."""

from datetime import date, datetime
import uuid

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid
from src.workspace.vectors import Vector


class Base(DeclarativeBase):
    """Base for workspace database models."""


class User(Base):
    """An account; login identifiers are stored separately."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserIdentifier(Base):
    """An email address or username belonging to an account."""

    __tablename__ = "user_identifiers"
    __table_args__ = (
        CheckConstraint("kind IN ('email', 'username')", name="ck_user_identifiers_kind"),
        CheckConstraint("length(trim(value)) > 0", name="ck_user_identifiers_value"),
        CheckConstraint("length(trim(normalized_value)) > 0", name="ck_user_identifiers_normalized_value"),
        UniqueConstraint("normalized_value", name="uq_user_identifiers_normalized_value"),
        UniqueConstraint("user_id", "kind", name="uq_user_identifiers_user_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str] = mapped_column(Text, nullable=False)


class UserSession(Base):
    """An opaque session represented by a hash of its token."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        Index("ix_user_sessions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginThrottle(Base):
    """Persistent sign-in attempt counters without raw identifiers or IPs."""

    __tablename__ = "login_throttles"
    __table_args__ = (
        CheckConstraint("scope IN ('account', 'unknown', 'client')", name="ck_login_throttles_scope"),
        CheckConstraint("length(key_digest) = 64", name="ck_login_throttles_key_digest"),
        CheckConstraint("attempts >= 0", name="ck_login_throttles_attempts"),
        Index("ix_login_throttles_updated_at", "updated_at"),
    )

    scope: Mapped[str] = mapped_column(String(8), primary_key=True)
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Collection(Base):
    """A private research collection belonging to one account."""

    __tablename__ = "collections"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 100", name="ck_collections_name_length"),
        CheckConstraint("length(trim(name)) > 0", name="ck_collections_name_nonempty"),
        CheckConstraint("length(normalized_name) > 0", name="ck_collections_normalized_name"),
        CheckConstraint("description IS NULL OR length(description) <= 2000", name="ck_collections_description_length"),
        UniqueConstraint("owner_id", "normalized_name", name="uq_collections_owner_normalized_name"),
        Index("ix_collections_owner_created_at", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Job(Base):
    """A durable, owner-scoped background task with a renewable lease."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_jobs_status"),
        CheckConstraint("attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts", name="ck_jobs_attempts"),
        Index("ix_jobs_status_created_at", "status", "created_at"),
        Index("ix_jobs_owner_id", "owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("owner_id", "content_hash", name="uq_sources_owner_hash"),
        CheckConstraint("reading_status IN ('unread', 'reading', 'read')", name="ck_sources_reading_status"))
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[date | None] = mapped_column(Date)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default='[]')
    reading_status: Mapped[str] = mapped_column(String(16), nullable=False, default='unread', server_default='unread')
    original_url: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False)
    active_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("source_revisions.id", name="fk_sources_active_revision_id", ondelete="SET NULL", use_alter=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SourceRevision(Base):
    __tablename__ = "source_revisions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    pages: Mapped[list] = mapped_column(JSON, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    original_url: Mapped[str | None] = mapped_column(Text)


class SourceReplacement(Base):
    """A staged file stays separate from the source until indexing publishes it."""
    __tablename__ = "source_replacements"
    __table_args__ = (CheckConstraint("status IN ('staged', 'published', 'abandoned')", name="ck_source_replacements_status"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    extract_job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False, unique=True)
    index_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("jobs.id"), unique=True)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("source_revisions.id", ondelete="SET NULL"), unique=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="staged", server_default="staged")
    original_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("revision_id", "ordinal", name="uq_chunks_revision_ordinal"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("source_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector().with_variant(JSON(), "sqlite"), nullable=False)


class CollectionSource(Base):
    __tablename__ = "collection_sources"
    collection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("collections.id", ondelete="SET NULL"))
    source_ids: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QuestionTurn(Base):
    __tablename__ = "question_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "request_key", name="uq_question_turn_request_key"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False, unique=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    request_key: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    retrieval_query: Mapped[str | None] = mapped_column(Text)
    timings: Mapped[dict | None] = mapped_column(JSON)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    evidence: Mapped[list | None] = mapped_column(JSON)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="qa-v1", server_default="qa-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Analysis(Base):
    __tablename__ = "analyses"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sources.id", ondelete="SET NULL"))
    revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("source_revisions.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="summary-v1", server_default="summary-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Comparison(Base):
    __tablename__ = 'comparisons'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('collections.id', ondelete='SET NULL'))
    selections: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Note(Base):
    __tablename__ = 'notes'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('collections.id', ondelete='SET NULL'))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    comparison_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
