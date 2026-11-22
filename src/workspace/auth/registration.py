"""Validation and transactional account creation for the workspace."""

import uuid

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator
from sqlalchemy.exc import IntegrityError

from src.workspace.auth.identifiers import USERNAME_PATTERN, normalize_identifier
from src.workspace.auth.passwords import hash_password
from src.workspace.database import WorkspaceDatabase
from src.workspace.models import User, UserIdentifier


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    username: str | None = None
    email: str | None = None
    password: SecretStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, username: str | None) -> str | None:
        if username is not None and not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("Username must be 3–32 ASCII letters, numbers, dots, underscores, or hyphens.")
        return username

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, email: str | None) -> str | None:
        if email is None:
            return None
        try:
            return validate_email(email, check_deliverability=False).normalized
        except EmailNotValidError:
            raise ValueError("Enter a valid email address.") from None

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: SecretStr) -> SecretStr:
        value = password.get_secret_value()
        if not 8 <= len(value) <= 128:
            raise ValueError("Password must be 8–128 characters long.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Password contains invalid Unicode.") from None
        return password

    @model_validator(mode="after")
    def require_identifier(self) -> "RegistrationRequest":
        if self.username is None and self.email is None:
            raise ValueError("Provide a username or email address.")
        return self


class RegistrationResponse(BaseModel):
    id: uuid.UUID


class IdentifierUnavailable(Exception):
    """A requested sign-in identifier is already in use."""


def _identifier_conflict(error: IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    return (
        getattr(original, "sqlstate", None) == "23505"
        and getattr(diagnostic, "constraint_name", None) == "uq_user_identifiers_normalized_value"
    )


def register_account(database: WorkspaceDatabase, request: RegistrationRequest) -> uuid.UUID:
    """Store the account and all of its identifiers in one transaction."""
    user_id = uuid.uuid4()
    password_hash = hash_password(request.password.get_secret_value())

    try:
        with database.transaction() as session:
            session.add(User(id=user_id, password_hash=password_hash))
            session.flush()
            for kind, value in (("username", request.username), ("email", request.email)):
                if value is not None:
                    session.add(UserIdentifier(
                        user_id=user_id,
                        kind=kind,
                        value=value,
                        normalized_value=normalize_identifier(value),
                    ))
    except IntegrityError as error:
        if _identifier_conflict(error):
            raise IdentifierUnavailable from None
        raise

    return user_id
