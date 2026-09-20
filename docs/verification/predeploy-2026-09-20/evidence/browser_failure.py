import sys,json,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(".local-run/ui-review-deps").resolve()))
from playwright.sync_api import sync_playwright
local=Path(".local-run/predeploy-2026-09-20");out=Path("docs/verification/predeploy-2026-09-20")
s=json.loads((local/"settings.json").read_text())
with sync_playwright() as p:
 b=p.chromium.launch(executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe",headless=True)
 ctx=b.new_context(storage_state=str(local/"player-state.json"),viewport={"width":390,"height":844});page=ctx.new_page();page.goto("http://127.0.0.1:18080/play")
 page.locator(".waiting-hero").wait_for()
 admin=b.new_context(storage_state=str(local/"admin-state.json"),viewport={"width":1440,"height":1000});a=admin.new_page();a.goto("http://127.0.0.1:18080/admin")
 a.get_by_text("Ошибка расчёта. Приём закрыт; скоринг можно повторить.",exact=False).wait_for(timeout=10000)
 page.wait_for_timeout(3500)
 print("Participant after failure:",page.locator(".waiting-hero").inner_text())
 assert "Сценарий принят" in page.locator(".waiting-hero").inner_text()
 assert page.locator(".participant-nav").count()==0
 page.screenshot(path=str(out/"ui-failure-player-mobile.png"));a.screenshot(path=str(out/"ui-failure-admin-desktop.png"))
 counts=subprocess.check_output(["docker","exec","aml-predeploy-20260920-db-1","psql","-U",s["POSTGRES_USER"],"-d",s["POSTGRES_DB"],"-Atc","SELECT (SELECT count(*) FROM scoring_results), (SELECT count(*) FROM scenarios WHERE status='submitted');"],text=True).strip()
 assert counts=="0|2",counts;print("After failure: 0 results, 2 submitted chains")
 print("Admin controls:",a.locator("body").inner_text()[:650])
 button=a.get_by_role("button",name="Повторить скоринг",exact=True)
 if not button.count():button=a.get_by_role("button",name="Запустить скоринг",exact=True)
 button.click();a.get_by_role("button",name="Подтвердить",exact=True).click()
 page.locator(".result-hero").wait_for(timeout=30000)
 print("Retry restored participant result automatically")
 page.screenshot(path=str(out/"ui-retry-result-mobile.png"))
 b.close()
