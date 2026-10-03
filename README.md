# Archer LDAP Group Migration Toolkit

An enterprise solution for migrating Archer LDAP groups across Archer GRC instances (such as staging, QA, dev, or air-gapped instances outside the Active Directory network) as **local stub groups with exact source GUIDs**.

This toolkit eliminates the classic Archer Application Packaging installation failure:
> `ValidationSeverity.Error: LDAPGroupNotCreatable: Group {sourceGroupId} is an LDAP group and can't be created.`

The repository provides two independent, fully featured sub-projects tailored for different operational workflows:
- **[Python Sub-Project (`python/`)](python/README.md)**: Automated CLI tools with JSON export, dry-run validation, and rollback journal management.
- **[SQL Sub-Project (`sql/`)](sql/README.md)**: Zero-dependency T-SQL scripts for direct execution in SSMS, Azure Data Studio, or `sqlcmd`.

---

## 1. How It Works (Archer Packaging Internals)

### The Core Problem
When exporting an Archer application, any field permissions, layout access rules, access roles, or notifications assigned to an LDAP group are serialized with that group's GUID and domain:
```xml
<!-- Example from UsersGroups.xml inside an Archer package (fictional values) -->
<PackageGroup>
    <GUID>cccccccc-cccc-4ccc-8ccc-cccccccccccc</GUID>
    <Id>258</Id>
    <Name>Example-Entity-Group</Name>
    <Domain>corp.example.com</Domain>
</PackageGroup>
```
During package installation on a target instance:
1. **Key Resolution (`KeyManager.cs`):** Archer's `GroupGuidLookup` queries `dbo.tblGroup` by GUID (`groupBroker.GetGroupsByGuid`). If a group with that exact GUID is found, Archer immediately associates the package permissions with the target `group_id`.
2. **The Failure Point (`GroupInstaller.cs`):** If the group is missing, Archer attempts to create it. For local groups, it creates a new stub. However, for LDAP groups (having a non-empty `Domain`), Archer halts execution:
   ```csharp
   if (packageGroup.Domain == null || packageGroup.Domain.Trim() == string.Empty) {
       // Local group: creates stub
   } else {
       // LDAP group: Hard error!
       requestResult.ValidationMessages.Add(new ValidationMessage(
           "LDAPGroupNotCreatable", typeof(GroupInstaller).Name, "LDAP Group", 
           ValidationSeverity.Error, $"Group {sourceGroupId} is an LDAP group and can't be created."));
   }
   ```
   Because target instances outside the Active Directory network cannot perform LDAP synchronization, the installation fails.

### The Solution: Offline Local Stub Seeding
By pre-creating local stub records in `dbo.tblGroup` using the **exact source GUIDs** (with `ldap_config_id = NULL` and `distinguished_name = NULL`):
- `KeyManager` finds the matching GUID immediately in `dbo.tblGroup`.
- `GroupInstaller.CreateGroup` is completely bypassed.
- The Archer application package installs cleanly with zero errors.

---

## 2. Choosing Your Migration Approach

| Feature | Python Sub-Project (`python/`) | SQL Sub-Project (`sql/`) |
| :--- | :--- | :--- |
| **Primary Audience** | DevOps, Automation Engineers, System Admins | Database Administrators (DBAs) |
| **Execution Environment** | PowerShell, Bash, Command Prompt | SSMS, Azure Data Studio, `sqlcmd` |
| **Dependencies** | Python 3.8+, `pyodbc`, ODBC Driver 17/18 | None (Native T-SQL) |
| **Air-Gapped Friendly** | Yes (Self-contained scripts) | Yes (Zero client-side installs) |
| **Export Mechanism** | Export script &rarr; Structured JSON file | Export script &rarr; Formatted `INSERT` statements |
| **Verification Mode** | Automated `--verify-only` dry-run | T-SQL analysis query in import script |
| **Rollback Tracking** | Automated `<input>.rollback.json` journal | T-SQL rollback script with dynamic FK check |
| **Guide & Runbook** | **[View Python Guide](python/README.md)** | **[View SQL Guide](sql/README.md)** |

---

## 3. Rollback & Database Integrity Mechanics

### Can you revert back to the original stage?

#### Before Package Installation: **YES**
- Unreferenced stubs can be safely deleted using either the Python rollback tool (`Rollback-ArcherLdapGroups.py`) or the SQL rollback script (`Rollback-ArcherLdapGroups.sql`).
- Deletions are executed in strict dependency order: hierarchy edges &rarr; created groups (&rarr; restored original GUIDs in the Python path, which supports `--fix-guids`).

#### After Package Installation: **DIRECT ROLLBACK IS BLOCKED BY DESIGN**
- Once the package is installed, layouts, fields, access roles, and event actions bind foreign keys to `tblGroup.group_id`.
- **All 24 foreign keys** referencing `dbo.tblGroup` in SQL Server are configured with `ON DELETE NO ACTION` (restrict).
- Both the Python and SQL rollback utilities dynamically inspect `sys.foreign_keys`. If active references exist, they safely abort and print the exact blocking table names and record counts.
- **Reversion Path:** To roll back post-installation, the Archer package must be uninstalled or the group references removed from the layout/application first, then the rollback utility can be re-run.

#### Identity Sequence Gaps
- Deleting created rows leaves permanent gaps in `tblGroup.group_id` (`IDENTITY(1,1)`).
- This is standard SQL Server behavior and does **not** affect Archer functionality since packaging keys strictly on `guid`, not `group_id`.

#### Caching & Broker Side Effects
- Direct SQL inserts into `dbo.tblGroup` bypass Archer's in-memory `GroupBroker` cache.
- While the database immediately holds the records (and packaging reads them directly from the database), Archer web services and the UI Manage Groups tree may not show the new groups immediately until an application cache refresh or IIS AppPool recycle occurs.

---

## 4. Key Architectural Considerations & Limitations

### Group Memberships (`tblXGroupsUsers`)
- Package definitions **never** package or map user-to-group memberships.
- Groups in packages serve purely as structural containers for application permissions.
- User memberships are omitted by default to protect Active Directory user privacy and eliminate payload bloat.

### Group Hierarchy (`tblGroupRelationships`)
- Packaging does not evaluate or package parent/child group relationships.
- Group relationships are runtime-only permission inheritance constructs.

### Name Collision Handling
- **Same GUID, different name:** The group is matched by GUID and logged as a name conflict; the target group name is preserved.
- **Same Name, different GUID:** Skipped by default to prevent accidental data overwrites.

### Round-Trip Packaging (Target &rarr; Source)
- If an application configured on the target instance is later packaged and brought back to the source instance, will it automap?
- **Yes.** Because the stub group in the target instance shares the exact same GUID as the source LDAP group, the source instance's `KeyManager` will match the GUID immediately on return.

---

## 5. Repository Structure

```
.
├── README.md                      # Global architecture & comparison guide (this file)
├── LICENSE.md                     # FSL-1.1-MIT license (Copyright 2026 Sourabh Sharma)
├── .gitignore                     # Git ignore rules for configs, journals, and logs
│
├── python/                        # Python CLI Sub-Project
│   ├── README.md                  # Comprehensive Python setup and CLI guide
│   ├── scripts/
│   │   ├── Export-ArcherLdapGroups.py    # Read-only source extractor
│   │   ├── Import-ArcherLdapGroups.py    # Idempotent stub importer & verifier
│   │   └── Rollback-ArcherLdapGroups.py  # Journal-driven rollback utility
│   ├── config/
│   │   └── migration.config.template.json# Config template for DB connections
│   ├── docs/
│   │   ├── RUNBOOK.md             # Step-by-step production runbook
│   │   └── ROLLBACK.md            # Rollback referencer and dependency guide
│   ├── examples/
│   │   └── example_export.json    # Sample sanitized JSON export
│   └── tests/
│       └── smoke.ps1              # PowerShell test & preflight runner
│
└── sql/                           # Standalone T-SQL Sub-Project
    ├── README.md                  # Comprehensive SQL guide for DBAs
    ├── Export-ArcherLdapGroups.sql# Source DB T-SQL extraction script
    ├── Import-ArcherLdapGroups.sql# Target DB T-SQL import & verification script
    └── Rollback-ArcherLdapGroups.sql # Target DB T-SQL rollback script with FK checks
```

---

## 6. Quick Navigation

- For automated CLI migrations with JSON outputs: **[Go to Python Sub-Project](python/README.md)**
- For standalone SSMS execution with zero dependencies: **[Go to SQL Sub-Project](sql/README.md)**

---

## 7. License

Licensed under the [Functional Source License, Version 1.1, MIT Future License](LICENSE.md)
(`FSL-1.1-MIT`), Copyright 2026 Sourabh Sharma. Use, copy, modification and redistribution
are permitted for any purpose other than a Competing Use (see license text); each published
version converts to MIT on the second anniversary of the date it is made available.
