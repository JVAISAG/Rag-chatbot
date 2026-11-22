"""Shared identifier normalization for account registration and sign-in."""

import pytest

from src.workspace.auth.identifiers import normalize_identifier, normalize_login_identifier


@pytest.mark.parametrize("value", ["Reader_1", "READER_1", "reader_1"])
def test_username_sign_in_matches_registration(value):
    assert normalize_login_identifier(value) == normalize_identifier("Reader_1")


def test_email_sign_in_matches_registration_with_international_domain():
    registered = "Sam@bücher.de"
    assert normalize_login_identifier("SAM@xn--bcher-kva.de") == normalize_identifier(registered)


@pytest.mark.parametrize("value", ["", "ab", "invalid name", "bad@email", "ééé", "\ud800"])
def test_invalid_sign_in_identifiers_are_rejected(value):
    assert normalize_login_identifier(value) is None
