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
 page.get_by_role("button",name="Зарплата",exact=True).click();page.wait_for_timeout(500)
 page.get_by_role("button",name="Перевод по карте",exact=True).click();page.wait_for_timeout(500)
 card=page.locator(".operation-card").first
 card.get_by_label("Сумма",exact=True).fill("15000");card.get_by_label("Сумма",exact=True).press("Tab")
 card.get_by_label("Получатель",exact=True).click()
 page.get_by_role("option").filter(has_text="Борис").click()
 page.wait_for_timeout(400)
 assert "Борис" in card.locator(".operation-caption").inner_text()
 card.locator(".q-item").first.click()
 assert card.get_by_role("button",name="Копировать операцию",exact=True).is_visible()
 card.get_by_role("button",name="Копировать операцию",exact=True).click();page.wait_for_timeout(300)
 assert page.locator(".operation-card").count()==3
 page.locator(".operation-card").first.get_by_role("button",name="Удалить операцию",exact=True).click();page.wait_for_timeout(300)
 assert page.locator(".operation-card").count()==2
 page.wait_for_timeout(1600);page.reload();page.locator(".operation-card").first.wait_for()
 assert page.locator(".operation-card").count()==2
 assert "Борис" in page.locator(".operation-card").first.inner_text()
 page.screenshot(path=str(out/"ui-editor-actions-desktop.png"))
 for path,name in [("/play/profile","profile"),("/play/limits","limits"),("/play","editor")]:
  page.goto("http://127.0.0.1:18080"+path);page.locator(".participant-nav").wait_for();page.wait_for_timeout(250)
  page.set_viewport_size({"width":390,"height":844});page.wait_for_timeout(250)
  print(name,"mobile_overflow",page.evaluate("document.documentElement.scrollWidth > innerWidth"))
  page.screenshot(path=str(out/("ui-"+name+"-mobile.png")))
  page.set_viewport_size({"width":1440,"height":1000})
 print("Header updates, collapsed copy/delete, autosave/reload passed; browser errors",errors)
 ctx.storage_state(path=str(local/"player-state.json"));b.close()
