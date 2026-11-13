"""Member registration, approval and persistent authentication for SaS."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.cookies import SimpleCookie

def setup(db):
    db.execute("""CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL COLLATE NOCASE UNIQUE,
        player_name TEXT NOT NULL,
        email TEXT NOT NULL COLLATE NOCASE UNIQUE,
        password_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        review_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        reviewed_at TEXT NOT NULL DEFAULT ''
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS member_sessions (
        token_hash TEXT PRIMARY KEY,
        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
        csrf TEXT NOT NULL,
        expires_at INTEGER NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS member_sessions_owner ON member_sessions(member_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS member_reads (
        member_id INTEGER PRIMARY KEY REFERENCES members(id) ON DELETE CASCADE,
        seen_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT ''
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS password_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id),
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','approved','rejected','completed')),
        created_at INTEGER NOT NULL,
        reviewed_at INTEGER,
        review_message TEXT NOT NULL DEFAULT '',
        code_hash TEXT,
        code_expires_at INTEGER
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS password_requests_member ON password_requests(member_id, created_at)")

def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ':' + digest.hex()

def check_password(password, stored):
    try:
        salt_hex, digest_hex = stored.split(':', 1)
        digest = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt_hex), n=16384, r=8, p=1)
        return hmac.compare_digest(digest, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False

def register(db, values):
    username = str(values.get('username', '')).strip()
    player_name = str(values.get('player_name', '')).strip()
    email = str(values.get('email', '')).strip().lower()
    password = values.get('password', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username):
        raise ValueError('Username must be 3–32 characters (letters, numbers, _ . -).')
    if not 2 <= len(player_name) <= 60:
        raise ValueError('Enter your in-game player name (2–60 characters).')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254:
        raise ValueError('Enter a valid email address.')
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError('Password must be at least 12 characters.')
    try:
        db.execute("""INSERT INTO members(username,player_name,email,password_hash,status,created_at)
            VALUES(?,?,?,?,'pending',?)""",
            (username, player_name, email, password_hash(password), datetime.now(timezone.utc).isoformat()))
    except sqlite3.IntegrityError as exc:
        raise ValueError('Username or email is already registered.') from exc

def member_session(handler, connect, lock):
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get('Cookie', ''))
        item = cookie.get('sas_member')
        if not item:
            return None
        digest = hashlib.sha256(item.value.encode()).hexdigest()
    except Exception:
        return None
    with lock, connect() as db:
        row = db.execute("""SELECT s.token_hash,s.csrf,m.id,m.username,m.player_name,m.status,m.review_message
            FROM member_sessions s JOIN members m ON m.id=s.member_id
            WHERE s.token_hash=? AND s.expires_at>?""", (digest, int(time.time()))).fetchone()
    return dict(row) if row else None

def new_session(db, member_id):
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.execute("DELETE FROM member_sessions WHERE expires_at<?", (int(time.time()),))
    db.execute("INSERT INTO member_sessions(token_hash,member_id,csrf,expires_at) VALUES(?,?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), member_id, csrf, int(time.time()) + 30 * 86400))
    return token, csrf

def public_member(row):
    return {key: row[key] for key in ('id', 'username', 'player_name', 'email', 'status',
                                      'review_message', 'created_at', 'reviewed_at')}

def request_password_reset(db, identifier):
    """Issue a generic response for known/unknown users. Limit one request per 15 min."""
    if not isinstance(identifier, str) or not 1 <= len(identifier.strip()) <= 254:
        raise ValueError("Enter your account username or email.")
    identifier = identifier.strip()
    row = db.execute("SELECT id FROM members WHERE username=? OR email=?",
                     (identifier, identifier)).fetchone()
    if row:
        now = int(time.time())
        recent = db.execute("""SELECT id FROM password_requests
            WHERE member_id=? AND created_at>? ORDER BY id DESC LIMIT 1""",
            (row["id"], now - 900)).fetchone()
        if not recent:
            db.execute("""UPDATE password_requests SET status='rejected',
                review_message='Superseded by a new request',reviewed_at=?,code_hash=NULL,code_expires_at=NULL
                WHERE member_id=? AND status IN ('pending','approved')""",
                (now, row["id"]))
            db.execute("INSERT INTO password_requests(member_id,status,created_at) VALUES(?,'pending',?)",
                       (row["id"], now))
    return {"message": "If the account exists, a password change request has been submitted for administrator review."}

def list_password_requests(db):
    return [dict(row) for row in db.execute("""SELECT p.id,p.member_id,p.status,p.created_at,
        p.reviewed_at,p.review_message,p.code_expires_at,m.username,m.player_name,m.email
        FROM password_requests p JOIN members m ON m.id=p.member_id
        ORDER BY CASE p.status WHEN 'pending' THEN 0 ELSE 1 END,p.created_at DESC LIMIT 300""")]

def review_password_request(db, request_id, decision, message=""):
    if decision not in ("approved", "rejected"):
        raise ValueError("Invalid review decision.")
    if decision == "rejected" and (not isinstance(message, str) or not 3 <= len(message.strip()) <= 500):
        raise ValueError("A rejection reason (3–500 characters) is required.")
    row = db.execute("SELECT * FROM password_requests WHERE id=?", (request_id,)).fetchone()
    if not row:
        raise LookupError("Password request not found.")
    if row["status"] != "pending":
        raise ValueError("This request has already been reviewed.")
    now = int(time.time())
    code = secrets.token_urlsafe(32) if decision == "approved" else None
    db.execute("""UPDATE password_requests SET status=?,reviewed_at=?,review_message=?,
        code_hash=?,code_expires_at=? WHERE id=? AND status='pending'""",
        (decision, now, message.strip() if decision == "rejected" else "",
         hashlib.sha256(code.encode()).hexdigest() if code else None,
         now + 3600 if code else None, request_id))
    return code

def complete_password_reset(db, username, code, new_password):
    if not isinstance(username, str) or not isinstance(code, str) or not isinstance(new_password, str):
        raise ValueError("Invalid password reset.")
    if not 12 <= len(new_password) <= 128:
        raise ValueError("Password must be at least 12 characters.")
    if len(code) > 256:
        raise ValueError("Invalid or expired reset code.")
    row = db.execute("""SELECT p.id,p.member_id,p.code_hash,p.code_expires_at
        FROM password_requests p JOIN members m ON p.member_id=m.id
        WHERE m.username=? AND p.status='approved' ORDER BY p.id DESC LIMIT 1""",
        (username.strip(),)).fetchone()
    if not row or not row["code_hash"] or not row["code_expires_at"] or row["code_expires_at"] < int(time.time()) or not hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(),row["code_hash"]):
        raise ValueError("Invalid or expired reset code.")
    db.execute("UPDATE members SET password_hash=? WHERE id=?",
               (password_hash(new_password), row["member_id"]))
    db.execute("""UPDATE password_requests SET status='completed',code_hash=NULL,
        code_expires_at=NULL WHERE id=?""", (row["id"],))
    db.execute("DELETE FROM member_sessions WHERE member_id=?", (row["member_id"],))
    return {"message": "Password changed. You can now sign in."}
