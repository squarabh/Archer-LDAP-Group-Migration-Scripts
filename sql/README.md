# Archer LDAP Group Migration — SQL Sub-Project

A pure T-SQL toolkit for migrating Archer LDAP groups across instances (e.g., to air-gapped, staging, or cross-domain instances outside the Active Directory network) as **local placeholder groups with exact source GUIDs**.

This sub-project is designed specifically for **Database Administrators (DBAs)** and environments where **Python, pip, or ODBC drivers cannot be installed**.

---

## 1. Why Use the SQL-Only Approach?

- **Zero External Dependencies:** Runs natively in SQL Server Management Studio (SSMS), Azure Data Studio, or `sqlcmd`.
- **Air-Gapped & Locked-Down Environments:** Perfect when security policies prohibit running external scripts or installing runtimes on database servers.
- **Full Parity with Python Toolkit for the core flow:**
  - Idempotent insertion (`WHERE NOT EXISTS`).
  - Name collision detection.
  - Preflight permission guards (`db_datawriter` / `db_owner` / `sysadmin`).
  - Dynamic `sys.foreign_keys` inspection for safe rollback.
- **Known SQL-path limitations (Python-only features):** hierarchy edges
  (`tblGroupRelationships`) are not migrated — re-created placeholders are flat
  (packaging ignores hierarchy, so installs still map); no `--fix-guids`
  equivalent (same-name/wrong-GUID rows are skipped, never overwritten);
  no automatic rollback journal (paste GUIDs into the rollback script manually).

---

## 2. File Overview

| File | Target Instance | Role | Description |
| :--- | :--- | :--- | :--- |
| [`Export-ArcherLdapGroups.sql`](Export-ArcherLdapGroups.sql) | **SOURCE DB** | Read-Only | Extracts LDAP groups and formats them into ready-to-paste T-SQL `INSERT` statements. |
| [`Import-ArcherLdapGroups.sql`](Import-ArcherLdapGroups.sql) | **TARGET DB** | Write | Analyzes existing groups, reports conflicts, and inserts missing placeholders with matching GUIDs. |
| [`Rollback-ArcherLdapGroups.sql`](Rollback-ArcherLdapGroups.sql) | **TARGET DB** | Safe Revert | Checks all 24+ foreign keys before deleting; safely deletes placeholders prior to package install. |

---

## 3. Step-by-Step Migration Guide

### Step 1: Extract from Source Database
1. Open SSMS and connect to the **SOURCE** Archer database (e.g., `ArcherProduction`).
2. Open [`Export-ArcherLdapGroups.sql`](Export-ArcherLdapGroups.sql).
3. Ensure results mode is set to **Results to Text** (`Ctrl + T`) or **Results to Grid** (`Ctrl + D`).
4. Execute the script (`F5`).
5. Copy the generated `INSERT INTO #Src VALUES (...)` lines from the output.

### Step 2: Import into Target Database
1. Open SSMS and connect to the **TARGET** Archer database (e.g., `ArcherTarget`).
2. Open [`Import-ArcherLdapGroups.sql`](Import-ArcherLdapGroups.sql).
3. Paste the copied rows into Section 3:
   ```sql
   /* >>> PASTE ROWS FROM Export-ArcherLdapGroups.sql BELOW THIS LINE <<< */
   INSERT INTO #Src VALUES (N'Example Finance Group', 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA');
   INSERT INTO #Src VALUES (N'Example HR Group', 'BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB');
   INSERT INTO #Src VALUES (N'Example-Entity-Group', 'CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC');
   /* >>> END OF PASTED ROWS <<< */
   ```
4. Execute the script (`F5`).
5. Review the execution summary:
   - **Pre-import analysis:** Displays which groups are already matched and which are missing.
   - **Collision warnings:** Flags any groups sharing the same name but possessing different GUIDs.
   - **Newly inserted count:** Shows how many records were inserted into `dbo.tblGroup`.
   - **Verification check:** Confirms that all source GUIDs are now present in `dbo.tblGroup`.

### Step 3: Install the Archer Package
Once the verification confirms that all groups match:
1. Navigate to the Archer Web UI on the target instance.
2. Go to **Administration > Tools > Install Packages**.
3. Install the application package. The packaging installer will automatically map layout authorizations, access roles, and event actions to the pre-seeded placeholder groups.

---

## 4. Rollback & Safety Mechanics

### Can you revert back to the original stage?

#### Before Package Installation: **YES**
If you need to cancel the migration before the package is installed:
1. Open [`Rollback-ArcherLdapGroups.sql`](Rollback-ArcherLdapGroups.sql) in SSMS connected to the TARGET database.
2. Paste the GUIDs of the groups you wish to delete into Section 2 (`#RollbackGuids`).
3. Execute (`F5`). Because no package objects reference the placeholders yet, the script safely deletes them.

#### After Package Installation: **DIRECT ROLLBACK IS BLOCKED BY DESIGN**
- Once the package is installed, layouts, fields, access roles, and notifications bind foreign keys to `tblGroup.group_id`.
- All 24 foreign keys referencing `dbo.tblGroup` in SQL Server are configured with `ON DELETE NO ACTION`.
- [`Rollback-ArcherLdapGroups.sql`](Rollback-ArcherLdapGroups.sql) automatically scans `sys.foreign_keys`. If active references exist, it aborts without deleting any rows and prints the exact blocking table names and record counts.
- **Reversion Path:** You must uninstall the package or remove group assignments from the application layouts first, then re-run the rollback script.

---

## 5. Database Integrity & Caching Notes

- **Identity Sequence Gaps:** Deleting created rows leaves permanent gaps in `tblGroup.group_id` (`IDENTITY(1,1)`). This is expected SQL Server behavior and does not affect Archer functionality since packaging matches exclusively on `guid`.
- **Audit Login Resolution:** The import script dynamically inspects `dbo.tblUser` to identify the `sysadmin` account ID (falling back to the lowest valid `user_id`) rather than hardcoding arbitrary IDs.
- **Web UI Cache:** Direct SQL inserts into `dbo.tblGroup` bypass Archer's in-memory group cache. While packaging reads directly from the database and works immediately, the Archer Web UI Manage Groups tree may require an application pool recycle or cache refresh to display the newly created placeholders.
