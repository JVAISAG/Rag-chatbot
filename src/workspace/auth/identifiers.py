"""Shared account-identifier normalization for registration and sign-in."""

import re
import unicodedata

from email_validator import EmailNotValidError, validate_email


USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,32}")


def normalize_identifier(value: str) -> str:
    """Use the same case-insensitive representation for all account identifiers."""
    return unicodedata.normalize("NFC", value.casefold())


def normalize_login_identifier(value: str) -> str | None:
    """Normalize a valid username or email without making a DNS request."""
    if USERNAME_PATTERN.fullmatch(value):
        return normalize_identifier(value)
    try:
        email = validate_email(value, check_deliverability=False).normalized
    except (EmailNotValidError, UnicodeError):
        return None
    return normalize_identifier(email)
