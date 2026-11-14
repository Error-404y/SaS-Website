"""Validated extensions for the SaS Messenger SQLite backend.

All operations re-check the authenticated actor and conversation membership.
These helpers never trust client-supplied sender identities or poll totals.
"""
import base64
import binascii
import io
import re
import time
from datetime import datetime, timezone

TYPING_SECONDS = 6
MAX_IMAGE_INPUT = 4 * 1024 * 1024
MAX_IMAGE_SAVED = 850 * 1024
MAX_POLL_OPTIONS = 6


def core():
    import messenger
    return messenger


def setup(db):
    fields = {row["name"] for row in db.execute("PRAGMA table_info(chat_messages)")}
    for name, definition in (
        ("reply_to_id", "INTEGER"),
        ("edited_at", "TEXT"),
        ("deleted_at", "TEXT"),
        ("kind", "TEXT NOT NULL DEFAULT 'text'"),
    ):
        if name not in fields:
            db.execute("ALTER TABLE chat_messages ADD COLUMN " + name + " " + definition)
    db.execute("""CREATE TABLE IF NOT EXISTS chat_typing (
        thread_key TEXT NOT NULL, member_key TEXT NOT NULL, expires_at INTEGER NOT NULL,
        PRIMARY KEY(thread_key,member_key))""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_images (
        message_id INTEGER PRIMARY KEY, image_data BLOB NOT NULL,
        content_type TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_polls (
        message_id INTEGER PRIMARY KEY, question TEXT NOT NULL, closed_at TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_poll_options (
        message_id INTEGER NOT NULL, position INTEGER NOT NULL, label TEXT NOT NULL,
        PRIMARY KEY(message_id,position))""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_poll_votes (
        message_id INTEGER NOT NULL, member_key TEXT NOT NULL, position INTEGER NOT NULL,
        PRIMARY KEY(message_id,member_key))""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_mentions (
        message_id INTEGER NOT NULL, member_key TEXT NOT NULL,
        PRIMARY KEY(message_id,member_key))""")
    db.execute("""CREATE INDEX IF NOT EXISTS chat_mentions_member
        ON chat_mentions(member_key,message_id)""")


def thread_for(db, actor, peer):
    if not core().valid_actor(db, actor):
        raise PermissionError("An approved account is required.")
    return core().thread_for(db, actor, peer)


def message_in_thread(db, actor, peer, message_id, own=False):
    thread = thread_for(db, actor, peer)
    if type(message_id) is not int or message_id < 1:
        raise ValueError("Invalid message.")
    row = db.execute("SELECT * FROM chat_messages WHERE id=? AND thread_key=?",
                     (message_id, thread)).fetchone()
    if row is None:
        raise ValueError("Message not found in this conversation.")
    if own and (row["sender_key"] != actor or actor == "system"):
        raise PermissionError("You can only modify your own messages.")
    return thread, row


def validate_reply(db, thread, reply_id):
    if reply_id is None:
        return None
    if type(reply_id) is not int or reply_id < 1:
        raise ValueError("Invalid reply.")
    row = db.execute("""SELECT deleted_at,sender_key FROM chat_messages
        WHERE id=? AND thread_key=?""", (reply_id, thread)).fetchone()
    if row is None or row["deleted_at"] or row["sender_key"] == "system":
        raise ValueError("Reply must refer to an available message in this conversation.")
    return reply_id


def mentionable(db, actor, peer):
    thread = thread_for(db, actor, peer)
    if thread == "alliance":
        rows = db.execute("""SELECT 'member:'||m.id AS id,m.username,m.player_name
          FROM members m JOIN chat_alliance_members a ON a.member_key='member:'||m.id
          WHERE m.status='approved' ORDER BY m.username LIMIT 1000""")
        return [dict(row) for row in rows]
    if thread.startswith("group:"):
        group_id = int(thread[6:])
        rows = db.execute("""SELECT 'member:'||m.id AS id,m.username,m.player_name
          FROM members m JOIN chat_group_members gm ON gm.member_key='member:'||m.id
          WHERE gm.group_id=? AND m.status='approved' ORDER BY m.username""",
          (group_id,))
        people = [dict(row) for row in rows]
        if db.execute("""SELECT 1 FROM chat_group_members
          WHERE group_id=? AND member_key='admin'""", (group_id,)).fetchone():
            people.append({"id":"admin","username":"SaS Admin","player_name":"Administrator"})
        return people
    return []


def sync_mentions(db, thread, actor, message_id, body):
    db.execute("DELETE FROM chat_mentions WHERE message_id=?", (message_id,))
    if thread != "alliance" and not thread.startswith("group:"):
        return
    names = set(word.casefold() for word in re.findall(
        r"(?<![\w@])@([A-Za-z0-9_.-]{2,32})", body))
    if not names:
        return
    if len(names) > 25:
        raise ValueError("Mention at most 25 names per message.")
    members = mentionable(db, actor, thread)
    by_name = {member["username"].casefold(): member["id"] for member in members}
    targets = {by_name[name] for name in names if name in by_name}
    if "everyone" in names:
        creator = None
        if thread.startswith("group:"):
            row = db.execute("SELECT creator_key FROM chat_groups WHERE id=?",
                             (int(thread[6:]),)).fetchone()
            creator = row["creator_key"] if row else None
        if actor != "admin" and creator != actor:
            raise ValueError("Only administrators and group creators can mention @everyone.")
        targets.update(member["id"] for member in members)
    targets.discard(actor)
    for member in targets:
        db.execute("INSERT OR IGNORE INTO chat_mentions(message_id,member_key) VALUES(?,?)",
                   (message_id, member))


def mention_unread(db, actor, thread, after_id):
    return db.execute("""SELECT COUNT(*) FROM chat_mentions cm
      JOIN chat_messages m ON m.id=cm.message_id
      WHERE m.thread_key=? AND m.id>? AND cm.member_key=? AND m.deleted_at IS NULL""",
      (thread, after_id, actor)).fetchone()[0]


def message_details(db, actor, thread, messages):
    # Only messages from the already-authorized conversation are considered.
    reply_ids = {m.get("reply_to_id") for m in messages if m.get("reply_to_id")}
    replies = {}
    if reply_ids:
        query = ",".join("?" for _ in reply_ids)
        for row in db.execute("""SELECT id,sender_key,body,kind,deleted_at
           FROM chat_messages WHERE thread_key=? AND id IN (""" + query + ")",
           (thread, *reply_ids)):
            replies[row["id"]] = dict(row)
    for item in messages:
        if item.get("deleted_at"):
            item["kind"] = "deleted"
            item["body"] = ""
        reply = replies.get(item.get("reply_to_id"))
        if reply:
            label = ("Message deleted" if reply["deleted_at"] else
                     "Photo" if reply["kind"]=="image" else
                     "Poll" if reply["kind"]=="poll" else reply["body"][:110])
            item["reply"] = {"id":reply["id"],"sender_key":reply["sender_key"],
                             "body":label}
        if item.get("kind") == "poll":
            item["poll"] = poll_details(db,actor,item["id"])
        if thread == "alliance" or thread.startswith("group:"):
            item["mentioned_me"] = bool(db.execute("""SELECT 1 FROM chat_mentions
               WHERE message_id=? AND member_key=?""", (item["id"],actor)).fetchone())
    return messages


def edit_message(db, actor, peer, message_id, body):
    thread, message = message_in_thread(db, actor, peer, message_id, own=True)
    if message["deleted_at"] or message["kind"] != "text":
        raise ValueError("Only existing text messages can be edited.")
    if not isinstance(body,str) or not body.strip() or len(body.strip()) > core().MAX_MESSAGE:
        raise ValueError("Enter a message up to 2000 characters.")
    clean=body.strip()
    if any(ord(ch)<32 and ch not in "\n\t" for ch in clean):
        raise ValueError("Invalid message characters.")
    # Compute mentions before editing, inside the same transaction.
    sync_mentions(db,thread,actor,message_id,clean)
    db.execute("""UPDATE chat_messages SET body=?,edited_at=? WHERE id=?""",
               (clean,core().now_utc(),message_id))
    return {"ok":True}


def delete_message(db, actor, peer, message_id):
    thread, message = message_in_thread(db,actor,peer,message_id,own=True)
    if message["deleted_at"]:
        return {"ok":True}
    db.execute("""UPDATE chat_messages SET body='',deleted_at=?,edited_at=NULL
      WHERE id=?""", (core().now_utc(),message_id))
    db.execute("DELETE FROM chat_mentions WHERE message_id=?",(message_id,))
    if message["kind"] == "image":
        db.execute("DELETE FROM chat_images WHERE message_id=?",(message_id,))
    if message["kind"] == "poll":
        for table in ("chat_polls","chat_poll_options","chat_poll_votes"):
            db.execute("DELETE FROM "+table+" WHERE message_id=?",(message_id,))
    return {"ok":True}


def set_typing(db,actor,peer,active=True):
    thread=thread_for(db,actor,peer)
    if thread.startswith("notes:"):
        return
    if active:
        db.execute("""INSERT INTO chat_typing(thread_key,member_key,expires_at)
         VALUES(?,?,?) ON CONFLICT(thread_key,member_key)
         DO UPDATE SET expires_at=excluded.expires_at""",
         (thread,actor,int(time.time())+TYPING_SECONDS))
    else:
        db.execute("DELETE FROM chat_typing WHERE thread_key=? AND member_key=?",
                   (thread,actor))
    db.execute("DELETE FROM chat_typing WHERE expires_at<?",(int(time.time())-30,))


def typing_names(db,actor,peer):
    thread=thread_for(db,actor,peer)
    if thread.startswith("notes:"):
        return []
    rows=db.execute("""SELECT member_key FROM chat_typing
       WHERE thread_key=? AND member_key!=? AND expires_at>?
       ORDER BY expires_at DESC LIMIT 3""",
       (thread,actor,int(time.time()))).fetchall()
    return [core().actor_name(db,row["member_key"]) for row in rows]


def create_poll(db,actor,peer,question,options,reply_id=None):
    thread=thread_for(db,actor,peer)
    if thread!="alliance" and not thread.startswith("group:"):
        raise ValueError("Polls are available in groups only.")
    if not isinstance(question,str) or not 3<=len(question.strip())<=180:
        raise ValueError("Poll question must be 3–180 characters.")
    if not isinstance(options,list) or not 2<=len(options)<=MAX_POLL_OPTIONS or any(
        not isinstance(value,str) or not 1<=len(value.strip())<=80 for value in options):
        raise ValueError("Provide 2–6 poll options (80 characters max each).")
    labels=[value.strip() for value in options]
    if len(set(value.casefold() for value in labels))!=len(labels):
        raise ValueError("Poll options must be different.")
    # Use the standard send path so all sender rate limits remain effective.
    msg=core().send(db,actor,peer,question.strip(),reply_id)
    mid=msg["id"]
    db.execute("UPDATE chat_messages SET kind='poll' WHERE id=?",(mid,))
    db.execute("INSERT INTO chat_polls(message_id,question) VALUES(?,?)",(mid,question.strip()))
    for position,label in enumerate(labels):
        db.execute("""INSERT INTO chat_poll_options(message_id,position,label)
           VALUES(?,?,?)""", (mid,position,label))
    return msg


def poll_details(db,actor,message_id):
    poll=db.execute("SELECT question,closed_at FROM chat_polls WHERE message_id=?",
                    (message_id,)).fetchone()
    if poll is None:
        return None
    votes={row["position"]:row["total"] for row in db.execute("""SELECT position,
      COUNT(*) AS total FROM chat_poll_votes WHERE message_id=? GROUP BY position""",
      (message_id,))}
    mine=db.execute("SELECT position FROM chat_poll_votes WHERE message_id=? AND member_key=?",
                    (message_id,actor)).fetchone()
    options=[{"position":row["position"],"label":row["label"],
              "votes":votes.get(row["position"],0)} for row in db.execute(
              "SELECT position,label FROM chat_poll_options WHERE message_id=? ORDER BY position",
              (message_id,))]
    return {"question":poll["question"],"options":options,
            "total_votes":sum(votes.values()),
            "my_vote":mine["position"] if mine else None,
            "closed":bool(poll["closed_at"])}


def vote_poll(db,actor,peer,message_id,position):
    thread,msg=message_in_thread(db,actor,peer,message_id)
    if thread!="alliance" and not thread.startswith("group:"):
        raise ValueError("Polls are available in groups only.")
    if msg["kind"]!="poll" or msg["deleted_at"]:
        raise ValueError("Poll unavailable.")
    if type(position) is not int or position<0:
        raise ValueError("Invalid poll choice.")
    poll=db.execute("SELECT closed_at FROM chat_polls WHERE message_id=?",(message_id,)).fetchone()
    if not poll or poll["closed_at"]:
        raise ValueError("Poll is closed.")
    if not db.execute("SELECT 1 FROM chat_poll_options WHERE message_id=? AND position=?",
                      (message_id,position)).fetchone():
        raise ValueError("Invalid option.")
    db.execute("""INSERT INTO chat_poll_votes(message_id,member_key,position)
       VALUES(?,?,?) ON CONFLICT(message_id,member_key)
       DO UPDATE SET position=excluded.position""",(message_id,actor,position))
    return poll_details(db,actor,message_id)


def close_poll(db,actor,peer,message_id):
    _,msg=message_in_thread(db,actor,peer,message_id,own=True)
    if msg["kind"]!="poll" or msg["deleted_at"]:
        raise ValueError("Poll unavailable.")
    db.execute("UPDATE chat_polls SET closed_at=COALESCE(closed_at,?) WHERE message_id=?",
               (core().now_utc(),message_id))
    return {"ok":True}


def encode_image(encoded):
    if not isinstance(encoded,str) or len(encoded)>MAX_IMAGE_INPUT*4//3+100:
        raise ValueError("Image is too large (4 MB maximum).")
    try:
        data=base64.b64decode(encoded,validate=True)
    except (binascii.Error,ValueError) as exc:
        raise ValueError("Invalid image data.") from exc
    if len(data)>MAX_IMAGE_INPUT:
        raise ValueError("Image is too large (4 MB maximum).")
    from PIL import Image,UnidentifiedImageError
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG","JPEG","WEBP") or im.width*im.height>12000000:
                raise ValueError("Use a PNG, JPEG or WebP image up to 12 megapixels.")
            im.load()
            rgb=im.convert("RGB")
            rgb.thumbnail((1600,1600))
            out=io.BytesIO()
            rgb.save(out,format="WEBP",quality=78,method=4)
            data=out.getvalue()
            if len(data)>MAX_IMAGE_SAVED:
                raise ValueError("Image is too complex; choose a smaller one.")
            return data,rgb.width,rgb.height
    except (UnidentifiedImageError,OSError,Image.DecompressionBombError) as exc:
        raise ValueError("Invalid image.") from exc


def send_image(db,actor,peer,encoded,caption="",reply_id=None):
    if not isinstance(caption,str) or len(caption)>350:
        raise ValueError("Caption must be 350 characters or less.")
    data,width,height=encode_image(encoded)
    msg=core().send(db,actor,peer,caption.strip() or "Photo",reply_id)
    db.execute("UPDATE chat_messages SET kind='image' WHERE id=?",(msg["id"],))
    db.execute("""INSERT INTO chat_images(message_id,image_data,content_type,width,height)
      VALUES(?,?,?,?,?)""",(msg["id"],data,"image/webp",width,height))
    return msg


def read_image(db,actor,peer,message_id):
    _,msg=message_in_thread(db,actor,peer,message_id)
    if msg["kind"]!="image" or msg["deleted_at"]:
        raise ValueError("Image unavailable.")
    row=db.execute("SELECT image_data,content_type FROM chat_images WHERE message_id=?",
                   (message_id,)).fetchone()
    if row is None:
        raise ValueError("Image unavailable.")
    return bytes(row["image_data"]),row["content_type"]


def purge_messages(db,ids):
    ids=list(ids)
    if not ids:
        return
    for id_batch in (ids[i:i+300] for i in range(0,len(ids),300)):
        clause=",".join("?" for _ in id_batch)
        for table in ("chat_images","chat_polls","chat_poll_options","chat_poll_votes","chat_mentions"):
            db.execute("DELETE FROM "+table+" WHERE message_id IN ("+clause+")",id_batch)
