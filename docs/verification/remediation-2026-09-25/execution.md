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

T05–T15, final independent review, browser/device checks and final measured
load/soak gates remain outstanding. The PR must remain draft until required
acceptance is satisfied. Production probes and real-device results must never
be inferred from local emulation.
