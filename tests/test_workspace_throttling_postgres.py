"""Opt-in concurrency checks for PostgreSQL login-attempt limits."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import re
from threading import Barrier
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from src.workspace.auth.login import LoginRequest, authenticate_password
from src.workspace.auth.passwords import hash_password
from src.workspace.auth.throttling import ThrottlePolicy, check_login_attempt
from src.workspace.database import WorkspaceDatabase, database_url
from src.workspace.models import Base, User, UserIdentifier


@pytest.mark.skipif(
    os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1",
    reason="Set WORKSPACE_RUN_POSTGRES_TESTS=1 for isolated PostgreSQL tests.",
)
def test_concurrent_attempts_cannot_bypass_postgres_limits():
    url = database_url()
    if url.host not in {"127.0.0.1", "localhost"} or not re.fullmatch(r"research_test_[0-9a-f]{12}", url.database or ""):
        pytest.fail("PostgreSQL throttle tests require a dedicated local research_test_<12 hex digits> database.")

    schema = f"workspace_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    workspace_engine = None
    database = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        workspace_engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 3, "options": f"-csearch_path={schema},public"},
        )
        Base.metadata.create_all(workspace_engine)
        database = WorkspaceDatabase(engine_factory=lambda: workspace_engine)
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        duration = timedelta(minutes=15)

        def run_concurrently(*, shared_client, valid, policy):
            ready = Barrier(5)

            def run(index):
                ready.wait(timeout=10)
                with database.transaction() as session:
                    return check_login_attempt(
                        session,
                        principal_scope="account",
                        principal_key=f"separate-{index}" if shared_client else "shared-account",
                        client_key="shared-client" if shared_client else f"separate-client-{index}",
                        verify=lambda: valid,
                        policy=policy,
                        now=now,
                    )

            with ThreadPoolExecutor(max_workers=5) as pool:
                return list(pool.map(run, range(5)))

        account_results = run_concurrently(
            shared_client=False,
            valid=False,
            policy=ThrottlePolicy(2, 20, duration, duration),
        )
        assert sum(result.retry_after is None for result in account_results) == 2
        assert sum(result.retry_after == 900 for result in account_results) == 3
        assert not any(result.verified for result in account_results)

        client_results = run_concurrently(
            shared_client=True,
            valid=True,
            policy=ThrottlePolicy(20, 3, duration, duration),
        )
        assert sum(result.verified for result in client_results) == 3
        assert sum(result.retry_after == 900 for result in client_results) == 2

        user_id = uuid.uuid4()
        with database.transaction() as session:
            session.add(User(id=user_id, password_hash=hash_password("a valid password")))
            session.add_all([
                UserIdentifier(user_id=user_id, kind="username", value="Reader", normalized_value="reader"),
                UserIdentifier(user_id=user_id, kind="email", value="reader@example.com", normalized_value="reader@example.com"),
            ])

        ready = Barrier(5)

        def sign_in(index):
            ready.wait(timeout=10)
            return authenticate_password(
                database,
                LoginRequest(identifier="READER" if index % 2 else "reader@example.com", password="wrong"),
                client_key=f"login-client-{index}",
                policy=ThrottlePolicy(2, 20, duration, duration),
                now=now,
            )

        with ThreadPoolExecutor(max_workers=5) as pool:
            login_results = list(pool.map(sign_in, range(5)))
        assert sum(result.retry_after is None for result in login_results) == 2
        assert sum(result.retry_after == 900 for result in login_results) == 3
        assert all(result.user_id is None for result in login_results)
    finally:
        if database is not None:
            database.close()
        elif workspace_engine is not None:
            workspace_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin_engine.dispose()
