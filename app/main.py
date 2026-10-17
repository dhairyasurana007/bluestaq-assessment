import os

from fastapi import FastAPI


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Team Notes API")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT", "local")}

    return app


app = create_app()
