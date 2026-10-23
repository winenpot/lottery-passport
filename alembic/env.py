import sys
from logging.config import fileConfig
from urllib.parse import urlparse

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.infrastructure.postgres.database import is_pgbouncer_url
from app.infrastructure.postgres.models import Base

config = context.config

# `-x db_url=...` lets you point a one-off migration run at a different
# database than Settings.database_url (e.g. a throwaway/scratch database for
# a test), without needing a second .env. Before this, the flag was silently
# ignored and alembic always used Settings.database_url -- on 2026-10-22 that
# ran real migrations against a stale remote database a local .env still
# pointed at, with no warning. `database_url` below is also used by
# run_async_migrations() for the PgBouncer check, so both paths agree.
x_args = context.get_x_argument(as_dictionary=True)
database_url = x_args.get("db_url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", database_url)

# Always visible, not just when -x is used: whoever runs a migration should
# see the exact host/database before it happens. Never the credentials.
_parsed = urlparse(database_url)
print(
    f"alembic: migrating {_parsed.hostname}:{_parsed.port or '-'}{_parsed.path} "
    f"({'from -x db_url' if 'db_url' in x_args else 'from Settings.database_url'})",
    file=sys.stderr,
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connect_args: dict[str, object] = {}
    if is_pgbouncer_url(database_url):
        # PgBouncer (transaction mode, Supabase port 6543) does not support
        # named prepared statements -- same fix as the app's own engine
        # (app/infrastructure/postgres/database.py), or every migration
        # fails with "prepared statement already exists".
        connect_args["statement_cache_size"] = 0
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
