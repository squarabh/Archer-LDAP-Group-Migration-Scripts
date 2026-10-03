#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-MIT
r"""Import LDAP-group placeholders into the TARGET Archer instance DB (idempotent).

Creates LOCAL groups (ldap_config_id/distinguished_name NULL) with the EXACT
source GUIDs so Archer packaging auto-maps them (match key = guid,
UQ_tblGroup_GUID). group_id values are NOT copied (IDENTITY).

Modes:
  --verify-only : SELECT only, rollback, prints matched/missing/conflicts.
  (default)     : create-missing + hierarchy edges, writes a ROLLBACK JOURNAL.
  --fix-guids   : additionally UPDATE guid of same-name rows holding a wrong
                  guid (typical after manual UI creation, which mints new GUIDs).

Rollback: every write run saves --journal (default <input>.rollback.json)
  listing created group_ids/guids, added hierarchy edges, and guid fixes
  (old->new). Feed it to Rollback-ArcherLdapGroups.py to revert.

  Rollback succeeds ONLY while nothing else references the created rows
  (e.g. run it BEFORE installing the package). After package install the
  database FKs intentionally block group deletion — see docs/ROLLBACK.md.

Safety: explicit transactions, SET QUOTED_IDENTIFIER/ANSI_NULLS ON,
  auth+permission preflight BEFORE any write (exit 3), never DELETEs except
  via the rollback script, never touches system/everyone rows.

Examples:
  python Import-ArcherLdapGroups.py --server TSQL --database ArcherTarget --input .\exports\groups.json --verify-only
  python Import-ArcherLdapGroups.py --server TSQL --database ArcherTarget --input .\exports\groups.json
  python Import-ArcherLdapGroups.py --server TSQL --database ArcherTarget --input .\exports\groups.json --fix-guids
"""
import argparse, datetime, getpass, json, os, sys, uuid


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def chunked(iterable, size=500):
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]


def build_conn_str(drv, server, database, sql_user, sql_password):
    if sql_user:
        return (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};"
                f"UID={sql_user};PWD={sql_password};TrustServerCertificate=yes;Encrypt=yes;")
    if "18" in drv or "17" in drv:
        return (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};"
                "Trusted_Connection=yes;TrustServerCertificate=yes;Encrypt=yes;")
    return f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"


def preflight_auth(cur, sql_user):
    try:
        cur.execute("SELECT SUSER_SNAME(), ISNULL(IS_SRVROLEMEMBER('sysadmin'),0), "
                    "ISNULL(IS_MEMBER('db_owner'),0), ISNULL(IS_MEMBER('db_datawriter'),0)")
        login_, is_sa, is_owner, can_write = cur.fetchone()
        print(f"AUTH: method={'SQL login' if sql_user else 'Windows Integrated'} login={login_} "
              f"sysadmin={is_sa} db_owner={is_owner} datawriter={can_write}")
        if is_owner != 1 and can_write != 1 and is_sa != 1:
            print("ERROR: login cannot INSERT into dbo.tblGroup "
                  "(needs db_datawriter/db_owner/sysadmin). No changes made.", file=sys.stderr)
            sys.exit(3)
        cur.execute("SELECT DB_NAME()")
        db = cur.fetchone()[0]
        if db.lower() in ("master", "model", "msdb", "tempdb"):
            print(f"ERROR: connected to [{db}] — point --database at the TARGET Archer "
                  "instance DB. No changes made.", file=sys.stderr)
            sys.exit(3)
        return login_
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: auth preflight failed (Windows Integrated Auth likely unavailable): {e}\n"
              "HINT: re-run with --sql-user/--sql-password. No changes made.", file=sys.stderr)
        sys.exit(3)


def resolve_login_id(cur, requested_login_id):
    try:
        cur.execute("SELECT user_id FROM dbo.tblUser WHERE user_id = ?", requested_login_id)
        if cur.fetchone():
            return requested_login_id
        cur.execute("SELECT TOP 1 user_id FROM dbo.tblUser WHERE user_username = 'sysadmin'")
        row = cur.fetchone()
        if row:
            print(f"INFO: user_id={requested_login_id} not found in tblUser; resolved to sysadmin (user_id={row[0]}).")
            return row[0]
        cur.execute("SELECT TOP 1 user_id FROM dbo.tblUser ORDER BY user_id ASC")
        row = cur.fetchone()
        fallback_id = row[0] if row else requested_login_id
        print(f"INFO: user_id={requested_login_id} not found in tblUser; falling back to user_id={fallback_id}.")
        return fallback_id
    except Exception:
        return requested_login_id


def connect(server, database, sql_user, sql_password):
    import pyodbc
    errs = []
    for drv in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"):
        try:
            cn = pyodbc.connect(build_conn_str(drv, server, database, sql_user, sql_password), timeout=15)
            cn.autocommit = False
            cur = cn.cursor()
            cur.execute("SET QUOTED_IDENTIFIER ON; SET ANSI_NULLS ON;")
            return cn
        except Exception as e:
            errs.append(f"{drv}: {e}")
    print("ERROR: cannot connect (Windows Integrated Auth may be unavailable):\n  "
          + "\n  ".join(errs) + "\nHINT: re-run with --sql-user/--sql-password.", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Import LDAP-group placeholders (idempotent)")
    ap.add_argument("--server", default=None)
    ap.add_argument("--database", default=None)
    ap.add_argument("--config", default=None, help="JSON with {target:{server,database}}")
    ap.add_argument("--input", required=True)
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--fix-guids", action="store_true")
    ap.add_argument("--login-id", type=int, default=2)
    ap.add_argument("--journal", default=None, help="rollback journal path (default: <input>.rollback.json)")
    ap.add_argument("--emit-sql", default=None, help="also write a standalone SSMS .sql loader for this input")
    ap.add_argument("--sql-user", default=os.environ.get("SQLUSER"))
    ap.add_argument("--sql-password", default=os.environ.get("SQLPASSWORD"))
    args = ap.parse_args()
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            tgt = json.load(f).get("target", {})
        args.server = args.server or tgt.get("server")
        args.database = args.database or tgt.get("database")
    if not args.server or not args.database:
        print("ERROR: --server/--database (or --config) required.", file=sys.stderr)
        sys.exit(1)
    if args.sql_password and any(arg.startswith("--sql-password") for arg in sys.argv):
        print("SECURITY WARNING: Passing passwords via command-line arguments exposes credentials in process tables. "
              "Use $env:SQLPASSWORD or interactive prompt instead.", file=sys.stderr)
    if args.sql_user and not args.sql_password:
        args.sql_password = getpass.getpass(f"SQL password for {args.sql_user}: ")
    args.journal = args.journal or (args.input + ".rollback.json")

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)
    groups = data.get("groups", [])
    hier = data.get("hierarchy", [])
    if not groups:
        print("ERROR: input has no groups", file=sys.stderr)
        sys.exit(1)

    # Validate input shape + GUID formats upfront (fail fast, before connecting)
    for i, g in enumerate(groups):
        if not isinstance(g, dict) or g.get("guid") is None or g.get("group_name") is None:
            print(f"ERROR: groups[{i}] must be an object with 'guid' and 'group_name'.", file=sys.stderr)
            sys.exit(1)
        if not is_valid_uuid(g.get("guid")):
            print(f"ERROR: group '{g.get('group_name')}' contains invalid GUID: {g.get('guid')}", file=sys.stderr)
            sys.exit(1)
    for i, h in enumerate(hier):
        if not isinstance(h, dict) or h.get("parent_group_id") is None or h.get("child_group_id") is None:
            print(f"ERROR: hierarchy[{i}] must be an object with 'parent_group_id' and 'child_group_id'.", file=sys.stderr)
            sys.exit(1)

    cn = connect(args.server, args.database, args.sql_user, args.sql_password)
    cur = cn.cursor()
    preflight_auth(cur, args.sql_user)
    effective_login_id = resolve_login_id(cur, args.login_id)
    stats = {"matched": 0, "created": [], "guid_fixed": [], "name_conflicts": [], "hier_added": []}

    try:
        for g in groups:
            guid, name = g["guid"], g["group_name"]
            cur.execute("SELECT group_id, group_name FROM dbo.tblGroup WHERE guid = ?", guid)
            row = cur.fetchone()
            if row:
                stats["matched"] += 1
                if row[1] != name:
                    stats["name_conflicts"].append({"guid": guid, "target_name": row[1], "source_name": name})
                continue
            cur.execute("SELECT group_id, guid FROM dbo.tblGroup WHERE group_name = ?", name)
            same = cur.fetchall()
            if same and args.fix_guids and not args.verify_only:
                cur.execute("UPDATE dbo.tblGroup SET guid=?, update_date=GETDATE(), update_login=? WHERE group_id=?",
                            guid, effective_login_id, same[0][0])
                stats["guid_fixed"].append({"group_id": same[0][0], "name": name,
                                            "old_guid": str(same[0][1]), "new_guid": guid})
                stats["matched"] += 1
                continue
            if same:
                stats["name_conflicts"].append({"guid": guid, "source_name": name,
                    "note": f"{len(same)} same-name row(s) with different guid; re-run with --fix-guids"})
                continue
            if args.verify_only:
                continue
            now = datetime.datetime.now()
            cur.execute("""INSERT INTO dbo.tblGroup (group_name, group_desc, create_date, create_login,
              update_date, update_login, everyone, guid, [system], distinguished_name, ldap_config_id)
              VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              name, g.get("group_desc"), now, effective_login_id, now, effective_login_id,
              int(bool(g.get("everyone", 0))), guid, 0, None, None)
            cur.execute("SELECT group_id FROM dbo.tblGroup WHERE guid=?", guid)
            stats["created"].append({"group_id": cur.fetchone()[0], "name": name, "guid": guid})

        if hier and not args.verify_only:
            src_to_guid = {g["group_id"]: g["guid"] for g in groups}
            def tid(guid_val):
                cur.execute("SELECT group_id FROM dbo.tblGroup WHERE guid=?", guid_val)
                r = cur.fetchone()
                return r[0] if r else None
            for h in hier:
                pg, cg = src_to_guid.get(h["parent_group_id"]), src_to_guid.get(h["child_group_id"])
                if not pg or not cg:
                    continue
                pt, ct = tid(pg), tid(cg)
                if not pt or not ct:
                    continue
                cur.execute("SELECT 1 FROM dbo.tblGroupRelationships WHERE parent_group_id=? AND child_group_id=?", pt, ct)
                if not cur.fetchone():
                    cur.execute("INSERT INTO dbo.tblGroupRelationships "
                                "(parent_group_id, child_group_id, create_date, create_login) VALUES (?,?,GETDATE(),?)",
                                pt, ct, effective_login_id)
                    stats["hier_added"].append({"parent_group_id": pt, "child_group_id": ct})

        if args.verify_only:
            cn.rollback()
            print(f"VERIFY target={args.database}: {stats['matched']} matched, "
                  f"{len(groups)-stats['matched']} missing, conflicts={len(stats['name_conflicts'])}")
            for c in stats["name_conflicts"]:
                print("  CONFLICT:", c)
            print("No changes made (--verify-only).")
            return

        cn.commit()
        journal = {"target": {"server": args.server, "database": args.database},
                   "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "input": args.input, "created_groups": stats["created"],
                   "guid_fixes": stats["guid_fixed"], "added_edges": stats["hier_added"]}
        with open(args.journal, "w", encoding="utf-8") as f:
            json.dump(journal, f, indent=2)
        print(f"OK target={args.database}: matched={stats['matched']} created={len(stats['created'])} "
              f"guid_fixed={len(stats['guid_fixed'])} hierarchy_added={len(stats['hier_added'])}")
        print(f"Journal for rollback: {args.journal}")
        for c in stats["name_conflicts"]:
            print("  ATTENTION:", c)

        # Batch installer check to avoid 2,100 parameter limit
        guids = [g["guid"] for g in groups]
        cur2 = cn.cursor()
        total_matched = 0
        for batch in chunked(guids, size=500):
            cur2.execute(f"SELECT COUNT(*) FROM dbo.tblGroup WHERE guid IN ({','.join('?'*len(batch))})", batch)
            total_matched += cur2.fetchone()[0]
        print(f"Installer check (GUID match): {total_matched}/{len(guids)} matched (need all).")

        if args.emit_sql:
            write_sql(args.emit_sql, data, effective_login_id)
            print(f"Standalone SQL also written: {args.emit_sql}")
    except Exception as e:
        cn.rollback()
        print(f"ERROR: rolled back: {e}", file=sys.stderr)
        sys.exit(1)


def write_sql(path, data, login_id=2):
    lines = ["/* Auto-generated standalone loader — idempotent, guid + same-name guarded like the importer.",
             "   NOTE: no auth preflight, no hierarchy edges. For the fully guarded SSMS path use",
             "   the SQL sub-project's Import-ArcherLdapGroups.sql instead. */",
             "SET NOCOUNT ON;", "SET QUOTED_IDENTIFIER ON;", "SET ANSI_NULLS ON;", "GO",
             "IF OBJECT_ID('tempdb..#Src') IS NOT NULL DROP TABLE #Src;",
             "CREATE TABLE #Src (group_name NVARCHAR(500), guid UNIQUEIDENTIFIER);"]
    for g in data.get("groups", []):
        guid_str = str(g.get("guid", "")).strip()
        if not is_valid_uuid(guid_str):
            continue
        clean_name = str(g.get("group_name", "")).replace("'", "''")
        lines.append(f"INSERT INTO #Src VALUES (N'{clean_name}', '{guid_str}');")
    lines += ["INSERT INTO dbo.tblGroup (group_name, group_desc, create_date, create_login, update_date,",
              f" update_login, everyone, guid, [system], distinguished_name, ldap_config_id)",
              f"SELECT s.group_name, NULL, GETDATE(), {int(login_id)}, GETDATE(), {int(login_id)}, 0, s.guid, 0, NULL, NULL",
              "FROM #Src s WHERE NOT EXISTS (SELECT 1 FROM dbo.tblGroup g WHERE g.guid = s.guid)",
              "  AND NOT EXISTS (SELECT 1 FROM dbo.tblGroup g2 WHERE g2.group_name = s.group_name AND g2.guid <> s.guid);",
              "PRINT 'Inserted: ' + CAST(@@ROWCOUNT AS VARCHAR(10));",
              "GO"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
