"""Database plumbing: per-app engine, session factory and the request-scoped session dependency."""

from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in the database and always returns timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    """Current time in UTC, with microsecond resolution."""
    return datetime.now(UTC)


def make_engine(database_url: str) -> Engine:
    """Build an engine for ``database_url``. No connection is made until first use."""
    url = make_url(database_url)
    kwargs: dict = {}
    is_sqlite = url.get_backend_name() == "sqlite"
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        # In-memory databases need one shared connection; file databases open one per use,
        # which also leaves no lingering file handles behind.
        in_memory = url.database in (None, "", ":memory:")
        kwargs["poolclass"] = StaticPool if in_memory else NullPool
    engine = create_engine(url, **kwargs)
    if is_sqlite:
        event.listen(engine, "connect", _sqlite_on_connect)
    return engine


def _sqlite_on_connect(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, taken from the app's own engine."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with factory() as session:
        yield session
