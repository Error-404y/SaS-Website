"""Delayed, reversible account and network restrictions for SaS.

Bans become effective only after a two-hour admin review period. All checks
consult persistent SQLite state, not background jobs or CSS. Admins are
intentionally exempt so a shared-address ban cannot lock out moderation.
"""
import ipaddress
import json
import re
import time

WAIT_SECONDS = 2 * 3600
KINDS = ("ip", "email", "name", "everything")


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS moderation_bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('ip','email','name','everything')),
        selectors_json TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        effective_at INTEGER NOT NULL,
        cancelled_at INTEGER,
        revoked_at INTEGER
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS moderation_ban_status
        ON moderation_bans(effective_at,cancelled_at,revoked_at)""")
    db.execute("""CREATE TABLE IF NOT EXISTS member_ips (
        member_id INTEGER PRIMARY KEY,
        last_ip TEXT NOT NULL,
        seen_at INTEGER NOT NULL
    )""")


def normalize_ip(raw):
    try:
        return str(ipaddress.ip_address(raw))
    except (ValueError, TypeError):
        return ""


def record_ip(db, member_id, remote_ip):
    address = normalize_ip(remote_ip)
    if address:
        db.execute("""INSERT INTO member_ips(member_id,last_ip,seen_at)
            VALUES(?,?,?) ON CONFLICT(member_id) DO UPDATE SET
            last_ip=excluded.last_ip,seen_at=excluded.seen_at""",
            (int(member_id), address, int(time.time())))


def member_ip(db, member_id):
    row = db.execute("SELECT last_ip FROM member_ips WHERE member_id=?", (member_id,)).fetchone()
    return row["last_ip"] if row else ""


def member_selectors(db, member_id, kind):
    member = db.execute("""SELECT id,username,player_name,email FROM members
        WHERE id=?""",(member_id,)).fetchone()
    if member is None:
        raise LookupError("Account not found.")
    if kind not in KINDS:
        raise ValueError("Choose IP, Email, Name or Everything.")
    ip = member_ip(db,member_id)
    selectors = {}
    if kind in ("ip","everything"):
        if not ip:
            raise ValueError("No verified IP recorded for this account. They must sign in first.")
        selectors["ip"] = ip
    if kind in ("email","everything"):
        selectors["email"] = member["email"].strip().casefold()
    if kind in ("name","everything"):
        selectors["names"] = list({member["username"].strip().casefold(),
                                   member["player_name"].strip().casefold()})
    return selectors


def queue(db, member_id, kind, reason="", now=None):
    now = int(time.time()) if now is None else int(now)
    if not isinstance(reason,str) or len(reason)>500:
        raise ValueError("Reason must be 500 characters or less.")
    selectors = member_selectors(db,member_id,kind)
    # Prevent rapidly queuing the same type for the same account.
    existing = db.execute("""SELECT id FROM moderation_bans WHERE member_id=? AND kind=?
        AND cancelled_at IS NULL AND revoked_at IS NULL""",(member_id,kind)).fetchone()
    if existing:
        raise ValueError("An active or pending ban of this type already exists.")
    cur=db.execute("""INSERT INTO moderation_bans(
        member_id,kind,selectors_json,reason,created_at,effective_at)
        VALUES(?,?,?,?,?,?)""",(member_id,kind,json.dumps(selectors,sort_keys=True),reason.strip(),
                                now,now+WAIT_SECONDS))
    return cur.lastrowid


def list_bans(db, now=None):
    now=int(time.time()) if now is None else int(now)
    results=[]
    for row in db.execute("""SELECT b.*,m.username,m.player_name FROM moderation_bans b
        LEFT JOIN members m ON m.id=b.member_id
        ORDER BY CASE WHEN cancelled_at IS NULL AND revoked_at IS NULL THEN 0 ELSE 1 END,
          created_at DESC LIMIT 300"""):
        item=dict(row)
        item.pop("selectors_json",None)  # admin UI does not need sensitive ban IPs
        item["username"]=item["username"] or "(deleted account)"
        item["status"]=("cancelled" if item["cancelled_at"] is not None else
                        "revoked" if item["revoked_at"] is not None else
                        "active" if item["effective_at"] <= now else "pending")
        results.append(item)
    return results


def stop(db, ban_id, now=None):
    now=int(time.time()) if now is None else int(now)
    row=db.execute("SELECT * FROM moderation_bans WHERE id=?",(ban_id,)).fetchone()
    if not row:
        raise LookupError("Ban not found.")
    if row["cancelled_at"] is not None or row["revoked_at"] is not None:
        raise ValueError("This ban has already been cancelled or removed.")
    column="cancelled_at" if row["effective_at"]>now else "revoked_at"
    db.execute("UPDATE moderation_bans SET "+column+"=? WHERE id=?",(now,ban_id))
    return column=="cancelled_at"


def is_banned(db, *, ip="", email="", username="", player_name="", now=None):
    now=int(time.time()) if now is None else int(now)
    ip=normalize_ip(ip)
    email=str(email).strip().casefold()
    names={str(username).strip().casefold(),str(player_name).strip().casefold()}-{""}
    for row in db.execute("""SELECT selectors_json FROM moderation_bans
        WHERE cancelled_at IS NULL AND revoked_at IS NULL AND effective_at<=?""",(now,)):
        selectors=json.loads(row["selectors_json"])
        if (ip and selectors.get("ip")==ip) or (email and selectors.get("email")==email):
            return True
        if names.intersection(selectors.get("names",[])):
            return True
    return False
