"""Alembic environment: online migrations against DATABASE_URL, one transaction, no autogenerate."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from pulse.config import get_settings

config = context.config


def run_migrations_online() -> None:
    engine = create_engine(get_settings().sqlalchemy_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported: the schema needs the pgvector extension")
run_migrations_online()
