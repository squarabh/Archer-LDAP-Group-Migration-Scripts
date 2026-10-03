-- SPDX-License-Identifier: FSL-1.1-MIT
/* ============================================================================
   Export-ArcherLdapGroups.sql
   Archer LDAP Group Migration (SQL-Only Sub-Project)

   PURPOSE:
     Extracts all active LDAP groups from the SOURCE Archer instance database
     and formats them directly into ready-to-paste T-SQL INSERT statements for
     Import-ArcherLdapGroups.sql.

   REQUIREMENTS:
     - Run against the SOURCE Archer instance database in SSMS or sqlcmd.
     - Permission: db_datareader (read-only). Zero writes performed.

   USAGE:
     1. Open this script in SSMS connected to the SOURCE Archer database.
     2. Set Results to Text (Ctrl+T) or Results to Grid (Ctrl+D).
     3. Execute (F5).
     4. Copy the generated T-SQL lines and paste them into the `#Src` section
        of `Import-ArcherLdapGroups.sql` on the TARGET instance.
   ============================================================================ */

SET NOCOUNT ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO

-- Safety Check: Confirm valid database
DECLARE @db SYSNAME = DB_NAME();
IF @db IN ('master', 'model', 'msdb', 'tempdb')
BEGIN
    RAISERROR('ERROR: Connected to system database [%s]. Please point SSMS at the SOURCE Archer instance database.', 16, 1, @db);
    SET NOEXEC ON;
    RETURN;
END

IF OBJECT_ID('dbo.tblGroup', 'U') IS NULL
BEGIN
    RAISERROR('ERROR: dbo.tblGroup not found in [%s]. Is this a valid Archer instance database?', 16, 1, @db);
    SET NOEXEC ON;
    RETURN;
END
GO

PRINT '============================================================================';
PRINT ' ARCHER LDAP GROUP EXTRACTION (SOURCE DATABASE: ' + DB_NAME() + ')';
PRINT '============================================================================';
PRINT '';

-- 1. Summary of groups to be exported
DECLARE @total_ldap_groups INT;
SELECT @total_ldap_groups = COUNT(*)
FROM dbo.tblGroup g
WHERE g.ldap_config_id IS NOT NULL 
  AND g.[system] = 0 
  AND g.everyone = 0;

PRINT 'Total LDAP Groups Found: ' + CAST(@total_ldap_groups AS VARCHAR(10));
PRINT '';

IF @total_ldap_groups = 0
BEGIN
    PRINT 'NOTICE: No LDAP groups found (or all groups are system/everyone).';
    PRINT 'Ensure ldap_config_id IS NOT NULL in dbo.tblGroup.';
END
ELSE
BEGIN
    PRINT '----------------------------------------------------------------------------';
    PRINT '--- COPY THE LINES BELOW AND PASTE INTO Import-ArcherLdapGroups.sql      ---';
    PRINT '----------------------------------------------------------------------------';

    -- Generate INSERT statements ready for Import-ArcherLdapGroups.sql
    SELECT 
        'INSERT INTO #Src VALUES (N''' + 
        REPLACE(g.group_name, '''', '''''') + ''', ''' + 
        CAST(g.guid AS VARCHAR(36)) + ''');' AS [Copy_Paste_T_SQL_For_Import]
    FROM dbo.tblGroup g
    WHERE g.ldap_config_id IS NOT NULL 
      AND g.[system] = 0 
      AND g.everyone = 0
    ORDER BY g.group_name;

    PRINT '';
    PRINT '----------------------------------------------------------------------------';
    PRINT '--- COPY THE HIERARCHY LINES BELOW AND PASTE INTO Section 4 OF Import   ---';
    PRINT '----------------------------------------------------------------------------';

    -- Generate hierarchy INSERTs keyed by GUID (stable across instances).
    -- Only edges with BOTH endpoints in the exported LDAP set are emitted,
    -- exactly matching the Python exporter (cross-boundary edges are skipped).
    SELECT
        'INSERT INTO #SrcHier VALUES (''' +
        CAST(p.guid AS VARCHAR(36)) + ''', ''' +
        CAST(c.guid AS VARCHAR(36)) + ''');' AS [Copy_Paste_Hierarchy_For_Import]
    FROM dbo.tblGroupRelationships r
    JOIN dbo.tblGroup p ON p.group_id = r.parent_group_id
    JOIN dbo.tblGroup c ON c.group_id = r.child_group_id
    WHERE (p.ldap_config_id IS NOT NULL AND p.[system] = 0 AND p.everyone = 0)
      AND (c.ldap_config_id IS NOT NULL AND c.[system] = 0 AND c.everyone = 0)
    ORDER BY p.group_name, c.group_name;

    PRINT '';
    PRINT '----------------------------------------------------------------------------';
    PRINT '--- METADATA & DOMAIN MAPPING (FOR AUDIT / REFERENCE ONLY)               ---';
    PRINT '----------------------------------------------------------------------------';

    SELECT 
        g.group_id AS [Source_GroupId],
        g.group_name AS [GroupName],
        g.guid AS [GUID],
        cfg.ldap_config_name AS [LdapConfigName],
        cfg.ldap_server AS [LdapServer],
        cfg.ldap_active_directory_domain AS [Domain],
        g.distinguished_name AS [DistinguishedName]
    FROM dbo.tblGroup g
    LEFT JOIN dbo.tblLDAPConfig cfg ON cfg.config_id = g.ldap_config_id
    WHERE g.ldap_config_id IS NOT NULL 
      AND g.[system] = 0 
      AND g.everyone = 0
    ORDER BY g.group_name;
END
GO

SET NOEXEC OFF;
GO
