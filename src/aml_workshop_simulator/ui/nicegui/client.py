"""Asynchronous API transport; credentials are always scoped to one request."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4
import time

import httpx
from src.aml_workshop_simulator.core.observability import metrics

SESSION_ERRORS = {
    "session_missing",
    "session_invalid",
    "session_expired",
    "session_revoked",
}


@dataclass
class APIError(Exception):
    message: str
    code: str = "api_error"
    status: int = 0
    details: dict | None = None
    request_id: str | None = None
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.message


class APIClient:
    def __init__(self, base_url: str, *, transport=None, auth_context_secret=None):
        self.auth_context_secret = auth_context_secret
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            transport=transport,
            timeout=httpx.Timeout(15, connect=5),
            limits=httpx.Limits(max_connections=80, max_keepalive_connections=30),
        )

    async def close(self):
        await self.http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        session_id: str | None = None,
        body: dict | None = None,
        params: dict | None = None,
        timeout: float = 15,
        auth_client_ip: str | None = None,
    ) -> Any:
        request_id = str(uuid4())
        headers = {"X-Request-ID": request_id}
        if session_id:
            headers["X-Session-ID"] = session_id
        if auth_client_ip and self.auth_context_secret and path.strip('/') in ('auth/login', 'auth/register'):
            from src.aml_workshop_simulator.core.client_context import sign_context
            headers.update(sign_context(auth_client_ip, path.rsplit('/', 1)[-1],
                                        str((body or {}).get('email', '')), self.auth_context_secret))
        started = time.monotonic()
        metrics.add('ui_api_in_flight', 1)
        try:
            response = await self.http.request(
                method,
                path.lstrip("/"),
                headers=headers,
                json=body,
                params=params,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise APIError(
                "Нет связи с сервером. Проверьте соединение и повторите попытку.",
                code="connection_error",
                request_id=request_id,
            ) from exc
        finally:
            metrics.add('ui_api_in_flight', -1)
            metrics.observe('ui_api_seconds', time.monotonic() - started)
        response_id = response.headers.get("X-Request-ID", request_id)
        if response.status_code == 204:
            return None
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.is_error:
            error = data if isinstance(data, dict) else {}
            retry = response.headers.get("Retry-After", "")
            raise APIError(
                message=error.get("message")
                or "Сервер временно недоступен. Повторите попытку.",
                code=error.get("code", "api_error"),
                status=response.status_code,
                details=error.get("details"),
                request_id=error.get("request_id") or response_id,
                retry_after=int(retry) if retry.isdigit() else None,
            )
        if data is None and response.content.strip() != b"null":
            raise APIError(
                "Сервер вернул неожиданный ответ.",
                code="invalid_response",
                request_id=response_id,
            )
        return data
