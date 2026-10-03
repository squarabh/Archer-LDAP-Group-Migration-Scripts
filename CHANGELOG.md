# Changelog

All notable changes to this project are recorded here. Dates are UTC.

## [Unreleased]
- Staging tables hardened: `#Src`/`#SrcHier` (and `#RollbackGuids`/`#RollbackEdges`)
  carry primary keys so duplicate pastes fail fast; `#Src.group_name` sized to
  `NVARCHAR(256)` to match `tblGroup`.
- SQL Export emits only hierarchy edges with both endpoints in the LDAP set
  (exact Python-importer parity for cross-boundary edges).
- SQL Rollback accepts optional `#RollbackEdges` GUID pairs to scope hierarchy
  deletion (Python parity); unscoped runs print a warning.
- Python Import pre-flights rollback-journal writability before any DB work and
  prints manual recovery data if the journal write ever fails post-commit.
- Python Import forces `everyone=0` (a migrated row can never become the special
  everyone group) and prints an explicit warning per `--fix-guids` rewrite.
- Input-shape validation fails fast on malformed JSON entries; empty-export exit
  unified as "nothing to do" (exit 2).
- All SQL staging sections wrapped in TRY/CATCH: any bad pasted row aborts the
  whole script before any real-table write (no more partial staging).
- SQL Rollback deletion section is atomic (TRY/CATCH + transaction): a mid-way
  FK failure rolls everything back with a clear ABORTED message instead of a
  misleading COMPLETE with zero deletes.

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
- Docs: architecture guide, per-project READMEs, process diagrams, exit-code
  contract, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE.md`.

### Fixed (pre-release hardening)
- Import-SQL preflight batch could not compile (`RAISERROR` with function argument);
  guards are now live.
- Import-SQL audit-login fallback could never fire (stale variable); NULL-reset added.
- Python `--force` rollback now commits edge deletion separately so it works as documented.
- `--emit-sql` output gained the same-name guard the importer enforces.
- Sanitized all real domains, GUIDs, server and group names from samples and docs.
- Terminology unified on "placeholder" (pre-seeded GUID mapping targets).
