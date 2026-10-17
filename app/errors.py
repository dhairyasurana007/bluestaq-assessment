"""RFC 9457 problem+json error handling for every 4xx and 5xx (PLAN.md section 5.6)."""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    """Base class for domain errors; carries the HTTP status and a human-readable detail."""

    status_code = 500

    def __init__(self, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.headers = headers


class NotFoundError(AppError):
    status_code = 404


class PreconditionFailedError(AppError):
    status_code = 412


class PreconditionRequiredError(AppError):
    status_code = 428


def _reason(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


def problem_response(
    request: Request,
    status: int,
    detail: str,
    headers: dict[str, str] | None = None,
    errors: list[dict] | None = None,
) -> JSONResponse:
    body: dict = {
        "type": "about:blank",
        "title": _reason(status),
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, headers=headers, media_type=PROBLEM_JSON)


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return problem_response(request, exc.status_code, exc.detail, exc.headers)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return problem_response(request, exc.status_code, detail, dict(exc.headers or {}) or None)


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(err["loc"]), "msg": str(err["msg"])} for err in exc.errors()]
    return problem_response(request, 422, "Request validation failed.", errors=errors)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return problem_response(request, 500, "Internal server error.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    # Starlette's HTTPException also covers routing 404/405 and FastAPI's HTTPException.
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
