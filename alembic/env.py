import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure src/ is on the path so ticket_tracker can be imported by Alembic.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticket_tracker.config import settings
from ticket_tracker.db.base import Base
from ticket_tracker.db.models import pipeline_tables, event, facebook_listings_legacy_raw, facebook_listings_legacy_classified, seatgeek_event_stats, facebook_listings_new_raw, facebook_listings_new_classified, stubhub_listing_raw  # noqa: F401 — registers models with Base.metadata

config = context.config

# Override the placeholder URL in alembic.ini with the real one from .env.
config.set_main_option("sqlalchemy.url", str(settings.database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_TRACKED_SCHEMAS = {None, "facebook", "stubhub"}


def _include_name(name, type_, parent_names):
    """Tell autogenerate which schemas to scan.

    None = the default (public) schema: events, pipeline_runs, seatgeek_event_stats.
    Keeping schema=None on those models avoids the Alembic behaviour where explicit
    schema='public' causes autogenerate to treat them as new tables (not yet in DB).
    Cross-schema FK strings use unqualified names ('events.id') so SQLAlchemy can
    resolve them against the None-schema metadata entry; PostgreSQL resolves the DDL
    FK via search_path at runtime.
    """
    if type_ == "schema":
        return name in _TRACKED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=_include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
