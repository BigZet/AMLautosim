import os
from typing import Any

import requests


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


class ApiError(RuntimeError):
    pass


def request(method: str, path: str, token: str | None = None, **kwargs: Any) -> Any:
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            headers=headers,
            timeout=15,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise ApiError(f"API недоступен: {API_BASE_URL}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(str(detail))
    if not response.content:
        return None
    return response.json()
