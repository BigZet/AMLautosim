from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.aml_workshop_simulator.api.routers import admin, auth, health, rounds
from src.aml_workshop_simulator.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_and_timing_middleware(
        request: Request, call_next: Any) -> Any:
    request_id = request.headers.get(
        "X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id
    start_time = time.time()

    response = await call_next(request)

    process_time = time.time() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.4f}"
    return response


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
        request: Request,
        exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": "http_error",
            "message": str(exc.detail),
            "details": None,
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id} if request_id else None,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "validation_error",
            "message": "Некорректные параметры запроса",
            "details": {"errors": exc.errors()},
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id} if request_id else None,
    )


# Health checks (unversioned per docs/api.md)
app.include_router(health.router, tags=["Health"])

# Application routers
app.include_router(
    auth.router,
    prefix=f"{
        settings.API_V1_STR}/auth",
    tags=["Auth"])
app.include_router(
    rounds.router,
    prefix=f"{
        settings.API_V1_STR}/rounds",
    tags=["Rounds & Participant"])
app.include_router(
    admin.router,
    prefix=f"{
        settings.API_V1_STR}/admin",
    tags=["Admin"])
