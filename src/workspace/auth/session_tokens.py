"""Generate opaque session tokens and their database-safe digests."""

import hashlib
import re
import secrets


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def generate_session_token() -> str:
    """Return a URL-safe token generated from 32 random bytes."""
    return secrets.token_urlsafe(32)


def session_token_digest(token: str | None) -> str | None:
    """Return a SHA-256 digest for a well-formed token, or None otherwise."""
    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()
