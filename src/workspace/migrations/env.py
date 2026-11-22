"""Run workspace migrations using the same settings as the workspace API."""

from alembic import context
from sqlalchemy import create_engine, pool

from src.workspace.database import database_url
from src.workspace.models import Base


config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_with_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        run_with_connection(connection)
        return

    engine = create_engine(
        database_url(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 3},
    )
    try:
        with engine.connect() as connection:
            run_with_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
