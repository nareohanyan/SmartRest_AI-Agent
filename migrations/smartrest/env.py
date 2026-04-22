import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

try:
    from app.smartrest.models import Base
except ImportError as exc:
    raise RuntimeError(
        "Unable to import Base from app.smartrest.models. "
        "Define your SQLAlchemy Base/models first, then run Alembic."
    ) from exc

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

smartrest_db_url = os.getenv("SMARTREST_DATABASE_URL") or os.getenv("DATABASE_URL")
if not smartrest_db_url:
    raise RuntimeError(
        "SMARTREST_DATABASE_URL is not set. "
        "Set it in your environment before running SmartRest Alembic."
    )

config.set_main_option("sqlalchemy.url", smartrest_db_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
