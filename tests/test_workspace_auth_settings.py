"""Local session-cookie configuration."""

import pytest

from src.workspace.auth.settings import AuthSettings, load_auth_settings


def test_secure_cookies_are_the_default(tmp_path):
    assert load_auth_settings({}, tmp_path / "missing.env") == AuthSettings(cookie_secure=True)


def test_local_http_requires_explicit_setting_and_environment_takes_precedence(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("WORKSPACE_COOKIE_SECURE=false\n", encoding="utf-8")
    assert not load_auth_settings({}, env_file).cookie_secure
    assert load_auth_settings({"WORKSPACE_COOKIE_SECURE": "true"}, env_file).cookie_secure


@pytest.mark.parametrize("value", ["", "0", "yes", "unsafe"])
def test_invalid_cookie_setting_fails_closed(tmp_path, value):
    with pytest.raises(ValueError, match="WORKSPACE_COOKIE_SECURE"):
        load_auth_settings({"WORKSPACE_COOKIE_SECURE": value}, tmp_path / "missing.env")
