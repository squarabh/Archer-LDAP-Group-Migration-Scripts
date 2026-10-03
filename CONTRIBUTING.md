# Contributing

Thanks for helping improve this toolkit. A few ground rules keep it safe for everyone:

1. **Never commit customer data.** No real server names, domains, IPs, group names,
   GUIDs, or database names. All samples must use the fictional values already in
   the repo (`corp.example.com`, `203.0.113.10`, `AAAAAAAA-…` GUIDs).
2. **Keep both paths in sync.** A behavior change in `python/` usually needs the
   matching change in `sql/` (and vice versa). If parity is intentionally not kept,
   say so in `sql/README.md` under known limitations.
3. **Test on DEV only.** Validate against a non-production Archer instance:
   `verify-only` first, then a full import → rollback cycle with `leftover = 0`.
   Never test against production databases.
4. **Docs follow code.** New flags, exit codes, or guard behavior must be reflected
   in the relevant `README.md` / `RUNBOOK.md` / `ROLLBACK.md`.
5. **Keep the license intact.** This project is `FSL-1.1-MIT` (see `LICENSE.md`).
   Do not remove copyright notices or relicense contributions under other terms.

## Reporting issues

Open an issue with: script name + arguments (redacted), full console output,
SQL Server version, and what you expected. For rollback-blocked cases, include
the blocking table list from the script output.
