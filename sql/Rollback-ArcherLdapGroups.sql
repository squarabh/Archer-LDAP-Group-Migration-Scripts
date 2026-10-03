-- SPDX-License-Identifier: FSL-1.1-MIT
/* ============================================================================
   Rollback-ArcherLdapGroups.sql
   Archer LDAP Group Migration (SQL-Only Sub-Project)

   PURPOSE:
     Safely rolls back (deletes) placeholder groups created during an import run.

   SAFETY GUARANTEES:
     - Pre-Package Installation: Runs cleanly when groups are unreferenced.
     - Post-Package Installation: BLOCKED BY DESIGN.
       If the Archer package was installed, foreign keys (with ON DELETE NO ACTION)
       protect data integrity. This script dynamically scans sys.foreign_keys
       and aborts before executing any DELETE if referenced by layout permissions,
       access roles, event actions, or notifications.
   ============================================================================ */

SET NOCOUNT ON;
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO

-- 1. Preflight Auth & Permissions
DECLARE @login SYSNAME = SUSER_SNAME();
DECLARE @is_owner INT = ISNULL(IS_MEMBER('db_owner'), 0);
DECLARE @can_write INT = ISNULL(IS_MEMBER('db_datawriter'), 0);
DECLARE @is_sysadmin INT = ISNULL(IS_SRVROLEMEMBER('sysadmin'), 0);

PRINT '============================================================================';
PRINT ' ARCHER LDAP GROUP ROLLBACK (TARGET DATABASE: ' + DB_NAME() + ')';
PRINT ' Current Login: ' + @login;
PRINT '============================================================================';

IF (@is_owner <> 1 AND @can_write <> 1 AND @is_sysadmin <> 1)
BEGIN
    RAISERROR('AUTH FAILED: Login [%s] requires db_datawriter, db_owner, or sysadmin. No changes made.', 16, 1, @login);
    SET NOEXEC ON;
    RETURN;
END

DECLARE @db SYSNAME = DB_NAME();
IF @db IN ('master', 'model', 'msdb', 'tempdb')
BEGIN
    RAISERROR('DATABASE CHECK FAILED: Connected to system database [%s]. Point SSMS at TARGET Archer DB.', 16, 1, @db);
    SET NOEXEC ON;
    RETURN;
END
GO

-- 2. Staging Table: Groups to Roll Back
IF OBJECT_ID('tempdb..#RollbackGuids') IS NOT NULL DROP TABLE #RollbackGuids;
CREATE TABLE #RollbackGuids (
    guid UNIQUEIDENTIFIER NOT NULL PRIMARY KEY
);

/* ----------------------------------------------------------------------------
   >>> PASTE GUIDs OF GROUPS TO REVERT BELOW THIS LINE <<<
   ---------------------------------------------------------------------------- */

BEGIN TRY
DECLARE @guid_paste_guard INT = 0; -- no-op: a TRY block must contain a statement even when nothing is pasted
-- EXAMPLE PLACEHOLDERS (fictional GUIDs):
-- INSERT INTO #RollbackGuids VALUES ('AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA');
-- INSERT INTO #RollbackGuids VALUES ('BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB');
-- INSERT INTO #RollbackGuids VALUES ('CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC');
END TRY
BEGIN CATCH
    PRINT 'STAGING FAILED: a pasted GUID is duplicated or malformed.';
    PRINT 'SQL Server error ' + CAST(ERROR_NUMBER() AS VARCHAR(10)) + ': ' + ERROR_MESSAGE();
    PRINT 'Fix the pasted GUIDs and re-run from the top in a fresh window. No changes made.';
    SET NOEXEC ON;
    RETURN;
END CATCH

/* ----------------------------------------------------------------------------
   >>> END OF GUID LIST <<<
   ---------------------------------------------------------------------------- */

DECLARE @target_count INT = (SELECT COUNT(*) FROM #RollbackGuids);
IF @target_count = 0
BEGIN
    PRINT 'NOTICE: #RollbackGuids is empty. Paste GUIDs of placeholder groups to revert above.';
    SET NOEXEC ON;
    RETURN;
END
PRINT 'Loaded ' + CAST(@target_count AS VARCHAR(10)) + ' GUID(s) for rollback check.';
PRINT '';

-- 2b. (Optional) Scope hierarchy deletion to known import-created edges.
-- Paste (parent_guid, child_guid) pairs here to delete ONLY those edges
-- (Python-rollback parity). Leave empty to delete every edge touching the
-- target groups (with a warning printed below).
IF OBJECT_ID('tempdb..#RollbackEdges') IS NOT NULL DROP TABLE #RollbackEdges;
CREATE TABLE #RollbackEdges (
    parent_guid UNIQUEIDENTIFIER NOT NULL,
    child_guid UNIQUEIDENTIFIER NOT NULL,
    PRIMARY KEY (parent_guid, child_guid)
);

/* ----------------------------------------------------------------------------
   >>> PASTE KNOWN EDGE GUID PAIRS BELOW THIS LINE (optional) <<<
   ---------------------------------------------------------------------------- */

BEGIN TRY
DECLARE @edge_paste_guard INT = 0; -- no-op: a TRY block must contain a statement even when nothing is pasted
/* (paste INSERT INTO #RollbackEdges ... lines here) */
END TRY
BEGIN CATCH
    PRINT 'STAGING FAILED: a pasted edge is duplicated or malformed.';
    PRINT 'SQL Server error ' + CAST(ERROR_NUMBER() AS VARCHAR(10)) + ': ' + ERROR_MESSAGE();
    PRINT 'Fix the pasted edges and re-run from the top in a fresh window. No changes made.';
    SET NOEXEC ON;
    RETURN;
END CATCH

/* ----------------------------------------------------------------------------
   >>> END OF EDGE LIST <<<
   ---------------------------------------------------------------------------- */


-- 3. Resolve Target Group IDs
IF OBJECT_ID('tempdb..#TargetGroups') IS NOT NULL DROP TABLE #TargetGroups;
SELECT g.group_id, g.group_name, g.guid
INTO #TargetGroups
FROM dbo.tblGroup g
JOIN #RollbackGuids r ON r.guid = g.guid;

DECLARE @found_count INT = (SELECT COUNT(*) FROM #TargetGroups);
PRINT 'Groups currently found in database: ' + CAST(@found_count AS VARCHAR(10));

IF @found_count = 0
BEGIN
    PRINT 'Nothing to roll back: none of the specified GUIDs exist in dbo.tblGroup.';
    SET NOEXEC ON;
    RETURN;
END

-- 4. Dynamic Foreign Key Dependency Check
PRINT '----------------------------------------------------------------------------';
PRINT '--- SCANNING ALL FOREIGN KEYS FOR ACTIVE DEPENDENCIES                    ---';
PRINT '----------------------------------------------------------------------------';

IF OBJECT_ID('tempdb..#BlockingReferences') IS NOT NULL DROP TABLE #BlockingReferences;
CREATE TABLE #BlockingReferences (
    referencing_table NVARCHAR(256),
    group_id INT,
    row_count INT
);

DECLARE @tbl NVARCHAR(256), @col NVARCHAR(256);
DECLARE fk_cursor CURSOR LOCAL FAST_FORWARD FOR
    SELECT DISTINCT
        OBJECT_NAME(f.parent_object_id) AS table_name,
        COL_NAME(fc.parent_object_id, fc.parent_column_id) AS column_name
    FROM sys.foreign_keys AS f
    INNER JOIN sys.foreign_key_columns AS fc 
        ON f.object_id = fc.constraint_object_id
    WHERE f.referenced_object_id = OBJECT_ID('dbo.tblGroup')
      AND OBJECT_NAME(f.parent_object_id) NOT IN ('tblGroupRelationships');

OPEN fk_cursor;
FETCH NEXT FROM fk_cursor INTO @tbl, @col;

WHILE @@FETCH_STATUS = 0
BEGIN
    DECLARE @sql NVARCHAR(MAX) = N'
        INSERT INTO #BlockingReferences (referencing_table, group_id, row_count)
        SELECT ''' + @tbl + ''', t.group_id, COUNT(*)
        FROM dbo.[' + @tbl + '] r
        JOIN #TargetGroups t ON t.group_id = r.[' + @col + ']
        GROUP BY t.group_id';
    
    BEGIN TRY
        EXEC sp_executesql @sql;
    END TRY
    BEGIN CATCH
        -- Ignore schema variation on obsolete columns across versions
    END CATCH

    FETCH NEXT FROM fk_cursor INTO @tbl, @col;
END

CLOSE fk_cursor;
DEALLOCATE fk_cursor;

DECLARE @blocking_total INT = (SELECT COUNT(*) FROM #BlockingReferences);

IF @blocking_total > 0
BEGIN
    PRINT 'ROLLBACK BLOCKED: Created groups are now referenced by Archer package objects!';
    PRINT 'SQL Server foreign key constraints prohibit deleting these groups.';
    PRINT '';
    PRINT 'Blocking Table References:';
    SELECT 
        b.referencing_table AS [ReferencingTable],
        t.group_name AS [GroupName],
        b.group_id AS [GroupId],
        b.row_count AS [ReferenceRows]
    FROM #BlockingReferences b
    JOIN #TargetGroups t ON t.group_id = b.group_id;

    PRINT '';
    PRINT 'REMEDIATION PATH (Archer has no package uninstall):';
    PRINT '1. In the Archer UI, manually remove group assignments from layouts/roles/events,';
    PRINT '   or reinstall a pre-change backup package to overwrite them.';
    PRINT '2. Alternatively, restore the instance DB from a pre-migration backup (full revert).';
    PRINT '3. Once dependencies are removed, re-run this script to delete the placeholders.';
    PRINT 'NO CHANGES WERE MADE TO THE DATABASE.';
    SET NOEXEC ON;
    RETURN;
END

-- 5. Safe Deletion (No active references detected)
-- All-or-nothing: any failure rolls EVERYTHING back so a blocked group delete
-- can never leave edges half-removed (Python non-force parity).
PRINT '----------------------------------------------------------------------------';
PRINT '--- SAFE DELETION: ZERO BLOCKING REFERENCES DETECTED                     ---';
PRINT '----------------------------------------------------------------------------';

BEGIN TRY
    BEGIN TRANSACTION;

    -- Clean up hierarchy relationships first: only staged edges when provided
    -- (Python parity), otherwise every edge touching the target groups.
    IF EXISTS (SELECT 1 FROM #RollbackEdges)
    BEGIN
        DELETE r
        FROM dbo.tblGroupRelationships r
        JOIN dbo.tblGroup pg ON pg.group_id = r.parent_group_id
        JOIN dbo.tblGroup cg ON cg.group_id = r.child_group_id
        JOIN #RollbackEdges e ON e.parent_guid = pg.guid AND e.child_guid = cg.guid
        WHERE r.parent_group_id IN (SELECT group_id FROM #TargetGroups)
           OR r.child_group_id IN (SELECT group_id FROM #TargetGroups);
        PRINT 'Deleted staged hierarchy relationships: ' + CAST(@@ROWCOUNT AS VARCHAR(10));
    END
    ELSE
    BEGIN
        PRINT 'WARNING: no staged edges provided — deleting EVERY hierarchy edge touching the target groups.';
        DELETE r
        FROM dbo.tblGroupRelationships r
        WHERE r.parent_group_id IN (SELECT group_id FROM #TargetGroups)
           OR r.child_group_id IN (SELECT group_id FROM #TargetGroups);
        PRINT 'Deleted hierarchy relationships: ' + CAST(@@ROWCOUNT AS VARCHAR(10));
    END

    -- Delete the placeholder groups
    DELETE g
    FROM dbo.tblGroup g
    JOIN #TargetGroups t ON t.group_id = g.group_id;

    DECLARE @deleted_groups INT = @@ROWCOUNT;
    PRINT 'Deleted placeholder groups: ' + CAST(@deleted_groups AS VARCHAR(10));

    COMMIT TRANSACTION;

    PRINT '';
    PRINT 'ROLLBACK COMPLETE: Successfully deleted ' + CAST(@deleted_groups AS VARCHAR(10)) + ' placeholder group(s).';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    PRINT '';
    PRINT 'ROLLBACK ABORTED: a delete failed part-way (e.g. an edge outside the staged list still references a group).';
    PRINT 'SQL Server error ' + CAST(ERROR_NUMBER() AS VARCHAR(10)) + ': ' + ERROR_MESSAGE();
    PRINT 'ALL partial work was rolled back — nothing was deleted. Remove the blocker and re-run.';
    SET NOEXEC ON;
    RETURN;
END CATCH
GO

SET NOEXEC OFF;
GO
