# Security Policy

## Supported versions

Only the latest commit on `main` is supported. There are no maintained backports.

## Reporting a vulnerability

Do not open a public issue for security-sensitive findings. Contact the maintainer
via LinkedIn (see Credits in `README.md`) with:

- Affected script and version (commit hash)
- Steps to reproduce
- Impact assessment (e.g., unintended writes, privilege behavior)

## Scope notes

- These tools require `db_datawriter`/`db_owner` on the target instance **by design**;
  that is not a vulnerability. Run them with least-privilege SQL logins and never
  commit credentials (see `.gitignore`).
- The scripts intentionally bypass the Archer application layer with direct SQL.
  Only run them against Archer instance databases during planned migrations, after
  a verified backup.
