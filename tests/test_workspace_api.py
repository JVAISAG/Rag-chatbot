"""HTTP checks for the isolated research workspace API."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from sqlalchemy.exc import SQLAlchemyError

from src.workspace.database import DatabaseConfigurationError
from src.workspace.main import create_app


def test_workspace_health_endpoint():
    with TestClient(create_app()) as client:
        response = client.get("/api/v2/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_connect_to_database():
    database = MagicMock()
    with TestClient(create_app(lambda: database)) as client:
        assert client.get("/api/v2/health").status_code == 200
        database.check.assert_not_called()

    database.close.assert_called_once_with()


def test_readiness_checks_database():
    database = MagicMock()
    with TestClient(create_app(lambda: database)) as client:
        response = client.get("/api/v2/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}
    database.check.assert_called_once_with()
    database.close.assert_called_once_with()


@pytest.mark.parametrize("error_type", [DatabaseConfigurationError, SQLAlchemyError, OSError])
def test_readiness_hides_database_error_details(error_type):
    database = MagicMock()
    database.check.side_effect = error_type("private-database-details")
    with TestClient(create_app(lambda: database)) as client:
        response = client.get("/api/v2/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert "private-database-details" not in response.text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/files"),
        ("POST", "/api/v1/upload"),
        ("POST", "/api/v1/query"),
        ("POST", "/api/v1/index"),
        ("DELETE", "/api/v1/file/example.txt"),
    ],
)
def test_workspace_does_not_expose_legacy_routes(method, path):
    with TestClient(create_app()) as client:
        response = client.request(method, path)

    assert response.status_code == 404
