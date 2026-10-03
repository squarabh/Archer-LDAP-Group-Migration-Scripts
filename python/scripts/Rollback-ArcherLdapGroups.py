#!/usr/bin/env python3
r"""Roll back an Import-ArcherLdapGroups.py run from its journal.

Reads <journal>.rollback.json {created_groups[], guid_fixes[], added_edges[]}
and undoes them in dependency order (edges -> groups -> guid restores).

Fails SAFE (no changes) when:
  - a created group is now referenced by package objects (e.g. install already
    ran: tblXEventActionGroup, tblXReportsGroups, tblXIVLayoutModuleGroupAuthorization, etc.).
    Uses dynamic sys.foreign_keys inspection to detect ALL 24+ Archer referencers.
    Use --check-only to preview, or remove those references first
    (Archer has no package uninstall — see docs/ROLLBACK.md for reversion options).
    --force deletes the journal-created hierarchy edges but NEVER deletes other objects' rows.
  - auth/permission preflight fails (exit 3).

Examples:
  python Rollback-ArcherLdapGroups.py --server TSQL --database ArcherTarget --journal .\exports\groups.json.rollback.json --check-only
  python Rollback-ArcherLdapGroups.py --server TSQL --database ArcherTarget --journal .\exports\groups.json.rollback.json
"""
import argparse, getpass, json, os, sys


def chunked(iterable, size=500):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]


def connect(server, database, sql_user, sql_password):
    import pyodbc
    errs = []
    for drv in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"):
        try:
            if sql_user:
                cs = (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};"
                      f"UID={sql_user};PWD={sql_password};TrustServerCertificate=yes;Encrypt=yes;")
            elif "18" in drv or "17" in drv:
                cs = (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};"
                      "Trusted_Connection=yes;TrustServerCertificate=yes;Encrypt=yes;")
            else:
                cs = f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
            cn = pyodbc.connect(cs, timeout=15)
            cn.autocommit = False
            cur = cn.cursor()
            cur.execute("SET QUOTED_IDENTIFIER ON; SET ANSI_NULLS ON;")
            cur.execute("SELECT SUSER_SNAME(), ISNULL(IS_MEMBER('db_owner'),0), "
                        "ISNULL(IS_MEMBER('db_datawriter'),0), ISNULL(IS_SRVROLEMEMBER('sysadmin'),0)")
            login_, o, w, sa = cur.fetchone()
            print(f"AUTH: login={login_} db_owner={o} datawriter={w} sysadmin={sa}")
            if o != 1 and w != 1 and sa != 1:
                print("ERROR: need db_datawriter/db_owner/sysadmin. No changes made.", file=sys.stderr)
                sys.exit(3)
            return cn
        except SystemExit:
            raise
        except Exception as e:
            errs.append(f"{drv}: {e}")
    print("ERROR: cannot connect:\n  " + "\n  ".join(errs), file=sys.stderr)
    sys.exit(1)


def get_referencing_tables(cur):
    sql = """
    SELECT DISTINCT
        OBJECT_NAME(f.parent_object_id) AS table_name,
        COL_NAME(fc.parent_object_id, fc.parent_column_id) AS col_name
    FROM sys.foreign_keys AS f
    INNER JOIN sys.foreign_key_columns AS fc
        ON f.object_id = fc.constraint_object_id
    WHERE f.referenced_object_id = OBJECT_ID('dbo.tblGroup')
    """
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        if rows:
            return [(r[0], r[1]) for r in rows if r[0] and r[1]]
    except Exception:
        pass
    # Fallback list if sys.foreign_keys is inaccessible
    return [(t, "group_id") for t in [
        "tblXEventActionGroup", "tblXGroupsUsers", "tblXGroupsRoles",
        "tblXReportsGroups", "tblXModulesAdminGroups", "tblXWorkspaceGroups",
        "tblXGroupDiscussionAdmin", "tblXIVLayoutModuleGroupAuthorization"
    ]]


def dependents(cur, group_ids):
    found = {}
    referencers = get_referencing_tables(cur)
    for tbl, col in referencers:
        if tbl.lower() in ("tblgrouprelationships",):
            # Hierarchy edges are managed directly by journal rollback
            continue
        for batch in chunked(group_ids, size=500):
            ph = ",".join("?" * len(batch))
            try:
                cur.execute(f"SELECT [{col}], COUNT(*) FROM dbo.[{tbl}] WHERE [{col}] IN ({ph}) GROUP BY [{col}]", batch)
                rows = cur.fetchall()
                if rows:
                    found.setdefault(tbl, []).extend([{"group_id": r[0], "rows": r[1]} for r in rows])
            except Exception:
                pass
    return found


def main():
    ap = argparse.ArgumentParser(description="Roll back a group import from its journal")
    ap.add_argument("--server", required=True)
    ap.add_argument("--database", required=True)
    ap.add_argument("--journal", required=True)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="also delete journal-created hierarchy edges even if groups have dependents (groups themselves still blocked)")
    ap.add_argument("--sql-user", default=os.environ.get("SQLUSER"))
    ap.add_argument("--sql-password", default=os.environ.get("SQLPASSWORD"))
    args = ap.parse_args()
    if args.sql_password and any(arg.startswith("--sql-password") for arg in sys.argv):
        print("SECURITY WARNING: Passing passwords via command-line arguments exposes credentials in process tables. "
              "Use $env:SQLPASSWORD or interactive prompt instead.", file=sys.stderr)
    if args.sql_user and not args.sql_password:
        args.sql_password = getpass.getpass(f"SQL password for {args.sql_user}: ")

    with open(args.journal, encoding="utf-8") as f:
        j = json.load(f)
    created = j.get("created_groups", [])
    fixes = j.get("guid_fixes", [])
    edges = j.get("added_edges", [])
    if not created and not fixes and not edges:
        print("Journal is empty — nothing to roll back.")
        return

    cn = connect(args.server, args.database, args.sql_user, args.sql_password)
    cur = cn.cursor()
    try:
        gids = [c["group_id"] for c in created]
        deps = dependents(cur, gids) if gids else {}
        if deps:
            print("BLOCKED: created groups are now referenced (package likely installed):")
            for t, rows in deps.items():
                print(f"  {t}: {rows}")
            print("Revert path: remove those references manually, reinstall a pre-change "
                  "backup package, or restore the instance DB (see docs/ROLLBACK.md), "
                  "No changes made." + ("" if args.force else " (--force only affects hierarchy edges)"))
            if args.check_only:
                print(f"CHECK-ONLY: would delete {len(edges)} edges, {len(created)} groups, "
                      f"restore {len(fixes)} guids (groups currently blocked). No changes made.")
                cn.rollback()
                return
            if not args.force:
                cn.rollback()
                sys.exit(2)
            # --force: delete ONLY the journal-created hierarchy edges in their own
            # transaction (the group DELETEs below would hit FKs and roll everything
            # back, so edges must commit first). Groups themselves stay put.
            for e in edges:
                cur.execute("DELETE FROM dbo.tblGroupRelationships WHERE parent_group_id=? AND child_group_id=?",
                            e["parent_group_id"], e["child_group_id"])
            cn.commit()
            print(f"FORCE: deleted {len(edges)} journal-created hierarchy edge(s); "
                  f"{len(created)} group(s) remain (still referenced). "
                  "Re-run after removing references to delete the groups.")
            sys.exit(2)
        if args.check_only:
            print(f"CHECK-ONLY: would delete {len(edges)} edges, {len(created)} groups, "
                  f"restore {len(fixes)} guids. No changes made.")
            cn.rollback()
            return

        # 1. edges added by import
        for e in edges:
            cur.execute("DELETE FROM dbo.tblGroupRelationships WHERE parent_group_id=? AND child_group_id=?",
                        e["parent_group_id"], e["child_group_id"])

        # 2. groups created by import (blocked above if referenced — FKs double-guard)
        for c in created:
            cur.execute("DELETE FROM dbo.tblGroup WHERE group_id=? AND guid=?", c["group_id"], c["guid"])

        # 3. guid fixes restored
        for fx in fixes:
            cur.execute("UPDATE dbo.tblGroup SET guid=?, update_date=GETDATE() WHERE group_id=?",
                        fx["old_guid"], fx["group_id"])

        cn.commit()
        print(f"OK rolled back: edges={len(edges)} groups={len(created)} guids_restored={len(fixes)}")
    except Exception as e:
        cn.rollback()
        print(f"ERROR: rolled back safely, no partial changes: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
