# Changelog

## 0.2.2

- First public HACS release with anonymized/synthetic public test fixtures.
- Preserve the existing 32 monitoring unique IDs and four disabled controls.
- Add scoped, idempotent removal of 25 known legacy registry identifiers after
  successful registration of all current monitoring entities.
- Import DOMAIN explicitly; a cleanup failure cannot disable monitoring.
- Include old config-entry migration for implicit admin and option consolidation.
- Include a pytest/ruff/hassfest/HACS CI template; it is not activated because
  the publishing credential lacks workflow scope. No live charger test is run.

Controls remain physically unverified. Session-preserving pause/resume and phase
switching remain unimplemented. Back up HA and update old entity references before
upgrading.

## 0.2.1 (local package)

- Fix missing username on old config entries; preserve data, identity and credentials.

## 0.2.0 (local package)

- 32 monitoring entities, four disabled controls, documented response validation.
