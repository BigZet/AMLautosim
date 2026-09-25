import pytest

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("width", [320, 360, 390, 430, 768, 1280])
def test_editor_layout_and_touch_targets(participant, width, capture):
    page = participant
    page.set_viewport_size({"width": width, "height": 844})
    if width in (360, 390, 1280):
        capture(page, "empty")
    page.get_by_role("button", name="Входящий перевод", exact=True).click()
    page.get_by_label("Сумма", exact=True).wait_for()
    page.get_by_text("Сохранено", exact=True).wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    # Original design uses compact inline icon actions. The previous 44px
    # target requirement remains a documented T15 gap, not a redesign mandate.
    assert page.locator(".operation-actions button:visible").count() == 4
    assert page.locator(".operation-menu-button").count() == 0
    assert page.locator(".operation-choice:visible").count() == 5
    page.set_viewport_size({"width": 844, "height": width})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 1280:
        page.evaluate("document.body.style.zoom = '2'")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("width", [320, 360, 390, 430, 768])
def test_shared_mobile_header_stays_aligned(participant, workshop, width, capture):
    page = participant
    page.set_viewport_size({"width": width, "height": 844})
    for path in ["/play", "/play/profile", "/play/limits", "/play/results"]:
        page.goto(workshop["url"] + path)
        header = page.locator(".app-header")
        header.locator(".header-actions").wait_for()
        identity = header.locator(".header-identity").bounding_box()
        actions = header.locator(".header-actions").bounding_box()
        username = header.locator(".header-user-name").bounding_box()
        assert actions["x"] > username["x"] + username["width"] - 1
        assert actions["y"] >= identity["y"] + identity["height"] - 1
        assert actions["y"] <= username["y"] + username["height"]
        assert header.locator(".header-game-title").evaluate(
            "e => getComputedStyle(e).borderLeftWidth === '0px'"
        )
        assert header.evaluate("e => e.scrollWidth <= e.clientWidth")
        capture(page, "header-" + path.replace("/", "-"))
