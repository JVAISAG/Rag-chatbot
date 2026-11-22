"""Validation and owner-scoped persistence for research collections."""

from datetime import datetime, timezone
import unicodedata
import uuid

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from src.workspace.database import WorkspaceDatabase
from src.workspace.models import Collection, Comparison, Note, User


def _validate_text(value: str, *, label: str, maximum: int) -> str:
    value = unicodedata.normalize("NFC", value.strip())
    if "\x00" in value:
        raise ValueError(f"{label} contains an unsupported character.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label} contains invalid Unicode.") from None
    if len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters long.")
    return value


def _validate_name(value: str | None) -> str:
    if value is None:
        raise ValueError("Collection name is required.")
    value = _validate_text(value, label="Collection name", maximum=100)
    if not value:
        raise ValueError("Collection name is required.")
    return value


def _validate_description(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_text(value, label="Description", maximum=2000) or None


def _normalized_name(name: str) -> str:
    return unicodedata.normalize("NFC", name.casefold())


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    description: str | None = None

    _name = field_validator("name")(_validate_name)
    _description = field_validator("description")(_validate_description)


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str | None = None
    description: str | None = None

    _name = field_validator("name")(_validate_name)
    _description = field_validator("description")(_validate_description)

    @model_validator(mode="after")
    def require_change(self) -> "CollectionUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide a name or description to update.")
        return self


class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class CollectionNotFound(Exception):
    """The collection does not exist for the requesting owner."""


class CollectionNameUnavailable(Exception):
    """The requesting owner already has a collection with this name."""


class CollectionHasNotes(Exception):
    """Removing this collection would strand the owner's saved note content."""


def _is_name_conflict(error: IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    if getattr(original, "sqlstate", None) == "23505":
        return getattr(diagnostic, "constraint_name", None) == "uq_collections_owner_normalized_name"
    return (
        getattr(original, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE"
        and str(original) == "UNIQUE constraint failed: collections.owner_id, collections.normalized_name"
    )


def list_collections(database: WorkspaceDatabase, owner_id: uuid.UUID) -> list[CollectionResponse]:
    with database.transaction() as session:
        rows = session.scalars(
            select(Collection)
            .where(Collection.owner_id == owner_id)
            .order_by(Collection.created_at.desc(), Collection.id.desc())
        ).all()
        return [CollectionResponse.model_validate(row) for row in rows]


def get_collection(database: WorkspaceDatabase, owner_id: uuid.UUID, collection_id: uuid.UUID) -> CollectionResponse:
    with database.transaction() as session:
        row = session.scalar(select(Collection).where(Collection.owner_id == owner_id, Collection.id == collection_id))
        if row is None:
            raise CollectionNotFound
        return CollectionResponse.model_validate(row)


def create_collection(database: WorkspaceDatabase, owner_id: uuid.UUID, details: CollectionCreate) -> CollectionResponse:
    try:
        with database.transaction() as session:
            row = Collection(
                id=uuid.uuid4(),
                owner_id=owner_id,
                name=details.name,
                normalized_name=_normalized_name(details.name),
                description=details.description,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            result = CollectionResponse.model_validate(row)
        return result
    except IntegrityError as error:
        if _is_name_conflict(error):
            raise CollectionNameUnavailable from None
        raise


def update_collection(
    database: WorkspaceDatabase,
    owner_id: uuid.UUID,
    collection_id: uuid.UUID,
    details: CollectionUpdate,
) -> CollectionResponse:
    try:
        with database.transaction() as session:
            row = session.scalar(
                select(Collection)
                .where(Collection.owner_id == owner_id, Collection.id == collection_id)
                .with_for_update()
            )
            if row is None:
                raise CollectionNotFound
            if "name" in details.model_fields_set:
                assert details.name is not None  # Validated when the field is supplied.
                row.name = details.name
                row.normalized_name = _normalized_name(details.name)
            if "description" in details.model_fields_set:
                row.description = details.description
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            result = CollectionResponse.model_validate(row)
        return result
    except IntegrityError as error:
        if _is_name_conflict(error):
            raise CollectionNameUnavailable from None
        raise


def delete_collection(database: WorkspaceDatabase, owner_id: uuid.UUID, collection_id: uuid.UUID) -> None:
    with database.transaction() as session:
        # Serialize with note/comparison creation and membership changes.
        session.scalar(select(User.id).where(User.id == owner_id).with_for_update())
        row = session.scalar(
            select(Collection)
            .where(Collection.owner_id == owner_id, Collection.id == collection_id)
            .with_for_update()
        )
        if row is None:
            raise CollectionNotFound
        if session.scalar(select(Note.id).where(Note.collection_id == collection_id, Note.owner_id == owner_id).limit(1)) is not None:
            raise CollectionHasNotes
        session.execute(delete(Comparison).where(Comparison.collection_id == collection_id, Comparison.owner_id == owner_id))
        session.delete(row)
