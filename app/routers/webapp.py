"""The demo web client: a single static HTML page served at ``GET /app``."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

# Resolved from this file (not the working directory) so it works wherever the app is started.
_APP_HTML = Path(__file__).resolve().parent.parent / "static" / "app.html"


@router.get("/app", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(_APP_HTML, media_type="text/html")
