"""Origin checking must not trust lookalike or missing browser origins."""

import pytest

from src.workspace.auth.origins import is_trusted_request_origin


ALLOWED = {"http://localhost:3000"}


@pytest.mark.parametrize("origin,referer", [
    ("http://localhost:3000", None),
    (None, "http://localhost:3000/documents?section=1"),
])
def test_allowed_origin_or_referer(origin, referer):
    assert is_trusted_request_origin(origin=origin, referer=referer, allowed_origins=ALLOWED)


@pytest.mark.parametrize("origin,referer", [
    (None, None),
    ("null", "http://localhost:3000/page"),
    ("http://localhost:3000.evil.example", None),
    ("http://evil.example", "http://localhost:3000/page"),
    ("http://localhost:3000/", None),
    (None, "http://localhost:3000@evil.example/page"),
    (None, "http://localhost:3000.evil.example/page"),
    (None, "http://localhost:notaport/page"),
    (None, "http://[broken/page"),
    (None, "javascript://localhost:3000/page"),
])
def test_unknown_or_unusable_origins_are_rejected(origin, referer):
    assert not is_trusted_request_origin(origin=origin, referer=referer, allowed_origins=ALLOWED)
