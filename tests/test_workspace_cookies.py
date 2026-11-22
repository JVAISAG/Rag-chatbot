"""Browser session-cookie attributes and expiry."""

from datetime import datetime, timezone
from http.cookies import SimpleCookie

import pytest
from starlette.responses import Response

from src.workspace.auth.cookies import SESSION_COOKIE, clear_session_cookie, set_session_cookie
from src.workspace.auth.sessions import IssuedSession


@pytest.mark.parametrize("secure", [True, False])
def test_cookie_is_http_only_scoped_and_expires_after_seven_days(secure):
    response = Response()
    expires = datetime(2026, 1, 8, 12, 0, tzinfo=timezone.utc)
    set_session_cookie(response, IssuedSession(token="a" * 43, expires_at=expires), secure=secure)

    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[SESSION_COOKIE]
    assert morsel.value == "a" * 43
    assert morsel["httponly"]
    assert morsel["path"] == "/"
    assert morsel["samesite"] == "lax"
    assert morsel["max-age"] == str(7 * 24 * 60 * 60)
    assert bool(morsel["secure"]) is secure
    assert morsel["expires"] == "Thu, 08 Jan 2026 12:00:00 GMT"
    assert not morsel["domain"]
    assert response.headers["cache-control"] == "no-store"


def test_logout_cookie_expires_and_uses_matching_attributes():
    response = Response()
    clear_session_cookie(response, secure=True)
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    morsel = cookie[SESSION_COOKIE]
    assert morsel.value == ""
    assert morsel["max-age"] == "0"
    assert morsel["httponly"]
    assert morsel["secure"]
    assert morsel["path"] == "/"
    assert morsel["samesite"] == "lax"
    assert response.headers["cache-control"] == "no-store"
