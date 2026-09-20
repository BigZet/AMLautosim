import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(".local-run/ui-review-deps").resolve()))
from playwright.sync_api import sync_playwright
local=Path(".local-run/predeploy-2026-09-20");out=Path("docs/verification/predeploy-2026-09-20")
with sync_playwright() as p:
 b=p.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",headless=True)
 admin=b.new_context(storage_state=str(local/"admin-state.json"),viewport={"width":390,"height":844});a=admin.new_page();a.goto("http://127.0.0.1:18080/admin")
 a.get_by_role("tab",name="Игра",exact=True).click();a.wait_for_timeout(500)
 print("Mobile game tab", a.locator("body").inner_text())
 a.screenshot(path=str(out/"ui-admin-settings-mobile.png"))
 a.get_by_label("Цель исходящих операций",exact=True).fill("250000")
 a.get_by_role("button",name="Сохранить настройки",exact=True).click();a.wait_for_timeout(700)
 a.screenshot(path=str(out/"ui-admin-save-mismatch-mobile.png"))
 print("Admin save error",a.locator(".error-box").all_inner_texts())
 b.close()
