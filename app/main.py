from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.errors import register_error_handlers
from app.routers import health, notes, root, teams


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    app.state.engine.dispose()


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Team Notes API", lifespan=_lifespan)
    app.state.database_url = database_url if database_url is not None else Settings().database_url
    # Per-app engine; creating it does not connect (or create a database file).
    app.state.engine = make_engine(app.state.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    register_error_handlers(app)
    app.include_router(root.router)
    app.include_router(health.router)
    app.include_router(teams.router)
    app.include_router(notes.router)
    return app


app = create_app()
