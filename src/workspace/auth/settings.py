"""Configuration for the local research workspace's authentication flow."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
import os
from pathlib import Path

from dotenv import dotenv_values

from src.workspace.auth.throttling import ThrottlePolicy
from src.workspace.database import DEFAULT_ENV_FILE


LOCAL_ALLOWED_ORIGINS = frozenset({
    "http://localhost:3000",
    "http://127.0.0.1:3000",
})
LOGIN_POLICY = ThrottlePolicy(
    account_limit=5,
    client_limit=30,
    window=timedelta(minutes=15),
    block_duration=timedelta(minutes=15),
)


@dataclass(frozen=True)
class AuthSettings:
    cookie_secure: bool = True


def load_auth_settings(
    environ: Mapping[str, str] | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
) -> AuthSettings:
    """Require an explicit opt-in before sending session cookies over HTTP."""
    environment = os.environ if environ is None else environ
    file_values = dotenv_values(env_file)
    name = "WORKSPACE_COOKIE_SECURE"
    configured = environment[name] if name in environment else file_values.get(name)
    if configured is None:
        return AuthSettings()
    value = configured.strip().lower()
    if value not in {"true", "false"}:
        raise ValueError("WORKSPACE_COOKIE_SECURE must be true or false.")
    return AuthSettings(cookie_secure=value == "true")
