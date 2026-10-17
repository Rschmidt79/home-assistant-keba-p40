# Validation — 2026-10-17 (0.2.4)

- Python 3.14.8; Home Assistant test dependency 2026.9.4.
- pytest: **116 passed**, with network sockets disabled.
- Statement coverage: **98.80%** (657/665).
- ruff check and ruff format --check: passed.
- RFID tests cover opaque IDs, invalid/missing values, no fallback to a previous
  session, active/historical scope, malformed closure data, API failure and
  diagnostics redaction. Public tests use synthetic chip IDs.
- Read-only observation on HA 2026.10.1 confirmed the session token sensor is
  loaded and exposes a historical session (`active_session: false`). This is
  not a fresh-swipe test or a physical charging-control test.
- GitHub Actions also runs official hassfest and HACS validation on the release
  commit. No charger controls or authorization settings are changed.

# Validation — 2026-10-05

- Home Assistant **2026.9.4**, Python **3.14.8**, macOS.
- pytest: **98 passed**, with network sockets disabled (`--disable-socket --allow-unix-socket`).
- Statement coverage: **98.77%** (645/653).
- ruff check: passed; ruff format --check: passed.
- Official Home Assistant hassfest: **1 integration, 0 invalid**, all applicable
  custom-integration validation plugins passed. Validator source commit
  `8bbc10b9f18d2af1a2e85718ecbbd580701c0ccb`.
- Actual HA config-entry setup, 36 registry entities (32 enabled), one device,
  reload/unload, outage/recovery, discovery deduplication, reauth/reconfigure,
  diagnostics redaction and existing unique IDs are tested.
- Controls cover documented profile/wallbox response alternatives, ACCEPTED,
  REJECTED/FAILED/CONFLICT/NOT_FOUND/unknown/null acceptance, malformed JSON/body,
  HTTP failure, timeout, no retry, post-write readback/refresh, no optimistic state,
  local bounds, single-box guard, complex-profile refusal and auth lock/expiry.
- Synthetic control response fixtures follow the captured KEBA OpenAPI; they are
  **not captured physical control responses**. The public monitoring fixtures use audited response shapes with synthetic
  device/session identifiers, counters and timestamps. The private audit is excluded.

No physical state-changing request was sent to 192.0.2.14 during this task.
No new physical GET audit was conducted during this implementation task.
Controls are **not physically verified**. Pause/resume remains unimplemented
because its required REST semantics are not established. HACS packaging exists,
but the GitHub repository is published as a HACS custom repository;
no default-catalog admission is claimed.

The ZIP excludes bytecode, test/lint caches, coverage database and local environment
files. Source, tests, documented fixtures, license, translations and an active CI workflow are included.

Version 0.2.2 includes runtime tests for exact 25-entry registry cleanup, preservation
of 32 monitor entities/four controls, other config entries/platforms/domains,
unknown IDs, idempotence, setup success and cleanup failure isolation.
No serial number, address, certificate fingerprint or credentials from the
reference device are published.

GitHub Actions runs pytest/coverage, ruff/formatter, official hassfest and HACS
validation on pushes/PRs/manual dispatch. All HACS checks are enabled; no default HACS catalog inclusion is claimed.
