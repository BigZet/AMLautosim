import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(".local-run/ui-review-deps").resolve()))
from playwright.sync_api import sync_playwright
local=Path(".local-run/predeploy-2026-09-20");out=Path("docs/verification/predeploy-2026-09-20")
with sync_playwright() as p:
 b=p.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",headless=True)
 ctx=b.new_context(storage_state=str(local/"player-state.json"),viewport={"width":1440,"height":1000});page=ctx.new_page()
 errors=[];page.on("pageerror",lambda e:errors.append(str(e)));page.on("console",lambda e:errors.append(e.text) if e.type=="error" else None)
 page.goto("http://127.0.0.1:18080/play")
 page.get_by_role("button",name="Отправить сценарий",exact=True).click()
 page.get_by_role("button",name="Отправить",exact=True).click()
 page.locator(".waiting-hero").wait_for()
 assert page.locator(".participant-nav").count()==0
 page.screenshot(path=str(out/"ui-submitted-desktop.png"))
 page.set_viewport_size({"width":390,"height":844});page.wait_for_timeout(200)
 assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
 page.screenshot(path=str(out/"ui-submitted-mobile.png"))
 admin=b.new_context(storage_state=str(local/"admin-state.json"));a=admin.new_page()
 a.goto("http://127.0.0.1:18080/admin")
 a.get_by_role("button",name="Запустить скоринг",exact=True).click()
 a.get_by_role("button",name="Подтвердить",exact=True).click()
 page.locator(".result-hero").wait_for(timeout=30000)
 assert page.locator(".participant-nav").count()==0
 assert page.locator(".score-breakdown").is_visible()
 page.screenshot(path=str(out/"ui-results-mobile.png"))
 page.locator(".shap-panel").screenshot(path=str(out/"ui-shap-mobile.png"))
 for tab in page.locator(".shap-tabs .q-tab").all():
  assert "%" not in tab.inner_text()
  tab.click();page.wait_for_timeout(400)
  table=page.locator(".shap-table:visible")
  assert table.locator("tbody tr").count()==28
  before=table.locator("tbody tr").evaluate_all("rows=>rows.map(r=>r.cells[2].innerText)")
  table.locator("th").nth(2).click();page.wait_for_timeout(150)
  after=table.locator("tbody tr").evaluate_all("rows=>rows.map(r=>r.cells[2].innerText)")
  assert after==list(reversed(before))
 page.set_viewport_size({"width":1440,"height":1000});page.wait_for_timeout(200)
 page.locator(".result-hero").scroll_into_view_if_needed();page.screenshot(path=str(out/"ui-results-desktop.png"))
 for route in ["/play/profile","/play/limits","/play/results"]:
  page.goto("http://127.0.0.1:18080"+route);page.locator(".result-hero").wait_for();assert page.locator(".participant-nav").count()==0
 page.reload();page.locator(".result-hero").wait_for()
 print("Submission, hidden navigation, automatic result, open score calculation, all 3 SHAP windows/28 rows/sort and reload passed")
 print("Browser errors",errors)
 b.close()
