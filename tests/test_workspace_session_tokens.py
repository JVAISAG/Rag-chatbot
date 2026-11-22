"""Checks for opaque session-token generation and hashing."""

import re

import pytest

from src.workspace.auth.session_tokens import generate_session_token, session_token_digest


def test_generated_tokens_are_distinct_and_have_stable_digests():
    first = generate_session_token()
    second = generate_session_token()

    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)
    digest = session_token_digest(first)
    assert digest is not None
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert digest == session_token_digest(first)
    assert first not in digest
    assert digest != session_token_digest(second)


@pytest.mark.parametrize("token", [None, "", "a" * 42, "a" * 44, "!" * 43, "é" * 43])
def test_invalid_tokens_have_no_digest(token):
    assert session_token_digest(token) is None
