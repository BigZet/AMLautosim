from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.errors import ApplicationError
from src.aml_workshop_simulator.services.authentication import INVALID_CREDENTIALS

logger = logging.getLogger(__name__)


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
    response_headers = {"Cache-Control": "no-store", **(headers or {})}
    if request_id:
        response_headers["X-Request-ID"] = request_id
    return JSONResponse(
        status_code=status_code, content=payload, headers=response_headers
    )


async def api_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    return _envelope(
        request, exc.status_code, exc.code, exc.message, exc.details, exc.headers
    )


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
    return _envelope(
        request, exc.status_code, code, str(exc.detail), headers=exc.headers
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    violations = []
    for error in exc.errors():
        # loc обычно вида ("body", "email"); отбрасываем первый элемент
        # ("body"/"query"/...), оставляя только путь до конкретного поля.
        parts = list(error.get("loc", ())[1:])
        # Discriminated configuration unions add the schema tag, not a field.
        if len(parts) > 1 and parts[0] == "game_config" and parts[1] in (7, 8, 9, 10):
            parts.pop(1)
        field = ".".join(str(part) for part in parts) or "body"
        reason = error.get("type", "value_error")
        message = error.get("msg", "Некорректное значение").removeprefix(
            "Value error, "
        )
        if field == "password" and reason == "string_too_short":
            minimum = (error.get("ctx") or {}).get("min_length", 10)
            message = f"Пароль должен содержать не менее {minimum} символов."
        violations.append({"field": field, "reason": reason, "message": message})

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
            INVALID_CREDENTIALS,
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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled request error: %s",
        getattr(request.state, "request_id", None),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _envelope(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_error",
        "Внутренняя ошибка сервиса",
    )
