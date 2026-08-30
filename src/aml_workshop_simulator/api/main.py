from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.aml_workshop_simulator.api.errors import ApiError
from src.aml_workshop_simulator.api.routers import admin, auth, health, rounds
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.logging import (
    REQUEST_ID,
    configure_logging,
    log_event,
    log_exception,
)
from src.aml_workshop_simulator.schemas.catalog_config import (
    validate_configuration_files,
)

validate_configuration_files()
configure_logging("api")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

#: Request/response headers that must never reach logs or audit events.
SENSITIVE_HEADERS = {"x-session-id", "authorization", "cookie"}

#: Endpoints an orchestrator polls every few seconds. Logging them would bury
#: the events an operator is actually looking for.
UNLOGGED_ROUTES = {"/health/live", "/health/ready"}


@app.middleware("http")
async def correlation_middleware(request: Request, call_next: Any) -> Any:
    """Correlate and time one request, and log both ends of it.

    The id travels back in `X-Request-ID` and is what an operator searches by;
    `REQUEST_ID` carries it to every log call made while serving the request, so
    handlers do not have to thread it through themselves.
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = REQUEST_ID.set(request_id)
    started = time.perf_counter()
    quiet = request.url.path in UNLOGGED_ROUTES
    try:
        if not quiet:
            log_event("request_started", route=_route(request), method=request.method)
        response = await call_next(request)
        if not quiet:
            log_event(
                "request_completed",
                route=_route(request),
                method=request.method,
                status_code=response.status_code,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("Cache-Control", "no-store")
        return response
    finally:
        REQUEST_ID.reset(token)


def _route(request: Request) -> str:
    """The path to log: templated once routing has resolved it.

    `/rounds/12` and `/rounds/13` then aggregate as one route. At
    `request_started` the router has not run yet, so that event carries the
    concrete path; both events share a `request_id`, which is what an operator
    searches by. Never the full URL — a query string can carry values the
    allowlist exists to keep out.
    """
    params = {str(value): name for name, value in (request.path_params or {}).items()}
    if not params:
        return request.url.path
    # Rebuilt from the matched parameters rather than read off the route: an
    # included router carries only its own relative path (`/{round_id}/scenario`),
    # which two routers could share.
    return "/".join(
        f"{{{params[segment]}}}" if segment in params else segment
        for segment in request.url.path.split("/")
    )


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
    # One place covers every refusal the API makes deliberately, including the
    # scenario conflicts §7 asks for by name (`scenario_revision_conflict`,
    # `mutation_id_reused`). The *message* is never logged: several of them
    # quote values the allowlist keeps out.
    log_event(
        "request_refused",
        level=logging.WARNING if exc.status_code >= 400 else logging.INFO,
        route=_route(request),
        method=request.method,
        status_code=exc.status_code,
        reason_code=exc.code,
    )
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

    # An invalidly formatted credential is still just an invalid credential to
    # a person signing in.  Keep this response indistinguishable from an
    # unknown email or a wrong password, and do not expose schema terminology
    # in either Streamlit login screen.
    is_login_request = (
        request.method == "POST"
        and request.url.path == f"{settings.API_V1_STR}/auth/login"
    )
    credential_fields = {"email", "password"}
    if (
        is_login_request
        and violations
        and all(violation["field"] in credential_fields for violation in violations)
    ):
        return _envelope(
            request,
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            auth.INVALID_CREDENTIALS,
        )

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
    # The envelope tells the caller nothing about the cause, by design. If the
    # traceback is not written here it exists nowhere, and a 500 seen at the
    # workshop can never be explained afterwards.
    # Starlette runs this handler outside the correlation middleware, so the
    # context variable has already been reset; the id survives on the request.
    token = REQUEST_ID.set(getattr(request.state, "request_id", None))
    try:
        log_exception(
            "request_failed",
            route=_route(request),
            method=request.method,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        REQUEST_ID.reset(token)
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
