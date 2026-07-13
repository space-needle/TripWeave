from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from tripweave.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(str(settings.database_url), pool_pre_ping=True)


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_postgis_version(engine: Engine) -> str:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).scalar_one_or_none()

    if result is None:
        raise RuntimeError("PostGIS extension is not installed")
    return str(result)


def iter_domain_tables(engine: Engine) -> Iterator[str]:
    query = text(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
        """
    )
    with engine.connect() as connection:
        for row in connection.execute(query):
            yield str(row.tablename)
