"""Verify workspace credentials without creating or exposing a session."""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import uuid

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from sqlalchemy import select

from src.workspace.auth.identifiers import normalize_identifier, normalize_login_identifier
from src.workspace.auth.passwords import hash_password, verify_password
from src.workspace.auth.throttling import ThrottlePolicy, check_login_attempt
from src.workspace.database import WorkspaceDatabase
from src.workspace.models import User, UserIdentifier


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    identifier: str
    password: SecretStr

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not 1 <= len(value) <= 320:
            raise ValueError("Identifier must be 1–320 characters long.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Identifier contains invalid Unicode.") from None
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: SecretStr) -> SecretStr:
        value = password.get_secret_value()
        if len(value) > 128:
            raise ValueError("Password must be at most 128 characters long.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Password contains invalid Unicode.") from None
        return password


@dataclass(frozen=True)
class LoginResult:
    user_id: uuid.UUID | None = None
    retry_after: int | None = None


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    # Match the current Argon2 settings even for an unknown identifier. The
    # result of this comparison is never allowed to authenticate an account.
    return hash_password("workspace invalid account sentinel")


def authenticate_password(
    database: WorkspaceDatabase,
    request: LoginRequest,
    *,
    client_key: str,
    policy: ThrottlePolicy,
    now: datetime | None = None,
) -> LoginResult:
    """Check credentials and update attempt counters in one transaction."""
    now = now if now is not None else datetime.now(timezone.utc)
    normalized = normalize_login_identifier(request.identifier)

    with database.transaction() as session:
        account = None
        if normalized is not None:
            account = session.execute(
                select(User.id, User.password_hash)
                .join(UserIdentifier, UserIdentifier.user_id == User.id)
                .where(UserIdentifier.normalized_value == normalized)
            ).one_or_none()

        # Both identifiers of a known user share a limit. Invalid and unknown
        # identifiers are counted separately without disclosing their values.
        scope = "account" if account is not None else "unknown"
        key = str(account.id) if account is not None else (normalized or normalize_identifier(request.identifier))

        def verify() -> bool:
            stored_hash = account.password_hash if account is not None else _dummy_password_hash()
            result = verify_password(request.password.get_secret_value(), stored_hash)
            return account is not None and result.valid

        outcome = check_login_attempt(
            session,
            principal_scope=scope,
            principal_key=key,
            client_key=client_key,
            verify=verify,
            policy=policy,
            now=now,
        )
        if outcome.verified and account is not None:
            return LoginResult(user_id=account.id)
        return LoginResult(retry_after=outcome.retry_after)
