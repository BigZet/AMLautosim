"""Real PostgreSQL; each run owns and removes only its disposable database."""

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
pytest_plugins = ['scripts.ci_test_policy']
ADMIN_URL = make_url(
    os.getenv("TEST_ADMIN_DATABASE_URL", "postgresql://aml:aml@localhost:5432/postgres")
).set(drivername="postgresql")
DATABASE_NAME = f"aml_test_{uuid4().hex}"
os.environ.update(
    DATABASE_URL=ADMIN_URL.set(
        drivername="postgresql+asyncpg", database=DATABASE_NAME
    ).render_as_string(hide_password=False),
    DB_POOL_DISABLED="true",
    BOOTSTRAP_ADMIN_EMAIL="admin@example.com",
    BOOTSTRAP_ADMIN_PASSWORD="admin12345",
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from scripts.seed_database import run_migrations, seed  # noqa: E402
from src.aml_workshop_simulator.api.main import app  # noqa: E402
from src.aml_workshop_simulator.db.session import AsyncSessionLocal  # noqa: E402


async def execute(statement, parameters=None):
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(statement), parameters or {})
        rows = result.mappings().all() if result.returns_rows else []
        await db.commit()
        return rows


@pytest.fixture(autouse=True)
def isolated_ui_storage(tmp_path, monkeypatch):
    """User simulation must never clear a developer's real NiceGUI sessions."""
    from nicegui.storage import Storage
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")


@pytest.fixture(scope="session")
def database():
    async def manage(create):
        conn = await asyncpg.connect(ADMIN_URL.render_as_string(hide_password=False))
        try:
            if create:
                await conn.execute(f'CREATE DATABASE "{DATABASE_NAME}"')
            else:
                await conn.execute(f'DROP DATABASE "{DATABASE_NAME}" WITH (FORCE)')
        finally:
            await conn.close()

    asyncio.run(manage(True))
    try:
        run_migrations()
        yield
    finally:
        asyncio.run(manage(False))


@pytest.fixture
def seeded_game_version():
    """All API regressions use the current v10 release."""
    return 10


@pytest.fixture
def api(database, seeded_game_version):
    front = sys.modules.get('src.aml_workshop_simulator.ui.nicegui.app')
    if front is not None:
        front.login_limiter.states.clear()
    asyncio.run(
        execute("TRUNCATE action_cards, users, rounds, auth_rate_limits RESTART IDENTITY CASCADE")
    )
    assert seeded_game_version == 10
    asyncio.run(seed())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def request_api(api):
    def request(method, path, headers=None, body=None, status=200):
        response = api.request(method, "/api/v1" + path, headers=headers, json=body)
        assert response.status_code == status, response.text
        return response.json() if response.content else None

    return request


@pytest.fixture
def scoring_worker(api):
    """Real queue consumer for explicit legacy wait-mode and UI regressions.

    The default202 contract and crash tests deliberately do not use this fixture.
    """
    from src.aml_workshop_simulator.services.scoring_jobs import worker_loop

    async def start():
        stop = asyncio.Event()
        task = asyncio.create_task(worker_loop(AsyncSessionLocal, stop, 0.1))
        return stop, task

    stop, task = api.portal.call(start)
    yield

    async def finish():
        stop.set()
        await asyncio.wait_for(task, 15)

    api.portal.call(finish)


@pytest.fixture
def admin(request_api):
    session = request_api(
        "POST",
        "/auth/login",
        body={
            "email": "admin@example.com",
            "password": "admin12345",
            "audience": "admin",
        },
    )
    return {"X-Session-ID": session["session_id"]}


@pytest.fixture
def player_factory(request_api):
    def create(name="Участник", password="participant123"):
        email = f"{uuid4().hex}@example.com"
        user = request_api(
            "POST",
            "/auth/register",
            body={
                "email": email,
                "password": password,
                "display_name": name,
            },
            status=201,
        )
        session = request_api(
            "POST", "/auth/login", body={"email": email, "password": password}
        )
        return {**user, "headers": {"X-Session-ID": session["session_id"]}}

    return create


@pytest.fixture
def player(player_factory):
    return player_factory()


@pytest.fixture
def round_id(request_api, admin):
    return request_api("GET", "/admin/rounds/current", admin)["id"]


@pytest.fixture
def active_round(request_api, admin, round_id):
    request_api("POST", f"/admin/rounds/{round_id}/start", admin)
    return round_id


@pytest.fixture
def chain(request_api, admin, round_id):
    from scripts.check_expanded_balance import demo_steps

    config = request_api("GET", "/admin/rounds/current", admin)["game_config"]

    def build(count=9):
        if config["schema_version"] == 10:
            import json

            steps = json.loads(
                (ROOT / "tests/fixtures/game_classifier_chain.json").read_text(
                    encoding="utf-8"
                )
            )[:count]
            cards = {
                (c["code"], c["version"]): c["id"] for c in config["card_snapshots"]
            }
            for step in steps:
                step["card"]["id"] = cards[
                    (step["card"]["code"], step["card"]["version"])
                ]
        else:
            steps = demo_steps(config)[:count]
        for step in steps:
            step["step_id"] = str(uuid4())
        return steps

    return build


@pytest.fixture
def command():
    return lambda steps, revision=0: dict(
        steps=steps, expected_revision=revision, client_mutation_id=str(uuid4())
    )


@pytest.fixture
def install_test_worker_calculator(monkeypatch):
    """Explicit offline/schema-4 fixture support, never a production fallback."""
    from types import SimpleNamespace
    from src.aml_workshop_simulator.services import scoring_jobs
    from src.aml_workshop_simulator.services.scenario_service import load_round_card_specs, round_policy

    def install(factory):
        def initialize(config):
            row = SimpleNamespace(game_config=config)
            specs = load_round_card_specs(row)
            scoring_jobs._thread.calculator = (specs, config, round_policy(row, specs), factory())
        monkeypatch.setattr(scoring_jobs, 'initialize_calculator', initialize)
    return install


@pytest.fixture
def sql(api):
    return lambda statement, parameters=None: api.portal.call(
        execute, statement, parameters
    )


@pytest.fixture(params=["removed_field", "salary_channel", "inverted_range"])
def invalid_game_config(request):
    from src.aml_workshop_simulator.core.game_config import base_game_config

    config = base_game_config()
    operation = next(
        o for o in config["operations"] if o["code"] == "incoming_transfer"
    )
    if request.param == "removed_field":
        operation["visible_params"] = ["action.funds_source"]
        message = "не объявлен"
    elif request.param == "salary_channel":
        operation = next(o for o in config["operations"] if o["code"] == "salary")
        operation["visible_params"] = ["channel"]
        message = "не объявлен"
    else:
        operation["min_amount"] = "90000.00"
        message = "минимальная сумма больше максимальной"
    return config, message


@pytest.fixture
def invalid_expanded_game_config(invalid_game_config):
    from src.aml_workshop_simulator.services.game_classifier import game_config

    invalid, message = invalid_game_config
    config = game_config()
    for operation in invalid["operations"]:
        if (
            operation.get("visible_params") in (["action.funds_source"], ["channel"])
            and operation["code"] in ("incoming_transfer", "salary")
        ) or operation.get("min_amount") == "90000.00":
            target = next(
                o for o in config["operations"] if o["code"] == operation["code"]
            )
            if operation.get("min_amount") == "90000.00":
                from decimal import Decimal
                target["min_amount"] = str(Decimal(target["max_amount"]) + 1)
            else:
                target["visible_params"] = operation["visible_params"]
    return config, message
