# Browser acceptance

Use Python 3.13, `requirements-browser.txt`, and Playwright's pinned browser
builds (`python -m playwright install --with-deps chromium firefox webkit`).
On Windows omit `--with-deps`. `PLAYWRIGHT_BROWSERS_PATH` can point to a clean
local cache; a broken previously installed browser is not an application failure.

Build the current image and start a disposable lab using
`tests/load/nicegui_driver/lab.py start --image IMAGE --directory .local-run/browser`.
Set `BROWSER_LAB_DIRECTORY=.local-run/browser`, then run:

```
python -m pytest tests/browser -q --browser chromium --browser firefox --browser webkit
```

Tests restart the lab's round and create disposable accounts. Never point them
at production. Run sequentially: the tests deliberately share a single-game
workshop, so xdist/parallel jobs require separate labs. An administrator session
is reused by setup; repeated admin logins must not disable or bypass rate limits.
Participant registration, login, editing, copy/delete/reorder, error correction,
submission and organizer scoring use the actual UI. Setup alone uses the API
to set a small target. The result path also accepts later asynchronous scoring.

`BROWSER_EVIDENCE_DIR` optionally saves screenshots of empty, invalid, editing,
submitted and result states. Credentials/private lab state must not be uploaded.
CI publishes JUnit, suite classification and failure screenshots, not traces
containing form credentials. Native Chrome/Edge can run separately with
`--browser chromium --browser-channel chrome` or `msedge`.

Layout covers 320/360/390/430/768/1280 CSS px and landscape, 200% desktop CSS
zoom, 44 px primary/operation targets and document overflow. Focus, text caret,
dot/comma entry and saved-draft recovery after offline/reload are browser tests.
CSS zoom is not OS text scaling; synthetic offline is not a phone radio test.
Actual iOS/Android keyboards, safe areas and browser chrome remain real-device
checks. WebKit on Windows/Linux does not establish Safari support on iPhone/macOS.
