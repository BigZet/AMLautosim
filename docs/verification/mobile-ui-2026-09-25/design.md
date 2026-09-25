# Mobile workshop design — 2026-09-25

The 390 px baseline places the save state and submission reason after eight
cards (about 1800 px down the page). All six tested widths avoid horizontal
overflow, but 33 visible buttons are smaller than the 44 px target. Secondary
card commands are icon-only. Screenshots and `before-layout.json` preserve
the observed baseline, using the T10 disposable image.

Use the same data and handlers at every width. At 320–700 px use one column:
compact goal, save/error state and current primary action first; resource
balance and operation picker next; the chain below. Full conditions, history
and explanation are expandable. At desktop keep the summary beside the chain.
No fixed bottom overlay: the keyboard and safe area cannot cover the last field.

| State | 360 / 390 px composition | Primary action |
| --- | --- | --- |
| Empty | Goal, short instruction, operation choices, empty chain | Add operation |
| Editing | Goal/status/reason, resources, one open operation, other summaries | Send when valid |
| Invalid | Short visible reason, expandable condition details, linked step | Correct the named field |
| Saving / offline | Persistent text status, retry on transport failure | Retry when needed |
| Submitted | Confirmation and waiting message, read-only chain | Wait |
| Result | Score/rank, expandable explanation, own ranking row | Explore result |

Operation headers retain amount and time. One open editor at a time reduces
scrolling; a labelled Actions menu contains copy/delete and explicit earlier/
later commands. Touch targets are at least 44×44 px; focus outlines and zoom
remain enabled. Dialogs scroll within available dynamic viewport height.
Long emails/names wrap. Truly two-dimensional tables retain labelled local
scroll containers rather than widening the document.

Browser screenshots at 360/390 and desktop will be the rendered mockups and
acceptance evidence. Chromium/Firefox/WebKit automation is separate from
real iPhone Safari/Android Chrome and macOS Safari; unavailable environments
remain explicitly unverified. No production browser interactions are used.
