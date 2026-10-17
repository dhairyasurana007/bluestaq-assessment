from fastapi import FastAPI

from app.config import Settings
from app.routers import health


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Team Notes API")
    app.state.database_url = database_url if database_url is not None else Settings().database_url
    app.include_router(health.router)
    return app


app = create_app()
