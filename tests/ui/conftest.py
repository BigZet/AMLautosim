"""Real stack for browser tests: PostgreSQL 16 + FastAPI + two Streamlit apps.

Everything runs as separate OS processes on its own database, so the browser
tests exercise exactly what a workshop participant would see. The stack can
restart individual services, which is how recovery from PostgreSQL is proven.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql://aml:aml@localhost:5432/postgres"
)
E2E_DB_NAME = os.environ.get("E2E_DATABASE_NAME", "aml_simulator_e2e")
E2E_DATABASE_URL = f"postgresql+asyncpg://aml:aml@localhost:5432/{E2E_DB_NAME}"
E2E_SYNC_DSN = f"postgresql://aml:aml@localhost:5432/{E2E_DB_NAME}"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin12345"
PARTICIPANT_PASSWORD = "correct-horse-42"

ARTIFACTS = ROOT / "tests" / "artifacts"

TABLES = (
    "audit_events",
    "leaderboard_adjustments",
    "scoring_results",
    "scenario_versions",
    "scenarios",
    "sessions",
    "round_presets",
    "rounds",
    "users",
    "action_cards",
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_http(url: str, timeout: float = 180.0, name: str = "service") -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(1.0)
    raise RuntimeError(f"{name} did not become reachable at {url}: {last}")


def _environment(api_url: str | None = None) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "DATABASE_URL": E2E_DATABASE_URL,
            "BOOTSTRAP_ADMIN_EMAIL": ADMIN_EMAIL,
            "BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
            "COOKIE_SECURE": "false",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(ROOT),
        }
    )
    if api_url:
        environment["API_URL"] = api_url
    return environment


class Stack:
    """Owns the API and both Streamlit processes for the whole session."""

    def __init__(self) -> None:
        self.api_port = free_port()
        self.play_port = free_port()
        self.admin_port = free_port()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._logs: dict[str, Any] = {}

    # -- URLs -------------------------------------------------------------
    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def play_url(self) -> str:
        return f"http://127.0.0.1:{self.play_port}"

    @property
    def admin_url(self) -> str:
        return f"http://127.0.0.1:{self.admin_port}"

    # -- process management ----------------------------------------------
    def _spawn(self, name: str, args: list[str], env: dict[str, str]) -> None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        handle = (ARTIFACTS / f"{name}.log").open("a", encoding="utf-8")
        self._logs[name] = handle
        self._processes[name] = subprocess.Popen(
            args, cwd=str(ROOT), env=env, stdout=handle, stderr=subprocess.STDOUT, text=True
        )

    def _stop(self, name: str) -> None:
        process = self._processes.pop(name, None)
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
        handle = self._logs.pop(name, None)
        if handle is not None:
            handle.close()

    def start_api(self) -> None:
        self._spawn(
            "api",
            [
                sys.executable, "-m", "uvicorn",
                "src.aml_workshop_simulator.api.main:app",
                "--host", "127.0.0.1", "--port", str(self.api_port),
                "--log-level", "warning",
            ],
            _environment(),
        )
        wait_for_http(f"{self.api_url}/health/ready", name="api")

    def start_ui(self, name: str, script: str, port: int) -> None:
        self._spawn(
            name,
            [
                sys.executable, "-m", "streamlit", "run", script,
                "--server.port", str(port), "--server.address", "127.0.0.1",
                "--server.headless", "true", "--browser.gatherUsageStats", "false",
            ],
            _environment(self.api_url),
        )
        wait_for_http(f"http://127.0.0.1:{port}", name=name)

    def start_all(self) -> None:
        self.start_api()
        self.start_ui("play", "src/aml_workshop_simulator/ui/participant/app.py", self.play_port)
        self.start_ui("admin", "src/aml_workshop_simulator/ui/admin/app.py", self.admin_port)

    def restart_api(self) -> None:
        self._stop("api")
        self.start_api()

    def stop_api(self) -> None:
        """Take the API down so the UI has to report an unreachable service."""
        self._stop("api")

    def restart_play(self) -> None:
        self._stop("play")
        self.start_ui("play", "src/aml_workshop_simulator/ui/participant/app.py", self.play_port)

    def stop_all(self) -> None:
        for name in list(self._processes):
            self._stop(name)

    # -- API access -------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        session_id: str | None = None,
    ) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.api_url}{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if session_id:
            request.add_header("X-Session-ID", session_id)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            payload = error.read()
            raise AssertionError(f"{method} {path} -> {error.code}: {payload!r}") from error


def _recreate_database() -> None:
    connection = psycopg2.connect(ADMIN_DSN)
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(E2E_DB_NAME)
                )
            )
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(E2E_DB_NAME)))
    finally:
        connection.close()


def _seed(migrate: bool, activate: bool = True) -> None:
    args = [sys.executable, "-m", "scripts.seed_database"]
    if activate:
        args.append("--activate-round")
    if migrate:
        args.append("--migrate")
    completed = subprocess.run(
        args,
        cwd=str(ROOT),
        env=_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    """One Chromium instance for every Playwright suite in the session.

    `sync_playwright()` cannot be started twice in the same thread, so the
    fixture lives here instead of being repeated in each test module.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as engine:
        instance = engine.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture(scope="session")
def stack() -> Iterator[Stack]:
    pytest.importorskip("streamlit")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    _recreate_database()
    _seed(migrate=True)

    instance = Stack()
    instance.start_all()
    try:
        yield instance
    finally:
        instance.stop_all()


def _truncate(attempts: int = 6) -> None:
    """Empty the tables, waiting out the live services.

    `TRUNCATE` needs an exclusive lock while the API and both Streamlit
    processes keep reading, so a first attempt can deadlock or time out. A
    bounded `lock_timeout` turns that into a retry instead of a failed test.
    """
    statement = "TRUNCATE TABLE " + ", ".join(TABLES) + " RESTART IDENTITY CASCADE"
    last: Exception | None = None
    for attempt in range(attempts):
        connection = psycopg2.connect(E2E_SYNC_DSN)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute(statement)
            return
        except (psycopg2.errors.LockNotAvailable, psycopg2.errors.DeadlockDetected) as error:
            last = error
            time.sleep(0.5 * (attempt + 1))
        finally:
            connection.close()
    raise AssertionError(f"could not truncate the test database: {last}")


@pytest.fixture()
def reset_state(stack: Stack) -> Iterator[Stack]:
    """Empty the E2E database and re-seed an active round before each test."""
    _truncate()
    _seed(migrate=False)
    yield stack


@pytest.fixture()
def draft_state(stack: Stack) -> Iterator[Stack]:
    """Like `reset_state`, but the seeded round is still waiting to be started."""
    _truncate()
    _seed(migrate=False, activate=False)
    yield stack


def unique_email(prefix: str = "p") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}@example.com"


def register(stack: Stack, display_name: str = "Игрок") -> dict[str, str]:
    email = f"p{uuid.uuid4().hex[:10]}@example.com"
    stack.request(
        "POST",
        "/api/v1/auth/register",
        {"email": email, "display_name": display_name, "password": PARTICIPANT_PASSWORD},
    )
    return {"email": email, "password": PARTICIPANT_PASSWORD, "display_name": display_name}


def db_execute(statement: str, params: tuple = ()) -> None:
    connection = psycopg2.connect(E2E_SYNC_DSN)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement, params)
    finally:
        connection.close()


def db_query(query: str, params: tuple = ()) -> list[tuple]:
    connection = psycopg2.connect(E2E_SYNC_DSN)
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()
    finally:
        connection.close()


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Mark a failed browser test so its fixture can save the artefacts."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        item._selenium_failed = True
