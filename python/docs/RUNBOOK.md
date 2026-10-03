# Runbook — extract → verify → import → install → (rollback if needed)

All values below are placeholders. Real customer names, domains, IPs and GUIDs
never appear in this repo — see `examples/example_export.json` for the format.

## 0. Prerequisites

- Python 3.8+ with `pip install pyodbc`, plus ODBC Driver 17/18 (scripts
  auto-negotiate). Or: use the standalone [SQL sub-project](../../sql/README.md).
- SOURCE: `db_datareader`. TARGET: `db_datawriter` or `db_owner` (scripts
  preflight this and abort clearly otherwise).
- No downtime, no service restarts.

## 1. Configure

```powershell
Copy-Item .\config\migration.config.template.json .\config\migration.config.json
# edit server/database names (never commit secrets)
```

## 2. Extract (SOURCE, read-only)

```powershell
python .\scripts\Export-ArcherLdapGroups.py --config .\config\migration.config.json --output .\exports\groups.json
# SQL login instead of Windows Integrated:
python .\scripts\Export-ArcherLdapGroups.py --server SQL01 --database ArcherProd --sql-user svc-export --output .\exports\groups.json
```

## 3. Verify (TARGET, zero-risk — always run first)

```powershell
python .\scripts\Import-ArcherLdapGroups.py --server TSQL --database ArcherTarget --input .\exports\groups.json --verify-only
```

## 4. Import (TARGET)

```powershell
python .\scripts\Import-ArcherLdapGroups.py --server TSQL --database ArcherTarget --input .\exports\groups.json
# same-name rows with wrong GUIDs (manual UI creation) → add --fix-guids
# SSMS-only alternative → use sql/Import-ArcherLdapGroups.sql
```

Gate before installing the package: `Installer check (GUID match): N/N matched`.

## 5. Install the Archer package

Normal package install — LDAP groups now auto-map (match key = `guid`).
Confirm the install log has no `LDAPGroupNotCreatable` / `GroupNotFound`.

## 6. Validation sequence (copy-paste, DEV-safe)

```powershell
python .\scripts\Import-ArcherLdapGroups.py --server . --database ArcherDev --input .\exports\groups.json --verify-only
# prove rollback on fakes (never touches real GUIDs):
# build fake2.json with 2 unused GUIDs → import → --check-only → rollback → leftover must be 0
```

## 7. Rollback (only before package install — see docs/ROLLBACK.md)

```powershell
python .\scripts\Rollback-ArcherLdapGroups.py --server TSQL --database ArcherTarget --journal .\exports\groups.json.rollback.json --check-only
python .\scripts\Rollback-ArcherLdapGroups.py --server TSQL --database ArcherTarget --journal .\exports\groups.json.rollback.json
```
