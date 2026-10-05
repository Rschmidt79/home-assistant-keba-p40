# KEBA KeContact P40 for Home Assistant

A local Home Assistant integration for KEBA KeContact P40 wallboxes, using the
charger's HTTPS REST API. No cloud connection or Modbus polling is required.

[![Validation](https://github.com/Rschmidt79/home-assistant-keba-p40/actions/workflows/checks.yaml/badge.svg)](https://github.com/Rschmidt79/home-assistant-keba-p40/actions/workflows/checks.yaml)
[![Release](https://img.shields.io/github/v/release/Rschmidt79/home-assistant-keba-p40)](https://github.com/Rschmidt79/home-assistant-keba-p40/releases)

## What you get

- 32 monitoring entities: charging and connection status, phase currents and
  voltages, power, lifetime/session energy, session timing and diagnostics.
- Local discovery, manual setup, automatic JWT renewal and certificate pinning.
- Charging status kept separate from an open session; exact session energy.
- Four optional controls, disabled by default and not yet physically tested.

**Tested hardware:** one P40 with REST API 2.5.0. P40 Pro and other firmware
versions are not yet physically verified. This is an independent community
project, not an official KEBA product.

Domain: `keba_p40`.
Version 0.2.2. Requires Home Assistant 2026.9 or newer (Python 3.14).

32 existing monitoring entities retain their unique IDs. Four additional controls
are registered but **disabled by default**. Setup, discovery and polling never send
controls. No Modbus polling or writes are used.

## Verification status

Monitoring reference: one physical KEBA P40 (device identifiers withheld), package
`1.5.1+cert-meter`, REST API `2.5.0`, BaseIO `5.0.1`, meter `3.0.1`, safety `3.1.3`.
Authenticated read-only audit: 2026-10-05. Public fixtures use the audited response structure with synthetic identifiers,
energy values, session IDs, dates and durations. The private raw audit is not included. Controls are implemented against the KEBA OpenAPI served by this
device, **but have not been physically executed**. This release is ready to install
for monitoring and staged control validation; it is not a claim of field-tested
production controls.

## Relationship to Home Assistant Core

[Core PR #173179](https://github.com/home-assistant/core/pull/173179) proposes a
built-in P40 integration. This repository is a separate implementation with its
own physical audit and tests; it is not a testing distribution of that PR.
Both use the domain `keba_p40`. Do not install both implementations together.
A future transition will require checking config-entry and entity compatibility.

## Install from ZIP

1. Back up Home Assistant and any existing `custom_components/keba_p40` directory.
2. Extract the ZIP. Copy its `custom_components/keba_p40` directory into
   `/config/custom_components/keba_p40`. Keep the folder name `keba_p40`.
3. Restart Home Assistant. Open Settings → Devices & services → Add integration →
   **KEBA KeContact P40**, or accept its discovery card.
4. Enter `p40.local` or `192.0.2.14`, HTTPS port `8443`, normal KEBA username and
   password. These are stored as standard HA config-entry credentials. JWTs stay
   in memory. HA config backups contain credentials; protect those backups.
5. Use the device certificate SHA-256 fingerprint with CA validation disabled for
   a pinned self-signed certificate, or trust its certificate in HA. Disabling CA
   validation without a fingerprint provides encryption without server identity
   verification. No certificate is guessed or bundled into this package.
6. Confirm the model, serial, energy, state, phase measurements and versions before
   enabling any controls. All 32 monitoring entities are enabled by default.
7. To test a control, open its entity settings and enable that specific entity.
   Follow `PHYSICAL_TEST_PLAN.md`. No controls are automatically called on enable.

Both HA and the charger must be able to reach each other on the local network.
Port 502 is irrelevant to this integration. `p40.local` requires working mDNS.

## HACS

Add `https://github.com/Rschmidt79/home-assistant-keba-p40` in HACS →
Custom repositories → **Integration**. Download the latest release, then restart
Home Assistant. The existing config entry and current entities are reused.
Do not delete the integration or create a duplicate entry.

Remove the old Ich-h4lt repository from HACS management first so it cannot
overwrite this integration. Keep the HA config entry/device. Back up your HA
configuration before switching repositories. Future releases appear as HACS
updates. This is a custom repository, not an entry in the default HACS catalog.


## Entities and semantics

See `ENTITIES.md` for all 36 entities and `CONTROLS.md` for request contracts.
`sessionActive` means an open session, not charging. Charging is `state=CHARGING`.
The observed reference had an open BLOCKED session, READY_FOR_CHARGING and 0 W.
Actual currents and offered PWM current are separate. Total energy is a lifetime
`total_increasing` kWh sensor suitable for the Energy Dashboard. Session energy
uses exact `energyConsumed`, has `state_class=total` and `last_reset=session_start`;
it is never total_increasing across sessions. `energyConsumedInKwh` is not used.
Times and duration use milliseconds; session duration includes waiting.
Missing data and API failures produce unavailable entities, never synthetic zero.
Serial is stable identity; alias is metadata. No vehicle identity inference exists.

## Polling and authentication

Wallbox: 5 s; sessions: 20 s or session/plug transition; Modbus/load-management config
and editable baseline profile: 120 s; device/version/alias: 6 h. The Modbus configs
are read **via REST**, not Modbus. Authentication and reads are serialized by an
async lock. Expired access tokens refresh with POST `/v2/jwt/refresh`; rejected
refreshes fall back to login. Controls obtain a fresh login token under the same
lock, so non-fresh-token restrictions are respected. No uncertain write is replayed.
No username, password, JWT, Authorization header or raw API response is logged or
returned by diagnostics. Diagnostic output also redacts identifying information.

## Limitations

Current control edits only a simple all-day ChargePointMaxProfile at stack level
zero, with exactly one wallbox. It preserves the existing item except its current,
refuses validity windows, complex schedules and explicit phase settings, and does
not create OCPP-sourced profiles or change OCPP configuration. Other higher priority
profiles may further restrict effective PWM; a cap is not a promise of actual current.
A missing/complex profile leaves the number unavailable; monitoring continues.

**Pause/resume is intentionally not exposed.** REST 2.5.0 has no documented dedicated
pause/resume endpoint. Zero-current profile suspension and same-session resumption
are not established by our REST audit/specification. Stop/start and out-of-order
availability must not silently substitute for session-preserving pause/resume.
This requested capability remains pending authoritative semantics and physical
validation. No phase-switching control is implemented.

## Upgrade from 0.1.0

Replace the integration directory, restart HA and retain the existing config entry.
No migration or unique-ID change is needed: existing IDs remain `{serial}_{key}`.
The display name drops “Read Only”. The four new controls start disabled. Do not
install this alongside Ich-h4lt's integration: both use domain `keba_p40` and cannot
coexist under that domain. Entity IDs may retain their prior names after upgrades.

## Troubleshooting

- Connection failure: check IP/hostname, LAN/VLAN routing, port 8443 and certificate.
- Authentication: reauthenticate with KEBA credentials; never paste JWTs into logs.
- Number unavailable: inspect the baseline profile with authorized GET; complex or
  phase-specific profiles are intentionally protected. HTTP 404 means unsupported.
- Control error: read physical state before trying again. A timeout can occur after
  the charger accepted a command. The integration does not retry the write.
- Availability enabled but no charging: vehicle, authorization and charging profiles
  still determine whether charging actually starts.
- Use HA Reload for retry. Unload clears credentials/tokens from the API instance
  and removes coordinator listeners; the shared HA HTTP session remains owned by HA.

## Development

Install `requirements_test.txt` into a Python 3.14 environment. Run `pytest --cov=custom_components.keba_p40`,
`ruff check .` and `ruff format --check .`. pytest disables network sockets by default.
See `VALIDATION.md` for actual results, and `PHYSICAL_TEST_PLAN.md` for the pending
real-device control tests. No automatic pricing, PV/load balancing, phase switching,
firmware, reboot, unlock, OCPP changes or Modbus writes are implemented.

## 0.2.1 compatibility fix

Old Ich-h4lt config entries omitted username because they always used admin.
Version 0.2.1 migrates those entries locally, fills the documented old admin
username, preserves credentials/serial, and consolidates old options into data.
It does not delete the entry or change its identity. Replace the folder and
restart HA; the existing entry is reused. Missing passwords trigger reauthentication
rather than a KeyError. No physical control request is part of migration.

## 0.2.2: legacy registry cleanup

After successful setup and registration of all 32 monitoring entities, this
release removes only the 25 known legacy entities from the old implementation,
matched by exact old unique ID, platform, entity domain and config entry.
Current unique IDs/HA entity IDs remain unchanged. Other devices, config entries
and unknown prefixed entities are untouched. Cleanup is idempotent.

Before upgrading, update any dashboards/automations using the old entities and
make a Home Assistant backup. No automatic reference remapping is attempted.
The cleanup uses HA's entity registry API, not direct .storage editing.
The missing DOMAIN import reported in the locally installed cleanup is fixed
and protected by registry/setup tests and ruff F821 checks.

## Publishing updates

Change the manifest version, run tests/ruff/hassfest, commit and push to main,
then create a matching GitHub release such as v0.2.3. HACS downloads the release
source tree. A tag alone is not a release. Active GitHub Actions in `.github/workflows/checks.yaml` run pytest, ruff,
hassfest and HACS validation. Tests block network sockets and no CI job contacts
a real charger.
