"""Real browsers against an explicitly selected disposable workshop."""

import json
import os
import re
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def capture(request):
    def save(page, state):
        directory = os.environ.get("BROWSER_EVIDENCE_DIR")
        if directory:
            destination = Path(directory)
            channel = request.config.getoption("--browser-channel")
            if channel:
                destination = destination / channel
            destination.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^a-zA-Z0-9_-]", "-", request.node.name)
            page.screenshot(
                path=str(destination / f"{name}-{state}.png"), full_page=True
            )

    return save


@pytest.fixture(autouse=True)
def javascript_errors(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert not errors


@pytest.fixture(scope="session")
def admin_api(workshop):
    with httpx.Client(base_url=workshop["api"] + "/api/v1", timeout=120) as api:
        response = api.post(
            "/auth/login",
            json={
                "email": "admin@example.com",
                "password": workshop["environment"]["AML_CI_ADMIN_PASSWORD"],
                "audience": "admin",
            },
        )
        response.raise_for_status()
        api.headers["X-Session-ID"] = response.json()["session_id"]
        yield api


@pytest.fixture
def scoring_participant(request, admin_api, page):
    current = admin_api.get("/admin/rounds/current").json()
    response = admin_api.post(f"/admin/rounds/{current['id']}/restart")
    response.raise_for_status()
    current = response.json()
    config = {
        k: v
        for k, v in current["game_config"].items()
        if k not in {"risk_model", "config_version", "card_snapshots"}
    }
    config["objectives"]["target_outflow"] = "10000.00"
    admin_api.put(
        f"/admin/rounds/{current['id']}",
        json={
            "expected_config_revision": current["config_revision"],
            "game_config": config,
        },
    ).raise_for_status()
    admin_api.post(f"/admin/rounds/{current['id']}/start").raise_for_status()
    return request.getfixturevalue("participant")


@pytest.fixture(scope="session")
def workshop():
    path = os.environ.get("BROWSER_LAB_DIRECTORY")
    if not path:
        pytest.fail("BROWSER_LAB_DIRECTORY must name a disposable load lab")
    state = json.loads((Path(path) / "private-state.json").read_text())
    if not state["project"].startswith("aml-load-"):
        pytest.fail("Browser tests require a disposable aml-load project")
    return state


@pytest.fixture
def participant(page, workshop, admin_api):
    current = admin_api.get("/admin/rounds/current").json()
    if current["status"] != "active":
        response = admin_api.post(f"/admin/rounds/{current['id']}/restart")
        response.raise_for_status()
        admin_api.post(
            f"/admin/rounds/{response.json()['id']}/start"
        ).raise_for_status()
    account = {
        "email": f"browser-{uuid4().hex}@example.com",
        "password": uuid4().hex,
        "display_name": "Участник с длинным именем для проверки адаптивности",
    }
    with httpx.Client(base_url=workshop["api"] + "/api/v1", timeout=60) as api:
        api.post("/auth/register", json=account).raise_for_status()
    page.goto(workshop["url"] + "/play/login")
    page.get_by_label("Email", exact=True).fill(account["email"])
    page.get_by_label("Пароль", exact=True).fill(account["password"])
    page.get_by_role("button", name="Войти", exact=True).click()
    page.wait_for_url("**/play")
    page.get_by_role("button", name="Добавить операцию", exact=True).wait_for()
    return page
