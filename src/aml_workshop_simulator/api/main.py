from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.aml_workshop_simulator.api.errors import ApiError
from src.aml_workshop_simulator.api.routers import admin, auth, health, rounds
from src.aml_workshop_simulator.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

#: Request/response headers that must never reach logs or audit events.
SENSITIVE_HEADERS = {"x-session-id", "authorization", "cookie"}


@app.middleware("http")
async def correlation_middleware(request: Request, call_next: Any) -> Any:
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers.setdefault("Cache-Control", "no-store")
    return response


def _envelope(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    payload = {
        "code": code,
        "message": message,
        "details": details,
        "request_id": request_id,
    }
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(status_code=status_code, content=payload, headers=response_headers)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _envelope(
        request, exc.status_code, exc.code, exc.message, exc.details, exc.headers
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    default_codes = {
        401: "session_missing",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
    }
    code = default_codes.get(exc.status_code, "http_error")
    return _envelope(request, exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    violations = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error.get("loc", ())[1:]) or "body"
        reason = error.get("type", "value_error")
        message = error.get("msg", "Некорректное значение")
        if field == "password" and reason == "string_too_short":
            minimum = (error.get("ctx") or {}).get("min_length", 10)
            message = f"Пароль должен содержать не менее {minimum} символов."
        violations.append({"field": field, "reason": reason, "message": message})

    response_message = "Запрос не соответствует контракту API"
    if (
        len(violations) == 1
        and violations[0]["field"] == "password"
        and violations[0]["reason"] == "string_too_short"
    ):
        response_message = violations[0]["message"]
    return _envelope(
        request,
        422,
        "validation_error",
        response_message,
        {"violations": violations},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _envelope(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Внутренняя ошибка сервиса",
    )


app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Auth"])
app.include_router(rounds.router, prefix=f"{settings.API_V1_STR}/rounds", tags=["Rounds"])
app.include_router(admin.router, prefix=f"{settings.API_V1_STR}/admin", tags=["Admin"])
