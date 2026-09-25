# Browser evidence — 2026-09-25

Host: Windows 11; Python 3.13.15; Playwright 1.63.0; pytest-playwright 0.9.0.
Disposable PostgreSQL 16 / nginx / API / single NiceGUI process; image
`sha256:4e51e23853e444596fe758d4c27a6d56d2fcc805e26018c5dc8833026f2e3250`
built from UI commit `ac11c78`. No production updates or browser interactions.

| Environment | Scope | Status |
| --- | --- | --- |
| Chromium 153.0.8010.12, build 1243, Windows | 320/360/390/430/768/1280; landscape; desktop CSS zoom 200%; complete participant/organizer path | Passed: 12 cases |
| Firefox 155.0, build 1543, Windows | Same automated matrix | Passed: 12 cases |
| WebKit 26.6, build 2359, Windows | Same automated matrix | Passed: 12 cases |
| Chrome 153.0.8010.50, Windows | Native installed channel | Passed: 12 cases |
| Edge 153.0.4234.48, Windows | Native installed channel | Passed: 12 cases |
| iPhone / Safari | Hardware keyboard, safe-area, browser toolbar, background/return, reconnect | **Unverified: no real device/service available** |
| Android / Chrome | Hardware keyboard, touch, long chain, dialogs | **Unverified: no real device/service available** |
| macOS / Safari | Native Safari browser | **Unverified: no macOS host available** |

Automation checks registration/login, add/edit/copy/delete/reorder, invalid
amount correction, comma/dot amounts, save confirmation, focus/caret and
viewport position, saved-draft reconnect, submit, organizer score and published
result after reload. Setup configures a small scoring target through the API;
scoring itself is initiated from the organizer UI. Conditions and model details
remain available on demand. The real device rows are not inferred from viewport
emulation. CSS zoom does not verify operating-system text scaling.

Before screenshots preserve the eight-step baseline; after screenshots and
`states/` show the resulting UI. `payload.json` and compressed raw action reports
use complete bidirectional application-message counting (see driver README).
At 8 steps the largest ordinary edit was 15,262 bytes; at 16 steps 18,655 bytes.
All final payload actions succeeded. Adding/reordering are reported separately.

Earlier diagnostic runs remain in the execution ledger: a damaged pre-existing
Firefox installation was replaced by an isolated clean browser cache; repeated
administrator setup logins correctly reached the rate limit and were replaced
with a reused setup session; viewport-position assertions account for native
scroll anchoring. Earlier WebKit first-click timeouts were intermittent. A separate regression
proved overlapping reconnect/timer polls could render stale empty state;
screen polls now serialize and the initial preview precedes the first render.
Two subsequent complete 36-case matrices passed (working overlay, then immutable
image), without click retries. This evidence does not prove every earlier
WebKit timeout had the same cause. No retries or weakened rate limits are enabled.

The PR remains draft while mandatory acceptance is incomplete.
