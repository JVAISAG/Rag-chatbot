"""Check browser origins before performing cookie-authenticated mutations."""

from collections.abc import Collection
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from src.workspace.auth.settings import LOCAL_ALLOWED_ORIGINS


def is_trusted_request_origin(
    *,
    origin: str | None,
    referer: str | None,
    allowed_origins: Collection[str],
) -> bool:
    """Compare the supplied Origin, or the Referer origin, with an exact allowlist."""
    if origin is not None:
        return origin != "null" and origin in allowed_origins
    if referer is None:
        return False
    try:
        parts = urlsplit(referer)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            return False
        # Accessing port also rejects malformed bracketed hosts and ports.
        _ = parts.port
    except ValueError:
        return False
    return f"{parts.scheme}://{parts.netloc}" in allowed_origins


def has_trusted_origin(request: Request) -> bool:
    return is_trusted_request_origin(
        origin=request.headers.get("origin"),
        referer=request.headers.get("referer"),
        allowed_origins=LOCAL_ALLOWED_ORIGINS,
    )


def require_trusted_origin(request: Request) -> None:
    """Reject mutations from unknown or unavailable browser origins."""
    if not has_trusted_origin(request):
        raise HTTPException(
            status_code=403,
            detail="Request origin is not allowed.",
            headers={"Cache-Control": "no-store"},
        )
