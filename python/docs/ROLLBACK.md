# Rollback design — why it works, when it doesn't

## What the journal records

Every write run of `Import-ArcherLdapGroups.py` writes `<input>.rollback.json`:

```json
{
  "created_groups": [{"group_id": 271, "name": "...", "guid": "..."}],
  "guid_fixes": [{"group_id": 55, "old_guid": "...", "new_guid": "..."}],
  "added_edges": [{"parent_group_id": 70, "child_group_id": 71}]
}
```

Rollback undoes in dependency order: **edges → groups → guid restores**,
each step guarded by re-checking current state (safe to run twice).

## When rollback succeeds

- Run **before** installing the package. Created placeholders are unreferenced, so
  `DELETE` succeeds and `leftover = 0`. Validated end-to-end (create →
  `check-only` → rollback → `leftover 0`, real groups untouched).

## When rollback is BLOCKED (by design)

Once the package is installed, rows like `tblXEventActionGroup(group_id)`
reference the new placeholders. All 24 foreign keys to `tblGroup` (counted on Archer 6.15;
other versions are handled because inspection is dynamic) are `NO ACTION`, so SQL
Server itself refuses the delete. The rollback script automatically and dynamically
inspects `sys.foreign_keys` across all tables pointing to `dbo.tblGroup` and aborts
with exit 2 listing every blocking referencer:

```
BLOCKED: created groups are now referenced (package likely installed):
  tblXEventActionGroup: [{'group_id': 271, 'rows': 1}]
```

Revert path — Archer has no package uninstall, so pick one (references were
created by the install, not by this toolkit):
1. **Manual removal (surgical):** in the Archer UI, remove the group assignments
   (field/layout permissions, access roles, event actions, notifications) that
   point at the placeholder groups — or delete the installed application objects
   — then re-run rollback.
2. **Backup package reinstall:** install a package exported before the change so its
   authorizations overwrite the installed ones, then remove any leftovers and
   re-run rollback.
3. **Database restore (full revert):** restore the instance database from a
   pre-migration backup. This also removes the installed package content, so use
   it when a complete return to the prior state is required.
`--force` never deletes other objects' rows — it only still removes
journal-created hierarchy edges.

## What rollback cannot restore

- `IDENTITY` gaps (deleted `group_id`s are gone forever — harmless, IDs are
  never matched on; packaging keys on `guid`).
- Membership added manually after import (members were never managed by
  this toolkit; leaving added users in place is intentional).
- Audit columns on pre-existing rows touched by `--fix-guids` other than the
  guid itself (update_date/login reflect the fix — documented in the journal).

## Cascading / cache notes

- Direct SQL bypasses Archer broker side effects (task-permission precompute,
  content-permission recalculation jobs, `UserFieldPermission` cache flush,
  security-event log). For **empty new placeholders** there is nothing to recalculate,
  and the package install itself runs through the brokers afterwards, which
  trigger those jobs for the installed authorizations. No manual recalc needed.
- If you import groups that will carry `cascade_group=1` authorizations with
  large existing hierarchies, expect Archer's normal post-install permission
  recalculation jobs (same as any package install) — not caused by this script.
- New groups are found by the installer's GUID lookup straight from the DB, so mapping
  works immediately. If the Manage-Groups tree doesn't show them, refresh /
  re-login; an app-pool recycle is optional, never required for correctness.
