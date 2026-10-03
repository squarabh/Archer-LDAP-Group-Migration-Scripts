#!/usr/bin/env python3
r"""Export Archer LDAP groups (read-only) to JSON.

Reads:  --server/--database (or --config JSON with .source) + --sql-user/--sql-password.
Writes: JSON {format, source, counts, groups, members, hierarchy, ldap_configs}.
Preflights auth BEFORE export; exit 3 with a clear hint when Windows
Integrated Auth is unavailable.

Examples:
  python Export-ArcherLdapGroups.py --server SQL01 --database ArcherProd --output .\exports\groups.json
  python Export-ArcherLdapGroups.py --config .\config\migration.config.json
"""
import argparse, datetime, getpass, json, os, sys


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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
            cn.autocommit = True
            try:
                cur = cn.cursor()
                cur.execute("SELECT SUSER_SNAME()")
                print(f"AUTH: method={'SQL login' if sql_user else 'Windows Integrated'} login={cur.fetchone()[0]}")
            except Exception as e:
                print("ERROR: auth preflight failed (Windows Integrated Auth likely unavailable): "
                      f"{e}\nHINT: re-run with --sql-user/--sql-password. No export performed.", file=sys.stderr)
                sys.exit(3)
            return cn
        except SystemExit:
            raise
        except Exception as e:
            errs.append(f"{drv}: {e}")
    print("ERROR: cannot connect (Windows Integrated Auth may be unavailable):\n  "
          + "\n  ".join(errs) + "\nHINT: re-run with --sql-user/--sql-password.", file=sys.stderr)
    sys.exit(1)


def q(cn, sql, params=()):
    cur = cn.cursor()
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description] if cur.description else []
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (datetime.datetime, datetime.date)):
                r[k] = v.isoformat()
    return rows


def main():
    ap = argparse.ArgumentParser(description="Export Archer LDAP groups (read-only)")
    ap.add_argument("--server", default=None)
    ap.add_argument("--database", default=None)
    ap.add_argument("--output", default=".\\exports\\ldap_groups_export.json")
    ap.add_argument("--config", default=None, help="JSON with {source:{server,database}}")
    ap.add_argument("--all", action="store_true", help="export ALL groups, not just LDAP ones")
    ap.add_argument("--include-system", action="store_true")
    ap.add_argument("--include-members", action="store_true",
                    help="also export user memberships (tblXGroupsUsers); omitted by default for privacy & packaging compatibility")
    ap.add_argument("--sql-user", default=os.environ.get("SQLUSER"))
    ap.add_argument("--sql-password", default=os.environ.get("SQLPASSWORD"))
    args = ap.parse_args()
    if args.config:
        cfg = load_config(args.config).get("source", {})
        args.server = args.server or cfg.get("server")
        args.database = args.database or cfg.get("database")
    if not args.server or not args.database:
        print("ERROR: --server/--database (or --config) required.", file=sys.stderr)
        sys.exit(1)
    if args.sql_password and any(arg.startswith("--sql-password") for arg in sys.argv):
        print("SECURITY WARNING: Passing passwords via command-line arguments exposes credentials in process tables. "
              "Use $env:SQLPASSWORD or interactive prompt instead.", file=sys.stderr)
    if args.sql_user and not args.sql_password:
        args.sql_password = getpass.getpass(f"SQL password for {args.sql_user}: ")

    cn = connect(args.server, args.database, args.sql_user, args.sql_password)
    where = "WHERE g.ldap_config_id IS NOT NULL" if not args.all else "WHERE 1=1"
    if not args.include_system:
        where += " AND g.[system] = 0 AND g.everyone = 0"

    groups = q(cn, f"""SELECT g.group_id, g.group_name, g.group_desc, g.create_date,
               g.create_login, g.update_date, g.update_login, g.everyone, g.guid,
               g.[system], g.distinguished_name, g.ldap_config_id,
               g.default_home_dashboard_id, g.default_home_workspace_id
        FROM dbo.tblGroup g {where} ORDER BY g.group_id""")
    if not groups:
        print("ERROR: no groups matched. Try --all/--include-system.", file=sys.stderr)
        sys.exit(2)

    gids = [g["group_id"] for g in groups]

    # Query members with batching (chunk size <= 500 to stay under SQL Server's 2,100 parameter limit)
    members = []
    if args.include_members:
        for batch in chunked(gids, size=500):
            ph = ",".join("?" * len(batch))
            rows = q(cn, f"""SELECT u.group_id, u.user_id, usr.user_username, usr.user_display_name,
                       usr.distinguished_name AS user_dn, usr.ldap_config_id AS user_ldap
                FROM dbo.tblXGroupsUsers u LEFT JOIN dbo.tblUser usr ON usr.user_id = u.user_id
                WHERE u.group_id IN ({ph}) ORDER BY u.group_id, u.user_id""", batch)
            members.extend(rows)
    else:
        print("INFO: User memberships omitted (not required for Archer packaging). Use --include-members for auditing.")

    # Query hierarchy with batching (size=500 -> 1000 params max, safely under 2100 limit)
    hierarchy = []
    for batch in chunked(gids, size=500):
        ph = ",".join("?" * len(batch))
        rows = q(cn, f"""SELECT parent_group_id, child_group_id FROM dbo.tblGroupRelationships
            WHERE parent_group_id IN ({ph}) OR child_group_id IN ({ph})
            ORDER BY parent_group_id, child_group_id""", batch + batch)
        hierarchy.extend(rows)

    try:
        ldap_cfgs = q(cn, """SELECT config_id, ldap_server, ldap_active_directory_domain,
            single_sign_on, group_role_mapping, ldap_config_name, is_default,
            user_domain, use_ssl FROM dbo.tblLDAPConfig ORDER BY config_id""")
        for c in ldap_cfgs:  # never export secrets
            c.pop("ldap_password", None)
    except Exception as e:
        ldap_cfgs = [{"_warning": f"tblLDAPConfig unreadable: {e}"}]

    payload = {
        "format": "archer-ldap-groups/v1",
        "source": {"server": args.server, "database": args.database,
                   "exported_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "filter_ldap_only": not args.all},
        "counts": {"groups": len(groups), "member_rows": len(members), "hierarchy_rows": len(hierarchy)},
        "groups": groups, "members": members, "hierarchy": hierarchy, "ldap_configs": ldap_cfgs,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"OK: {len(groups)} groups, {len(members)} member rows, "
          f"{len(hierarchy)} hierarchy rows -> {args.output}")


if __name__ == "__main__":
    main()
