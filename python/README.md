# Archer LDAP Group Migration — Python Sub-Project

An automated, cross-platform CLI toolkit for migrating Archer LDAP groups across instances (e.g., to air-gapped, staging, or cross-domain instances outside the Active Directory network) as **local stub groups with exact source GUIDs**.

This sub-project provides automated JSON-based extraction, idempotent importing, preflight authentication/permission validation, and journal-driven rollback.

---

## 1. Prerequisites & Dependencies

### System Requirements
- **Python:** Version 3.8 or higher.
- **SQL Server ODBC Driver:**
  - [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) (Recommended)
  - ODBC Driver 17 for SQL Server, or standard SQL Server legacy driver.
- **Database Permissions:**
  - **Source Database:** `db_datareader` (Read-only access).
  - **Target Database:** `db_datawriter` or `db_owner`.

### Python Package Installation
Install the required database driver library:
```powershell
pip install pyodbc
```

### Pre-Script Environment Validation
You can run the built-in smoke test script to verify that Python, `pyodbc`, and ODBC drivers are correctly configured:
```powershell
powershell -ExecutionPolicy Bypass -File .\tests\smoke.ps1 -Server "TARGET_SQL_HOST" -Database "TargetArcherDB"
```

---

## 2. Directory Layout

```
python/
  config/
    migration.config.template.json  # Configuration file template
  docs/
    RUNBOOK.md                      # Detailed step-by-step production runbook
    ROLLBACK.md                     # Rollback architecture and referencer details
  examples/
    example_export.json             # Sanitized reference export structure
  scripts/
    Export-ArcherLdapGroups.py      # Extracts LDAP groups to JSON
    Import-ArcherLdapGroups.py      # Dry-runs and imports stub groups into target DB
    Rollback-ArcherLdapGroups.py    # Undoes imports using the rollback journal
  tests/
    smoke.ps1                       # Automated preflight & smoke test runner
```

---

## 3. Configuration Setup

You can provide server and database connection details via command-line flags or a configuration file.

To use a configuration file:
1. Copy the template:
   ```powershell
   Copy-Item .\config\migration.config.template.json .\config\migration.config.json
   ```
2. Edit `config/migration.config.json` with your server and database names:
   ```json
   {
     "source": {
       "server": "SOURCE-SQL-HOST",
       "database": "SourceArcherDB"
     },
     "target": {
       "server": "TARGET-SQL-HOST",
       "database": "TargetArcherDB"
     }
   }
   ```
*(Note: Never commit passwords to configuration files. Passwords should be supplied via `$env:SQLPASSWORD`, interactive prompt, or Windows Integrated Authentication).*

---

## 4. Execution Workflow

### Step 1: Export from Source (Read-Only)
Extract active LDAP groups into a JSON payload:
```powershell
# Using config file:
python .\scripts\Export-ArcherLdapGroups.py --config .\config\migration.config.json --output .\exports\groups.json

# Or using explicit flags:
python .\scripts\Export-ArcherLdapGroups.py --server "SQL01" --database "SourceArcherDB" --output .\exports\groups.json
```
*Tip: By default, user memberships (`tblXGroupsUsers`) are omitted to protect Active Directory privacy and optimize payload size. If you need user memberships for auditing, pass the `--include-members` flag.*

### Step 2: Verify on Target (Zero-Risk Dry Run)
Always run verify-only mode first. This tests connectivity, checks permissions, reports matched vs. missing groups, and identifies naming conflicts without making any database modifications:
```powershell
python .\scripts\Import-ArcherLdapGroups.py --server "TSQL01" --database "TargetArcherDB" --input .\exports\groups.json --verify-only
```

### Step 3: Import Stubs into Target Database
Execute the import to create local stub groups with matching GUIDs:
```powershell
python .\scripts\Import-ArcherLdapGroups.py --server "TSQL01" --database "TargetArcherDB" --input .\exports\groups.json
```
- Every write run automatically writes a **Rollback Journal** (default: `<input>.rollback.json`, e.g., `.\exports\groups.json.rollback.json`).
- If existing target groups share the same name but have different GUIDs, they are safely skipped. Add `--fix-guids` only if you explicitly intend to update their GUIDs.

### Step 4: Install the Archer Package
Navigate to the Archer Web UI on the target instance (**Administration > Tools > Install Packages**) and install your application package. Archer's `KeyManager` will automatically map layout authorizations and access roles to the imported stub groups.

---

## 5. Rollback Procedure

### Can you revert back to the original stage?

#### Before Package Installation: **YES**
If you need to revert before installing the package:
```powershell
# 1. Preview changes (Check-Only mode):
python .\scripts\Rollback-ArcherLdapGroups.py --server "TSQL01" --database "TargetArcherDB" --journal .\exports\groups.json.rollback.json --check-only

# 2. Execute rollback:
python .\scripts\Rollback-ArcherLdapGroups.py --server "TSQL01" --database "TargetArcherDB" --journal .\exports\groups.json.rollback.json
```
The script reads the rollback journal and deletes the created hierarchy edges and stub groups in reverse dependency order.

#### After Package Installation: **DIRECT ROLLBACK IS BLOCKED BY DESIGN**
- Once the package is installed, layouts, access roles, and events bind foreign keys to `tblGroup.group_id`.
- All 24 foreign keys to `tblGroup` in SQL Server are configured with `ON DELETE NO ACTION`.
- `Rollback-ArcherLdapGroups.py` dynamically scans `sys.foreign_keys`. If active references exist, it aborts (Exit 2) and prints the exact blocking table names and reference counts.
- **Reversion Path:** You must uninstall the Archer package or remove group assignments in the application layouts first, then re-run the rollback script.

---

## 6. CLI Command Reference

### `Export-ArcherLdapGroups.py`
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--server` | SQL Server hostname / instance | None |
| `--database` | Source Archer instance database | None |
| `--output` | Destination path for the exported JSON file (forward slashes work on Windows and Linux) | `./exports/ldap_groups_export.json` |
| `--config` | Path to JSON config file | None |
| `--all` | Export ALL groups (including local non-LDAP groups) | `False` |
| `--include-system` | Include Archer system and everyone groups | `False` |
| `--include-members` | Extract user membership rows (`tblXGroupsUsers`) | `False` |
| `--sql-user` | SQL Authentication username | `$env:SQLUSER` |
| `--sql-password` | SQL Authentication password | `$env:SQLPASSWORD` |

### `Import-ArcherLdapGroups.py`
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--server` | SQL Server hostname / instance | None |
| `--database` | Target Archer instance database | None |
| `--input` | Path to exported JSON file | Required |
| `--verify-only` | Dry-run mode: checks matches without writing | `False` |
| `--fix-guids` | Update GUID on existing same-name rows | `False` |
| `--login-id` | Audit `user_id` for creation records (auto-resolves) | `2` (sysadmin) |
| `--journal` | Path to write the rollback journal | `<input>.rollback.json` |
| `--emit-sql` | Also emit a standalone `.sql` loader script (idempotent, guid + same-name guarded; no auth preflight or hierarchy — for the fully guarded SSMS path see `sql/Import-ArcherLdapGroups.sql`) | None |

### `Rollback-ArcherLdapGroups.py`
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--server` | SQL Server hostname / instance | Required |
| `--database` | Target Archer instance database | Required |
| `--journal` | Path to `<input>.rollback.json` | Required |
| `--check-only` | Preview deletions without modifying the database | `False` |
| `--force` | Delete hierarchy edges even if groups are referenced | `False` |

## 7. Exit-Code Contract

All three scripts use the same exit codes, so they are safe to chain in automation:

| Code | Meaning | Produced by |
| :--- | :--- | :--- |
| `0` | Success (or clean dry-run / check-only preview) | all scripts |
| `1` | Error: bad input, connection failure, or rolled-back exception | all scripts |
| `2` | Blocked by design: created groups are now referenced by package objects — no changes made | `Rollback-…` (re-run after removing references; `--force` still removes journal edges) |
| `3` | Auth/permission preflight failed — no changes made (re-run with `--sql-user/--sql-password`) | `Export-…`, `Import-…`, `Rollback-…` |
