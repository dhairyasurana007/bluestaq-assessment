import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "commit": os.environ.get("RENDER_GIT_COMMIT", "local")}
