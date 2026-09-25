# Remediation execution evidence

Base: `5fc9dcc69f3b8a1f7ce2fed5f2aac20fa90be012`. Isolated branch:
`codex/review-remediation-2026-09-25`. No production changes.

## T00 — baseline

See baseline.md, baseline-results.json and sanitized production-inventory.json.
Original working directories and uncommitted reports were preserved.

## T01 — package integrity

Commits `10aa3b0`, `adad110`. Target regressions: 33 passed, one Windows
symlink privilege skip. Both fresh LF and Windows checkouts load the default
v10 and legacy v8 packages. The 25 frozen original predictions (features,
probabilities and full explanations) are unchanged; the original saved pin is
accepted. Publisher follow-up regressions: four passed. Artifact bytes unchanged.

## T02 — explicit CI suites

Python 3.13.15, disposable PostgreSQL 16, locked runtime/research/audit environments.
Windows runtime: **583 passed, one symlink skip**, 449 research cases deselected;
runtime inventory verified. Ruff passed. Linux image readiness and an actual
NiceGUI WebSocket handshake passed (`python -m scripts.ci_smoke`).

The research environment reproduces **71 failures, 11 setup errors, 367 passes**;
all 82 failing node IDs and reasons are recorded in tests/research-baseline.json.
The baseline checker rejects new failures, collection failures, disappearing
tests and skipped known failures. Runtime tests are never baseline-exempt.

Runtime and ML dependency audits completed successfully with no known
vulnerabilities. Windows cache-write warnings did not affect audit results.
An initial Linux API run lacked test-only archived fixtures in its container
mounts (158 passes, six failures, one setup error); rerun with those fixtures
passed all 165 API tests. These fixtures are available in the CI checkout and
are not added to the production image. Draft PR #3 is open. Remote run
36078739342 passed Linux and Windows runtime, image and research-baseline jobs;
run 36078739381 passed dependency audit. API job was still running at this checkpoint.

## T03 — reproducible delivery and readiness

Target regression: 31 passed, one Windows symlink skip. Missing legacy startup
and missing saved model were reproduced before the fix. Default v10 and saved
round packages are checked; legacy is lazy. Paths are rooted at the project;
UI settings validate URLs, ports and storage. Source compatibility re-release
replayed all 25 chains unchanged and preserved both previous default pins.

Python base is pinned to registry index
`sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0`.
Manual release workflow builds once, smoke-checks, then pushes the same image
with OCI revision/source and records its registry digest. Production compose
has a separate one-shot migration/seed service, no host config overlay, and
private API/DB ports. The local T03 image passed clean-install readiness,
pg_dump/pg_restore into a separate disposable DB, repeated release preserving
accounts, cookie checks and actual WebSocket handshake. Production database
copy and registry publication are not claimed as completed by this local check.

Raw local JUnit, JSON reports and logs are under
`.superpowers/sdd/2026-09-25-review-remediation/`; CI uploads reports as artifacts.

## Remaining acceptance

T04 targeted suite: 41 passed; legacy/disabled-purchase and supported-version
boundary additions: four passed. RED reproduced 13 failures before changes.
Purchase counts use the effective card override, versions are restricted to
8/10 before loading config or acquiring restart locks. All 25 full model
replays remained identical after the controlled source compatibility release.

T05: three regressions reproduced before changes. Main suite 35 passed; final
audit/migration/restart/UI-auth suite 13 passed. Migration upgrades a populated
old schema without changing audit rows. Failed restart rolls back ID metadata;
cutoff preserves audit of discarded drafts. Account access works without a
round and keeps legacy-route compatibility. Expected scoring errors retain
their code/message/request ID while partial results roll back.

T06–T15, final independent review, browser/device checks and final measured
load/soak gates remain outstanding. The PR must remain draft until required
acceptance is satisfied. Production probes and real-device results must never
be inferred from local emulation.

## T06 checkpoint — backup

Seven backup/restore tests passed against PostgreSQL 16: online snapshots of
editing and scored scenarios, preserved users/rounds/results/audit, revoked
sessions, checksum rejection, no overwrite of existing target and retention.
Restore durations: 0.960 s and 0.975 s; backup ages around 1.25 s, tiny test DBs.
An additional image smoke started the matching image against the restored DB
and passed readiness plus the HTTP/cookie/WebSocket checks. Off-host transfer
is implemented with remote checksum verification but a real off-host destination
and production-sized RPO/RTO have not been verified.

Repository master protection now requires runtime-linux, runtime-windows, api
and image, with strict status checks (GitHub API returned the applied settings).

## T06 checkpoint — perimeter

Read-only LB inspection and SYN header observation confirmed source
80.90.184.166 for backend 94.241.141.158:8080. HTTPS domain and direct public
HTTP both returned 200: production bypass is confirmed and remains unfixed
because deployment is excluded. The new compose publishes nginx only and
restricts original peer IP; UI/API/DB are private. Disposable ingress smoke
verified external 403 and a real WebSocket handshake through the trusted path.
Two header/404 unit regressions and six NiceGUI integration tests passed.
Production redirect, source-header sanitation and real browser CSP behavior
remain rollout/browser acceptance items.

## T06 checkpoint — authentication

Early process-wide UI limits and durable PostgreSQL API limits now use the
verified proxy peer and short-lived signed UI context. Defaults: pair 10/min,
IP 300/min, burst 120. Sixty registration/login pairs on one NAT completed
in 13.052 s without 429. Known/unknown wrong-login responses match; spoofed
IP headers do not bypass the gate. Account-global failed-login lockout is
removed; administrative blocking remains. Duplicate registration retains 409
and its documented account-enumeration limitation. Current/cards require auth.

Targeted auth/scoring: 24 passed; limiter/settings: 5 passed; catalog/UI and
audit regressions: 43 passed. Full runtime: 604 passed, one expected Windows
symlink skip. Full API run pending. Inventory retains every previous runtime
case except two intentionally replaced account-global lockout tests, now
covered by per-IP isolation tests. Production ingress rollout, real off-host
backup destination and production-sized recovery are not verified.

## T07 — instrumentation and measured baseline

Private token-gated metrics expose route/status timing, SQL timing, connection
acquisition, pool state, API/UI event-loop lag, CPU/RSS, UI HTTP in-flight and
connected client count. Request IDs are generated server-side; validated client
correlation is separate. Readiness failures log type and request ID, not exception
message/SQL/password. Telemetry regressions: 6 passed; contract bundle: 12 passed;
UI save compatibility: 6 passed. The runtime lock adds only psutil 7.2.2.

The real cookie/HTTP/Socket.IO driver exercised nginx -> NiceGUI -> API -> PG16
on local image sha256:070668a28329c7f4f85309010b5e2f800d0b9b651ae82859dd53047b18aab84f.
Each steady-state series lasted 120 seconds after login/prepare. Login warmup
concurrency was 5; these are not simultaneous-login figures. Sixty precreated
accounts took 12.12 seconds to register separately.

| VU | edits | failed actions | edit p95 (s) | canary p95 (s) |
|---:|---:|---:|---:|---:|
| 20 | 560 | 0 | 1.701 | 0.033 |
| 30 | 817 | 0 | 1.771 | 0.160 |
| 45 | 1159 | 0 | 2.383 | 0.214 |
| 60 | 1500 | 0 | 3.037 | 0.586 |

Peak connected clients matched requested VU. At 60 VU maximum sampled UI lag
was 0.342 s and API lag 0.100 s; generator CPU peak was 19.4% of one core.
Increasing UI lag correlates with edit latency; exact CPU attribution remains
unknown pending profiling. The 1.5-second target does not pass this baseline.
Raw timestamped actions/metrics are preserved in T07-baseline-*.json.gz; summary
and limitations are in T07-baseline-summary.json. Shared workstation background
regression activity and lack of browser paint measurement preclude production
capacity claims. Final acceptance needs controlled repeat runs and the 2h soak.
