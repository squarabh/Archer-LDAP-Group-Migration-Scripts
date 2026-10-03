# Changelog

All notable changes to this project are recorded here. Dates are UTC.

## [Unreleased]
- SQL path now migrates GUID-keyed hierarchy edges (export emits `#SrcHier`
  lines; import recreates them), matching the Python importer.
- Docs written observationally (no implementation references); terminology unified
  on "placeholder"; reversion path corrected (Archer has no package uninstall).
- Cross-platform path defaults; backup prerequisite, LDAP-sync interplay warning,
  `--fix-guids` consequence note, and tested-versions matrix documented.

## [1.0.0] - 2026-10-03

Initial public release under `FSL-1.1-MIT`.

### Added
- Python sub-project: read-only LDAP exporter (JSON), idempotent placeholder
  importer (`--verify-only`, `--fix-guids`, `--emit-sql`, rollback journals),
  journal-driven rollback (`--check-only`, `--force`), config template, sanitized
  example export, smoke test, runbook and rollback docs.
- SQL sub-project: SSMS-ready export (group + GUID-keyed hierarchy `INSERT`s),
  guarded import (preflight checks, collision detection, hierarchy recreation),
  FK-aware rollback with dynamic `sys.foreign_keys` blocking detection.
- Docs: architecture guide, per-project READMEs, exit-code contract, `CONTRIBUTING.md`,
  `SECURITY.md`, `LICENSE.md`.

### Fixed (pre-release hardening)
- Import-SQL preflight batch could not compile (`RAISERROR` with function argument);
  guards are now live.
- Import-SQL audit-login fallback could never fire (stale variable); NULL-reset added.
- Python `--force` rollback now commits edge deletion separately so it works as documented.
- `--emit-sql` output gained the same-name guard the importer enforces.
- Sanitized all real domains, GUIDs, server and group names from samples and docs.
- Terminology unified on "placeholder" (pre-seeded GUID mapping targets).
