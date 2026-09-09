"""FastAPI composition root."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from src.aml_workshop_simulator.api import error_handlers
from src.aml_workshop_simulator.api.routers import admin, auth, health, rounds
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.errors import ApplicationError
from src.aml_workshop_simulator.db.session import async_engine
from src.aml_workshop_simulator.schemas.catalog_config import (
    validate_configuration_files,
)
from src.aml_workshop_simulator.schemas.common import ErrorEnvelope


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_configuration_files()
    try:
        yield
    finally:
        await async_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version="2.0.0",
        lifespan=lifespan,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        responses={
            code: {"model": ErrorEnvelope, "description": description}
            for code, description in {
                400: "Сценарий не удовлетворяет игровым условиям",
                401: "Требуется действующая сессия",
                403: "Недостаточно прав",
                404: "Ресурс не найден",
                409: "Конфликт состояния или ревизии",
                422: "Нарушен контракт запроса",
                429: "Временное ограничение входа",
                500: "Ошибка сервиса или скоринга",
                503: "Сервис не готов",
            }.items()
        },
    )
    app.add_exception_handler(ApplicationError, error_handlers.api_error_handler)
    app.add_exception_handler(HTTPException, error_handlers.http_exception_handler)
    app.add_exception_handler(
        RequestValidationError, error_handlers.validation_exception_handler
    )
    app.add_exception_handler(Exception, error_handlers.unhandled_exception_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        candidate = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            candidate
            if 0 < len(candidate) <= 128
            and candidate.isascii()
            and candidate.isprintable()
            else str(uuid.uuid4())
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(health.router, tags=["Health"])
    for prefix, router in (
        ("auth", auth.router),
        ("rounds", rounds.router),
        ("admin", admin.router),
    ):
        app.include_router(
            router, prefix=f"{settings.API_V1_STR}/{prefix}", tags=[prefix.title()]
        )
    return app


app = create_app()
