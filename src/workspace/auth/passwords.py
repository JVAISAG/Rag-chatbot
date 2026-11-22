"""Hash and verify account passwords with Argon2id."""

from dataclasses import dataclass
import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type


logger = logging.getLogger(__name__)
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


@dataclass(frozen=True)
class PasswordVerification:
    """Verification outcome and whether a successful hash needs updating."""

    valid: bool
    needs_rehash: bool = False


def hash_password(password: str) -> str:
    """Return an encoded Argon2id hash with a fresh random salt."""
    return _password_hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> PasswordVerification:
    """Verify a password and flag changed hashing parameters on success."""
    try:
        _password_hasher.verify(stored_hash, password)
        return PasswordVerification(valid=True, needs_rehash=_password_hasher.check_needs_rehash(stored_hash))
    except VerifyMismatchError:
        return PasswordVerification(valid=False)
    except (InvalidHashError, VerificationError):
        logger.warning("A stored password hash could not be verified.")
        return PasswordVerification(valid=False)
