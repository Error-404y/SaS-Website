"""Private and alliance chat persistence for SaS approved accounts and admins.

Only server-derived sender identities are accepted; no client-supplied sender,
role, recipient display name, or membership information is trusted.
"""
from datetime import datetime, timedelta, timezone

MAX_MESSAGE = 2000
MAX_HISTORY = 80
MAX_MESSAGES_PER_MINUTE = 30
ADMIN = "admin"
ALLIANCE = "alliance"


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_key TEXT NOT NULL,
        sender_key TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS chat_thread_messages
        ON chat_messages(thread_key,id DESC)""")
    db.execute("""CREATE INDEX IF NOT EXISTS chat_sender_rate
        ON chat_messages(sender_key,created_at)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_reads (
        member_key TEXT NOT NULL,
        thread_key TEXT NOT NULL,
        last_read_id INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(member_key,thread_key)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS chat_read_member
        ON chat_reads(member_key)""")
    # No email or password data is duplicated in the messenger.


def member_key(member_id):
    return f"member:{int(member_id)}"


def member_profile(row):
    return {"id": member_key(row["id"]), "username": row["username"],
            "player_name": row["player_name"]}


def approved_member(db, key):
    if not isinstance(key, str) or not key.startswith("member:"):
        return None
    suffix = key[7:]
    if not suffix.isdecimal() or len(suffix) > 16:
        return None
    return db.execute("""SELECT id,username,player_name FROM members
        WHERE id=? AND status='approved'""", (int(suffix),)).fetchone()


def thread_for(db, actor, target):
    """Validate each private target and derive a canonical two-person thread key."""
    if target == ALLIANCE:
        return "alliance"
    if target == actor:
        raise ValueError("Choose another member to message.")
    if target != ADMIN and approved_member(db, target) is None:
        raise ValueError("This player is not available.")
    pair = sorted((actor, target))
    return "dm:" + "|".join(pair)


def valid_actor(db, actor):
    return actor == ADMIN or approved_member(db, actor) is not None


def contact_list(db, actor):
    rows = db.execute("""SELECT id,username,player_name FROM members
        WHERE status='approved' ORDER BY username COLLATE NOCASE,id LIMIT 1000""").fetchall()
    contacts = [{"id": ALLIANCE, "username": "SaS Alliance Chat",
                 "player_name": "Alliance group", "group": True}]
    if actor != ADMIN:
        contacts.append({"id": ADMIN, "username": "SaS Admin", "player_name": "Administrator", "group": False})
    for row in rows:
        profile = member_profile(row)
        if profile["id"] != actor:
            contacts.append({**profile, "group": False})
    return contacts


def summaries(db, actor):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    contacts = contact_list(db, actor)
    summaries_out = []
    for contact in contacts:
        target = contact["id"]
        thread = thread_for(db, actor, target)
        latest = db.execute("""SELECT id,sender_key,body,created_at
            FROM chat_messages WHERE thread_key=? ORDER BY id DESC LIMIT 1""",
            (thread,)).fetchone()
        seen = db.execute("""SELECT last_read_id FROM chat_reads
            WHERE member_key=? AND thread_key=?""", (actor, thread)).fetchone()
        last_id = seen["last_read_id"] if seen else 0
        unread = db.execute("""SELECT COUNT(*) AS total FROM chat_messages
            WHERE thread_key=? AND id>? AND sender_key!=?""",
            (thread, last_id, actor)).fetchone()["total"]
        summaries_out.append({**contact,
            "last_message": latest["body"][:100] if latest else "",
            "last_at": latest["created_at"] if latest else None,
            "last_id": latest["id"] if latest else 0,
            "last_sender": latest["sender_key"] if latest else None,
            "unread": unread})
    # Group is always discoverable, then sort remaining chats by newest message.
    group = summaries_out[:1]
    rest = sorted(summaries_out[1:], key=lambda r: (-r["last_id"], r["username"].casefold()))
    return group + rest


def history(db, actor, target):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    thread = thread_for(db, actor, target)
    # Return recent messages in chronological order.
    rows = db.execute("""SELECT id,sender_key,body,created_at FROM chat_messages
        WHERE thread_key=? ORDER BY id DESC LIMIT ?""",
        (thread, MAX_HISTORY)).fetchall()
    messages = [dict(row) for row in reversed(rows)]
    return messages


def send(db, actor, target, body):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    thread = thread_for(db, actor, target)
    if not isinstance(body, str):
        raise ValueError("Enter a message.")
    message = body.strip()
    if not message:
        raise ValueError("Enter a message.")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"Messages must be {MAX_MESSAGE} characters or fewer.")
    if any(ord(char) < 32 and char not in "\n\t" for char in message):
        raise ValueError("Invalid message characters.")
    created = now_utc()
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    recent = db.execute("""SELECT COUNT(*) FROM chat_messages
        WHERE sender_key=? AND created_at>=?""", (actor, since)).fetchone()[0]
    if recent >= MAX_MESSAGES_PER_MINUTE:
        raise ValueError("Too many messages. Try again in a minute.")
    cur = db.execute("""INSERT INTO chat_messages(thread_key,sender_key,body,created_at)
        VALUES(?,?,?,?)""", (thread,actor,message,created))
    return {"id": cur.lastrowid, "sender_key": actor, "body": message,
            "created_at": created}


def mark_read(db, actor, target):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    thread = thread_for(db, actor, target)
    last = db.execute("""SELECT COALESCE(MAX(id),0) AS id FROM chat_messages
        WHERE thread_key=?""", (thread,)).fetchone()["id"]
    db.execute("""INSERT INTO chat_reads(member_key,thread_key,last_read_id)
        VALUES(?,?,?) ON CONFLICT(member_key,thread_key) DO UPDATE SET
        last_read_id=MAX(chat_reads.last_read_id,excluded.last_read_id)""", (actor,thread,last))
    return last


def purge_member(db, member_id):
    """Destroy private messages when an account is permanently deleted."""
    key = member_key(member_id)
    rows = db.execute("""SELECT thread_key FROM chat_messages
        WHERE thread_key LIKE 'dm:%' AND
        (sender_key=? OR thread_key LIKE ? OR thread_key LIKE ?)""",
        (key, "dm:" + key + "|%", "dm:%|" + key)).fetchall()
    # Exact suffix/prefix matching: no accidental removal of member:12 for member:1.
    threads = {row["thread_key"] for row in rows}
    for thread in threads:
        people = thread[3:].split("|")
        if key in people:
            db.execute("DELETE FROM chat_messages WHERE thread_key=?", (thread,))
            db.execute("DELETE FROM chat_reads WHERE thread_key=?", (thread,))
    # Alliance messages no longer belong to the deleted account, but remain as
    # historical posts with sender anonymized.
    db.execute("UPDATE chat_messages SET sender_key='deleted' WHERE sender_key=? AND thread_key='alliance'", (key,))
    db.execute("DELETE FROM chat_reads WHERE member_key=?", (key,))
