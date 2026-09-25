import pytest

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("width", [320, 360, 390, 430, 768, 1280])
def test_editor_layout_and_touch_targets(participant, width, capture):
    page = participant
    page.set_viewport_size({"width": width, "height": 844})
    if width in (360, 390, 1280):
        capture(page, "empty")
    page.get_by_role("button", name="Добавить операцию", exact=True).click()
    page.get_by_role("button", name="Входящий перевод", exact=True).click()
    page.get_by_label("Сумма", exact=True).wait_for()
    page.get_by_text("Сохранено", exact=True).wait_for()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    small = page.locator(
        ".operation-actions button:visible, .header-exit, .operation-choice"
    ).evaluate_all(
        "els => els.filter(e => e.getBoundingClientRect().width < 44 || e.getBoundingClientRect().height < 44).map(e => e.getAttribute('aria-label') || e.innerText)"
    )
    assert small == []
    if width <= 430:
        assert page.locator(".save-indicator").bounding_box()["y"] < 844
    page.set_viewport_size({"width": 844, "height": width})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 1280:
        page.evaluate("document.body.style.zoom = '2'")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
