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
