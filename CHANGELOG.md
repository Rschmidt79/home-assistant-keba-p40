# 0.2.5

- Preserve the complete production stability fixes when updating through HACS.
- Accept supported current profiles with a past validFrom and null phase count;
  restore a numeric current-limit entity by avoiding NumberEntity.value collision.
- Retain per-action control receipts, uncertain outcomes and fresh physical feedback;
  never replay an ambiguous control POST.
- Use fresh connections for wallbox controls and prevent stale polling from hiding
  a current-limit acknowledgement.
- Publish passive meter observation freshness even when the meter value is unchanged.
- Keep existing entity IDs, device identity, config entries and control enablement.
  Add one control-result diagnostic sensor; controls remain disabled for new installs.

Update while the charger is idle, with a Home Assistant backup, then fully restart
Home Assistant. Integration reload alone does not reliably replace imported Python
modules. Do not remove/re-add the integration. Local charging-controller scripts,
templates and dashboards are separate and are not installed or replaced by this release.
A downgrade to public 0.2.4 loses these fixes; restore the complete pre-update backup
instead if rollback is needed. Climate/preconditioning changes are not included.

# 0.2.4

- Add a read-only session token ID sensor for RFID-based automation, with session
  identity and active/historical attributes. Preserve chip ID case and leading zeros.
- Reject invalid/missing chip values and redact chip IDs from diagnostics.
- Treat malformed session closure data as inactive for chip bindings.
- No automatic vehicle mapping, charger authorization or control changes.

# 0.2.3

- Improve installation and feature documentation and repository discoverability.
- Include a neutral local integration icon and enable all HACS checks.
- No changes to charger requests, entity IDs or control behavior.

# Changelog

## 0.2.2

- First public HACS release with anonymized/synthetic public test fixtures.
- Preserve the existing 32 monitoring unique IDs and four disabled controls.
- Add scoped, idempotent removal of 25 known legacy registry identifiers after
  successful registration of all current monitoring entities.
- Import DOMAIN explicitly; a cleanup failure cannot disable monitoring.
- Include old config-entry migration for implicit admin and option consolidation.
- Include a pytest/ruff/hassfest/HACS CI workflow. No live charger test is run.

Controls remain physically unverified. Session-preserving pause/resume and phase
switching remain unimplemented. Back up HA and update old entity references before
upgrading.

## 0.2.1 (local package)

- Fix missing username on old config entries; preserve data, identity and credentials.

## 0.2.0 (local package)

- 32 monitoring entities, four disabled controls, documented response validation.
