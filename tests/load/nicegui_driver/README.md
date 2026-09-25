# Reproducible proxy / Socket.IO load driver

Use Python 3.13 with `requirements-dev.txt` (NiceGUI 3.16.0,
python-socketio 5.16.4, httpx 0.28.1, psutil 7.2.2). The driver obtains the
real NiceGUI page and cookie, performs the WebSocket handshake, sends the
page's own input/button listener events and waits for server save status.
It does not instantiate GameEditor or call preview/save APIs directly.
This measures server UI round trips, **not browser paint or device latency**.

Build an image, then start a disposable lab:

```powershell
docker build -f deploy/Dockerfile -t aml-remediation:load .
python tests/load/nicegui_driver/lab.py start --image aml-remediation:load --directory .local-run/load-lab
$state = Get-Content .local-run/load-lab/private-state.json -Raw | ConvertFrom-Json
$env:METRICS_TOKEN = $state.metrics_token
python tests/load/nicegui_driver/runner.py --url $state.url --api $state.api --ui $state.ui --accounts .local-run/load-lab/accounts.json --users 60 --seconds 120 --output .local-run/load-60.json
python tests/load/nicegui_driver/lab.py stop --directory .local-run/load-lab
```

The lab publishes only loopback ephemeral ports. Its nginx source restriction
is relaxed **only in the generated local override**, never in production.
Private state contains disposable credentials; do not commit or publish it.
The lab helper records the exact local image ID and measures registration
separately. The driver records package versions, hardware, each successful,
failed or timed-out action, server metric samples, generator CPU/RSS and
host-wide network counters. Do not compare successful latency alone: report
all failures and actual connected-client counts. Generator network counters
include unrelated host traffic and must be labelled accordingly.

For steady-state baseline run 20/30/45/60 users; login concurrency defaults
to 5 for warmup. Use `--login-concurrency 60` for the separate simultaneous
login experiment. For soak use `--seconds 7200 --reconnect-every 20`.
Repeat final 45/60 runs three times, record image and worker/pool settings.
Keep failed reports; a harness fault is not evidence of application capacity.

Internal `/internal/metrics` requires `Authorization: Bearer <METRICS_TOKEN>`;
an unset token disables it. Nginx rejects `/internal/` even for trusted ingress
peers. Samples are process-local (PID included); when testing multiple API
workers retain samples for every PID rather than treating one as aggregate.
SQL durations omit statements/parameters. Acquisition timing includes connection
creation/pre-ping and near-zero reuse within a transaction. Histograms retain
the last 1024 samples plus lifetime count/sum; percentile windows are explicit.

For card payload comparison use fresh accounts with `--steps 1`, `8`, `16`
and `--structural`. The last add and a reorder are separate actions. Edits
respect the field's published min/max. `ws_message_bytes` counts incoming
and outgoing Socket.IO application envelopes plus Engine.IO message prefixes;
it excludes WebSocket framing/compression and heartbeat packets. Concurrent
application updates in the measurement interval are included. The exact driver
hash is recorded. Legacy T07 reports counted only update-event payloads and
must not be compared directly with this complete application-message counter.
