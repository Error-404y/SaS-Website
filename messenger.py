"""Private and alliance chat persistence for SaS approved accounts and admins.

Only server-derived sender identities are accepted; no client-supplied sender,
role, recipient display name, or membership information is trusted.
"""
from datetime import datetime, timedelta, timezone
import messenger_features as rich

MAX_MESSAGE = 2000
MAX_HISTORY = 80
MAX_MESSAGES_PER_MINUTE = 30
PRESENCE_ONLINE_SECONDS = 75
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
    db.execute("""CREATE TABLE IF NOT EXISTS chat_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        creator_key TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_group_members (
        group_id INTEGER NOT NULL,
        member_key TEXT NOT NULL,
        PRIMARY KEY(group_id,member_key)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS chat_groups_by_member
        ON chat_group_members(member_key,group_id)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_group_invites (
        group_id INTEGER NOT NULL,
        member_key TEXT NOT NULL,
        invited_by TEXT NOT NULL,
        invited_at TEXT NOT NULL,
        joined_at TEXT,
        PRIMARY KEY(group_id,member_key)
    )""")
    db.execute("""CREATE INDEX IF NOT EXISTS chat_group_invites_member
        ON chat_group_invites(member_key,joined_at)""")
    # Older groups already have accepted memberships in chat_group_members.
    # Do not turn any of those existing memberships back into invitations.
    # Existing approved accounts retain their previous shared-chat access.
    existing = db.execute("""SELECT 1 FROM sqlite_master WHERE type='table'
        AND name='chat_alliance_members'""").fetchone()
    db.execute("""CREATE TABLE IF NOT EXISTS chat_alliance_members (
        member_key TEXT PRIMARY KEY,
        joined_at TEXT NOT NULL
    )""")
    if not existing:
        db.execute("""INSERT OR IGNORE INTO chat_alliance_members(member_key, joined_at)
            SELECT 'member:' || id, ? FROM members WHERE status='approved'""",
            (now_utc(),))
    db.execute("""CREATE TABLE IF NOT EXISTS chat_presence (
        member_key TEXT PRIMARY KEY,
        last_seen_at INTEGER NOT NULL
    )""")
    # Presence is ephemeral: retain recent last-seen times but prune old records.
    db.execute("DELETE FROM chat_presence WHERE last_seen_at < CAST(strftime('%s','now') AS INTEGER)-7776000")
    rich.setup(db)
    # No email or password data is duplicated in the messenger.


def heartbeat(db, actor):
    """Record activity only for an authenticated, approved player or admin."""
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    db.execute("""INSERT INTO chat_presence(member_key,last_seen_at)
        VALUES(?,CAST(strftime('%s','now') AS INTEGER))
        ON CONFLICT(member_key) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
        (actor,))


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


def alliance_joined(db, actor):
    if actor == ADMIN:
        return True
    return db.execute("SELECT 1 FROM chat_alliance_members WHERE member_key=?",
                      (actor,)).fetchone() is not None


def join_alliance(db, actor):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    if actor == ADMIN:
        return False
    if alliance_joined(db, actor):
        return False
    member = approved_member(db, actor)
    if member is None:
        raise PermissionError("Approved account required.")
    stamp = now_utc()
    db.execute("""INSERT INTO chat_alliance_members(member_key,joined_at)
                  VALUES(?,?)""", (actor,stamp))
    # Created only once, on the first successful join. Subsequent POSTs are idempotent.
    body = str(member["player_name"]) + " just Joined the Group-Chat !"
    cur = db.execute("""INSERT INTO chat_messages(thread_key,sender_key,body,created_at)
        VALUES('alliance','system',?,?)""", (body,stamp))
    db.execute("""INSERT INTO chat_reads(member_key,thread_key,last_read_id)
        VALUES(?,'alliance',?) ON CONFLICT(member_key,thread_key)
        DO UPDATE SET last_read_id=MAX(last_read_id,excluded.last_read_id)""",
        (actor,cur.lastrowid))
    return True


def group_details(db, actor, target):
    if not isinstance(target, str) or not target.startswith("group:"):
        return None
    suffix=target[6:]
    if not suffix.isdecimal() or len(suffix)>14:
        raise ValueError("Group not found.")
    group=db.execute("""SELECT g.id,g.name,g.creator_key
        FROM chat_groups g JOIN chat_group_members m ON g.id=m.group_id
        WHERE g.id=? AND m.member_key=?""",(int(suffix),actor)).fetchone()
    if group is None:
        raise ValueError("Group not found or you are not a member.")
    return group


def pending_group_invitation(db, actor, target):
    if not isinstance(target, str) or not target.startswith("group:"):
        return None
    suffix=target[6:]
    if not suffix.isdecimal() or len(suffix)>14:
        return None
    return db.execute("""SELECT i.group_id,i.invited_by,g.name
        FROM chat_group_invites i JOIN chat_groups g ON g.id=i.group_id
        WHERE i.group_id=? AND i.member_key=? AND i.joined_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM chat_group_members m
            WHERE m.group_id=i.group_id AND m.member_key=i.member_key
        )""",(int(suffix),actor)).fetchone()


def actor_name(db, actor):
    if actor == ADMIN:
        return "SaS Admin"
    member = approved_member(db,actor)
    return str(member["player_name"]) if member else "Former member"


def join_group(db, actor, target):
    if not valid_actor(db,actor):
        raise PermissionError("Approved account required.")
    if not isinstance(target,str) or not target.startswith("group:"):
        raise ValueError("Group not found.")
    invitation = pending_group_invitation(db,actor,target)
    if invitation is None:
        # Repeated presses are idempotent if the account already joined.
        if group_details(db,actor,target):
            return False
        raise ValueError("You have not been invited to this group.")
    stamp=now_utc()
    updated=db.execute("""UPDATE chat_group_invites SET joined_at=?
        WHERE group_id=? AND member_key=? AND joined_at IS NULL""",
        (stamp,invitation["group_id"],actor))
    if not updated.rowcount:
        return False
    db.execute("""INSERT OR IGNORE INTO chat_group_members(group_id,member_key)
        VALUES(?,?)""",(invitation["group_id"],actor))
    body=actor_name(db,actor)+" joined the Group !"
    cur=db.execute("""INSERT INTO chat_messages(thread_key,sender_key,body,created_at)
        VALUES(?,?,?,?)""",(target,"system",body,stamp))
    db.execute("""INSERT INTO chat_reads(member_key,thread_key,last_read_id)
        VALUES(?,?,?) ON CONFLICT(member_key,thread_key) DO UPDATE SET
        last_read_id=MAX(chat_reads.last_read_id,excluded.last_read_id)""",
        (actor,target,cur.lastrowid))
    return True


def create_group(db, actor, name, participants):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    if not isinstance(name, str) or not 3 <= len(name.strip()) <= 60:
        raise ValueError("Group name must be 3–60 characters.")
    name=name.strip()
    if not isinstance(participants, list) or len(participants)>24:
        raise ValueError("Select up to 24 other players.")
    if any(not isinstance(p,str) or not p for p in participants):
        raise ValueError("Invalid group player.")
    keys=set(participants)
    if len(keys)!=len(participants) or actor in keys or ALLIANCE in keys:
        raise ValueError("Select each other player once.")
    if any(not valid_actor(db, member) for member in keys):
        raise ValueError("Only approved accounts can join a group.")
    cur=db.execute("""INSERT INTO chat_groups(name,creator_key,created_at)
        VALUES(?,?,?)""",(name,actor,now_utc()))
    group_id=cur.lastrowid
    db.execute("INSERT INTO chat_group_members(group_id,member_key) VALUES(?,?)",
               (group_id,actor))
    for member in keys:
        db.execute("""INSERT INTO chat_group_invites(
            group_id,member_key,invited_by,invited_at) VALUES(?,?,?,?)""",
            (group_id,member,actor,now_utc()))
    return "group:"+str(group_id)


def thread_for(db, actor, target):
    """Validate each private target and derive a canonical two-person thread key."""
    if target == ALLIANCE:
        if not alliance_joined(db, actor):
            raise ValueError("Join SaS Group first.")
        return "alliance"
    if isinstance(target,str) and target.startswith("group:"):
        group_details(db,actor,target)
        return target
    if target == actor:
        return "notes:" + actor
    if target != ADMIN and approved_member(db, target) is None:
        raise ValueError("This player is not available.")
    pair = sorted((actor, target))
    return "dm:" + "|".join(pair)


def valid_actor(db, actor):
    return actor == ADMIN or approved_member(db, actor) is not None


def contact_list(db, actor):
    rows = db.execute("""SELECT id,username,player_name FROM members
        WHERE status='approved' ORDER BY username COLLATE NOCASE,id LIMIT 1000""").fetchall()
    joined = alliance_joined(db, actor)
    contacts = [{"id": ALLIANCE, "username": "SaS - Group Chat",
                 "player_name": "Everyone in the alliance", "group": True,
                 "pinned": True, "joined": joined,
                 "can_mention_everyone": actor == ADMIN}]
    for group in db.execute("""SELECT g.id,g.name,g.creator_key,COUNT(gm.member_key) AS participants
        FROM chat_groups g
        JOIN chat_group_members gm ON gm.group_id=g.id
        WHERE EXISTS(SELECT 1 FROM chat_group_members self
                     WHERE self.group_id=g.id AND self.member_key=?)
        GROUP BY g.id,g.name,g.creator_key ORDER BY g.id DESC""",(actor,)):
        contacts.append({"id": "group:"+str(group["id"]), "username": group["name"],
                         "player_name": str(group["participants"])+" participants",
                         "group": True, "pinned": False,
                         "can_mention_everyone": actor in (ADMIN,group["creator_key"])})
    for invitation in db.execute("""SELECT g.id,g.name,i.invited_by
        FROM chat_group_invites i JOIN chat_groups g ON g.id=i.group_id
        WHERE i.member_key=? AND i.joined_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM chat_group_members gm
            WHERE gm.group_id=i.group_id AND gm.member_key=i.member_key)
        ORDER BY g.id DESC""",(actor,)):
        sender=actor_name(db,invitation["invited_by"])
        contacts.append({"id": "group:"+str(invitation["id"]),
            "username":invitation["name"],
            "player_name":"Private group invitation",
            "group":True,"pinned":False,"joined":False,
            "invited_by":sender,"invitation":True})
    if actor != ADMIN:
        contacts.append({"id": ADMIN, "username": "SaS Admin", "player_name": "Administrator", "group": False})
        own = approved_member(db, actor)
        if own:
            contacts.append({**member_profile(own), "group": False, "self": True})
    for row in rows:
        profile = member_profile(row)
        if profile["id"] != actor:
            contacts.append({**profile, "group": False})
    return contacts


def summaries(db, actor):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    contacts = contact_list(db, actor)
    now = int(datetime.now(timezone.utc).timestamp())
    presence = {row["member_key"]: row["last_seen_at"]
                for row in db.execute("SELECT member_key,last_seen_at FROM chat_presence")}
    for contact in contacts:
        if not contact["group"] and not contact.get("self"):
            seen = presence.get(contact["id"])
            contact["online"] = bool(seen is not None and 0 <= now-seen <= PRESENCE_ONLINE_SECONDS)
            contact["last_seen_at"] = seen
    summaries_out = []
    for contact in contacts:
        target = contact["id"]
        if target == ALLIANCE and not contact["joined"]:
            summaries_out.append({**contact,"last_message":"","last_at":None,
                "last_id":0,"last_sender":None,"unread":0})
            continue
        if contact.get("invitation"):
            summaries_out.append({**contact,
                "last_message":contact["invited_by"]+" has invited you to join a Group",
                "last_at":None, "last_id":0, "last_sender":None,
                "unread":1})
            continue
        thread = thread_for(db, actor, target)
        latest = db.execute("""SELECT id,sender_key,body,created_at,kind,deleted_at
            FROM chat_messages WHERE thread_key=? ORDER BY id DESC LIMIT 1""",
            (thread,)).fetchone()
        seen = db.execute("""SELECT last_read_id FROM chat_reads
            WHERE member_key=? AND thread_key=?""", (actor, thread)).fetchone()
        last_id = seen["last_read_id"] if seen else 0
        unread = db.execute("""SELECT COUNT(*) AS total FROM chat_messages
            WHERE thread_key=? AND id>? AND sender_key!=?""",
            (thread, last_id, actor)).fetchone()["total"]
        mentions=rich.mention_unread(db,actor,thread,last_id) if contact["group"] else 0
        summaries_out.append({**contact,
            "last_message": ("Message deleted" if latest and latest["deleted_at"] else
                "Photo" if latest and latest["kind"]=="image" else
                "Poll: "+latest["body"][:80] if latest and latest["kind"]=="poll" else
                latest["body"][:100] if latest else ""),
            "last_at": latest["created_at"] if latest else None,
            "last_id": latest["id"] if latest else 0,
            "last_sender": latest["sender_key"] if latest else None,
            "mentions": mentions, "unread": unread})
    # Keep alliance group pinned; custom groups and direct messages follow by activity.
    group = summaries_out[:1]
    rest = sorted(summaries_out[1:], key=lambda r: (-r["last_id"], r["username"].casefold()))
    return group + rest


def history_page(db, actor, target, before=None):
    if not valid_actor(db, actor):
        raise PermissionError("Approved account required.")
    thread = thread_for(db, actor, target)
    if before is not None:
        if not isinstance(before,int) or before<=0:
            raise ValueError("Invalid message cursor.")
        rows = db.execute("""SELECT id,sender_key,body,created_at,reply_to_id,edited_at,deleted_at,kind FROM chat_messages
            WHERE thread_key=? AND id<? ORDER BY id DESC LIMIT ?""",
            (thread, before, MAX_HISTORY+1)).fetchall()
    else:
        rows = db.execute("""SELECT id,sender_key,body,created_at,reply_to_id,edited_at,deleted_at,kind FROM chat_messages
            WHERE thread_key=? ORDER BY id DESC LIMIT ?""",
            (thread, MAX_HISTORY+1)).fetchall()
    has_more=len(rows)>MAX_HISTORY
    messages=[dict(row) for row in reversed(rows[:MAX_HISTORY])]
    rich.message_details(db,actor,thread,messages)
    # The existing read cursor belongs to the *recipient*, not to the sender.
    # Reveal it only for the sender's own messages in a private 1:1 chat.
    # Self-notes, alliance chats and custom groups are intentionally excluded.
    if thread.startswith("dm:") and target != actor:
        read_row = db.execute("""SELECT last_read_id FROM chat_reads
            WHERE member_key=? AND thread_key=?""", (target, thread)).fetchone()
        recipient_read_id = read_row["last_read_id"] if read_row else 0
        for message in messages:
            if message["sender_key"] == actor:
                message["read"] = message["id"] <= recipient_read_id
    return messages, has_more


def history(db, actor, target):
    return history_page(db,actor,target)[0]


def send(db, actor, target, body, reply_to=None):
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
    reply_id=rich.validate_reply(db,thread,reply_to)
    created = now_utc()
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
    recent = db.execute("""SELECT COUNT(*) FROM chat_messages
        WHERE sender_key=? AND created_at>=?""", (actor, since)).fetchone()[0]
    if recent >= MAX_MESSAGES_PER_MINUTE:
        raise ValueError("Too many messages. Try again in a minute.")
    cur = db.execute("""INSERT INTO chat_messages(thread_key,sender_key,body,created_at,reply_to_id)
        VALUES(?,?,?,?,?)""", (thread,actor,message,created,reply_id))
    rich.sync_mentions(db,thread,actor,cur.lastrowid,message)
    return {"id": cur.lastrowid, "sender_key": actor, "body": message,
            "created_at": created, "reply_to_id": reply_id}


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
            rich.purge_messages(db,[row["id"] for row in db.execute(
                "SELECT id FROM chat_messages WHERE thread_key=?",(thread,))])
            db.execute("DELETE FROM chat_messages WHERE thread_key=?", (thread,))
            db.execute("DELETE FROM chat_reads WHERE thread_key=?", (thread,))
    # Alliance messages no longer belong to the deleted account, but remain as
    # historical posts with sender anonymized.
    db.execute("UPDATE chat_messages SET sender_key='deleted' WHERE sender_key=? AND thread_key='alliance'", (key,))
    # Remove group memberships and delete groups that become empty.
    ids=[row["group_id"] for row in db.execute(
        "SELECT group_id FROM chat_group_members WHERE member_key=?",(key,))]
    db.execute("DELETE FROM chat_group_invites WHERE member_key=?",(key,))
    db.execute("DELETE FROM chat_group_members WHERE member_key=?",(key,))
    for group_id in ids:
        if db.execute("SELECT 1 FROM chat_group_members WHERE group_id=?",
                      (group_id,)).fetchone() is None:
            group_key="group:"+str(group_id)
            rich.purge_messages(db,[row["id"] for row in db.execute(
                "SELECT id FROM chat_messages WHERE thread_key=?",(group_key,))])
            db.execute("DELETE FROM chat_messages WHERE thread_key=?",(group_key,))
            db.execute("DELETE FROM chat_reads WHERE thread_key=?",(group_key,))
            db.execute("DELETE FROM chat_group_invites WHERE group_id=?",(group_id,))
            db.execute("DELETE FROM chat_groups WHERE id=?",(group_id,))
    db.execute("UPDATE chat_groups SET creator_key='deleted' WHERE creator_key=?",(key,))
    db.execute("UPDATE chat_messages SET sender_key='deleted' WHERE sender_key=? AND thread_key LIKE 'group:%'",(key,))
    rich.purge_messages(db,[row["id"] for row in db.execute(
        "SELECT id FROM chat_messages WHERE thread_key=?",("notes:"+key,))])
    db.execute("DELETE FROM chat_messages WHERE thread_key=?", ("notes:"+key,))
    db.execute("DELETE FROM chat_reads WHERE thread_key=?", ("notes:"+key,))
    db.execute("DELETE FROM chat_alliance_members WHERE member_key=?", (key,))
    db.execute("DELETE FROM chat_reads WHERE member_key=?", (key,))
    # The removed account must leave no stored activity or poll-vote identity.
    db.execute("DELETE FROM chat_presence WHERE member_key=?", (key,))
    db.execute("DELETE FROM chat_typing WHERE member_key=?", (key,))
    db.execute("DELETE FROM chat_poll_votes WHERE member_key=?", (key,))
    db.execute("DELETE FROM chat_mentions WHERE member_key=?", (key,))
    # Historical group messages stay anonymized; attached images do not.
    photos=[row["id"] for row in db.execute("""SELECT id FROM chat_messages
        WHERE sender_key='deleted' AND kind='image' AND deleted_at IS NULL""")]
    rich.purge_messages(db,photos)
    for message_id in photos:
        db.execute("""UPDATE chat_messages SET body='',kind='deleted',deleted_at=?
            WHERE id=?""",(now_utc(),message_id))
