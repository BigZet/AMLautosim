"""FastAPI composition root."""

import uuid
import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.routing import iter_route_contexts
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy.exc import TimeoutError as PoolTimeout

from src.aml_workshop_simulator.api import error_handlers
from src.aml_workshop_simulator.api.routers import admin, auth, health, rounds
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.version import SERVICE_VERSION
from src.aml_workshop_simulator.core.errors import ApplicationError
from src.aml_workshop_simulator.core.observability import metrics, correlation_id, request_log, sample_loop, stop_sampler, configure_logging
from src.aml_workshop_simulator.db.session import async_engine
from src.aml_workshop_simulator.schemas.catalog_config import (
    validate_configuration_files,
)
from src.aml_workshop_simulator.schemas.common import ErrorEnvelope


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    validate_configuration_files()
    from src.aml_workshop_simulator.services.game_classifier import get_game_classifier

    get_game_classifier()
    sampler = asyncio.create_task(sample_loop())
    try:
        yield
    finally:
        await stop_sampler(sampler)
        await async_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=SERVICE_VERSION,
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
    app.add_exception_handler(PoolTimeout, error_handlers.database_busy_handler)
    app.add_exception_handler(HTTPException, error_handlers.http_exception_handler)
    app.add_exception_handler(
        RequestValidationError, error_handlers.validation_exception_handler
    )
    app.add_exception_handler(Exception, error_handlers.unhandled_exception_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        client_id = correlation_id(request.headers.get("X-Request-ID", ""))
        request.state.correlation_id = client_id
        started = time.monotonic()
        status = 500
        metrics.add('http_in_flight', 1)
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            duration = time.monotonic() - started
            route = route_templates.get(request.scope.get('endpoint'), 'unmatched')
            method = request.method if request.method in {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'} else 'OTHER'
            metrics.observe(f'http {method} {route} {status}', duration)
            metrics.add('http_in_flight', -1)
            request_log(request.state.request_id, client_id, route, status, duration)

    app.include_router(health.router, tags=["Health"])
    for prefix, router in (
        ("auth", auth.router),
        ("rounds", rounds.router),
        ("admin", admin.router),
    ):
        app.include_router(
            router, prefix=f"{settings.API_V1_STR}/{prefix}", tags=[prefix.title()]
        )
    route_templates = {route.endpoint: route.path for route in iter_route_contexts(app.routes)}
    return app


app = create_app()
