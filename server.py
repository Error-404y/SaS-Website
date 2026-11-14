import hmac
import hashlib
import members
import messenger
import messenger_features as rich
import ban_system
import reminder_cards
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent

def load_local_env():
    path = ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        key, setting = value.split("=", 1)
        key = key.strip()
        if key != "Const-Web" and not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        os.environ.setdefault(key, setting.strip().strip('"').strip("'"))

load_local_env()
DB = Path(os.environ.get("SAS_DB_PATH", str(ROOT / "data" / "website.sqlite3")))
HOST = os.environ.get("SAS_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or "8080")
ADMIN_USER = os.environ.get("SAS_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("SAS_ADMIN_PASSWORD", "")
COOKIE_SECURE = os.environ.get("SAS_COOKIE_SECURE", "1") != "0"
MAINTENANCE_MODE = os.environ.get("Const-Web", "false").strip().lower() in ("true", "1", "yes", "on")
WEBHOOK = os.environ.get("SAS_DISCORD_WEBHOOK_URL", "")
REGISTRATION_WEBHOOK = os.environ.get("SAS_DISCORD_REGISTRATION_WEBHOOK_URL", "")
LOGIN_WEBHOOK = os.environ.get("SAS_DISCORD_LOGIN_WEBHOOK_URL", "")
ADMIN_IDLE_SECONDS = 30 * 60
LOCK = threading.RLock()
NOTICE_STATUS = {kind: {"configured": bool(url), "last_result": "not attempted",
    "last_attempt": None} for kind, url in (
    ("registration", REGISTRATION_WEBHOOK), ("login", LOGIN_WEBHOOK), ("reminder", WEBHOOK))}
KINDS = ("events", "alliance", "updates", "announcements")
CATEGORIES = ("Events", "Deals", "Alliance", "Port Inspection", "Other")
RSS_RESOURCES = ("ammo", "cash", "electricity", "gas")
RSS_BUFFS = ("troop_attack", "troop_defense", "troop_hp", "resource_gathering")
SEED_EVENTS = [
    ("Chief Almighty", "Events", "2026-11-09 00:00:00", "2026-11-14 23:59:59"),
    ("Precinct Powerplay", "Events", "2026-11-09 00:00:00", "2026-11-15 23:59:59"),
    ("Heroes Unite", "Deals", "2026-11-09 00:00:00", "2026-11-22 23:59:59"),
    ("Oilfield Strike", "Events", "2026-11-10 00:00:00", "2026-11-10 23:59:59"),
    ("Mafia Attack", "Events", "2026-11-10 00:00:00", "2026-11-13 12:00:00"),
    ("Lucky Wheel", "Events", "2026-11-10 00:00:00", "2026-11-12 23:59:59"),
    ("Prison Clash", "Events", "2026-11-10 00:00:00", "2026-11-13 23:59:59"),
    ("Bros. in Arms", "Events", "2026-11-13 00:00:00", "2026-11-14 23:59:59")
]

def connect():
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=20000")
    return db

def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with LOCK, connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            start_utc TEXT NOT NULL DEFAULT '',
            end_utc TEXT NOT NULL DEFAULT '',
            rewards TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL DEFAULT '',
            reminded_at INTEGER,
            reminder_claimed_at INTEGER
        )""")
        if "modified_at" not in {row["name"] for row in db.execute("PRAGMA table_info(entries)")}:
            db.execute("ALTER TABLE entries ADD COLUMN modified_at TEXT NOT NULL DEFAULT ''")
        for field in ("points", "scoring"):
            if field not in {row["name"] for row in db.execute("PRAGMA table_info(entries)")}:
                db.execute("ALTER TABLE entries ADD COLUMN "+field+" TEXT NOT NULL DEFAULT ''")
        db.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS rss_spending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource TEXT NOT NULL,
            amount REAL NOT NULL,
            spent_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS rss_spending_order ON rss_spending(spent_at,id)""")
        db.execute("""CREATE TABLE IF NOT EXISTS reminder_messages (
            event_id INTEGER NOT NULL,
            stage TEXT NOT NULL CHECK(stage IN ('yellow','red')),
            event_start_utc TEXT NOT NULL,
            message_id TEXT NOT NULL DEFAULT '',
            sent_at INTEGER NOT NULL DEFAULT 0,
            attempt_at INTEGER NOT NULL DEFAULT 0,
            deleted_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(event_id,stage,event_start_utc)
        )""")
        db.execute("""CREATE INDEX IF NOT EXISTS reminder_messages_cleanup
            ON reminder_messages(deleted_at,sent_at)""")
        db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            csrf TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            last_activity_at INTEGER NOT NULL DEFAULT 0
        )""")
        if "last_activity_at" not in [row["name"] for row in db.execute("PRAGMA table_info(sessions)")]:
            db.execute("ALTER TABLE sessions ADD COLUMN last_activity_at INTEGER NOT NULL DEFAULT 0")
        # Previously issued sessions lack a trustworthy human-activity timestamp.
        # Re-authentication is required to establish a new 30-minute idle window.
        db.execute("DELETE FROM sessions WHERE last_activity_at=0")
        members.setup(db)
        messenger.setup(db)
        ban_system.setup(db)
        db.execute("""CREATE TABLE IF NOT EXISTS auth_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            source TEXT NOT NULL,
            happened_at INTEGER NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS auth_failures_recent ON auth_failures(category,source,happened_at)")
        db.execute("""CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        first = db.execute("SELECT value FROM meta WHERE key='seeded'").fetchone()
        if not first:
            now = datetime.now(timezone.utc).isoformat()
            for title, category, start, end in SEED_EVENTS:
                db.execute("""INSERT INTO entries(kind,title,category,start_utc,end_utc,created_at)
                    VALUES('events',?,?,?,?,?)""", (title, category, start, end, now))
            db.execute("INSERT INTO meta(key,value) VALUES('seeded','1')")
        for key in ("rss_hour", "tech_plan", "rss_resources", "rss_buffs",
                    "rss_tech_name", "rss_tech_progress", "rss_tech_stage", "rss_tech_ends_at",
                    "rss_territory_plan", "rss_updated_at", "rss_base_at", "rss_base_spend_id"):
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?, '')", (key,))

def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def parse_utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", value):
        raise ValueError("Use YYYY-MM-DD HH:MM:SS in UTC.")
    try:
        date = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError("Enter a valid UTC date and time.") from exc
    return int(date.replace(tzinfo=timezone.utc).timestamp())

def clean(value, limit, required=False):
    if not isinstance(value, str):
        raise ValueError("Invalid text value.")
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError("A required field is empty or too long.")
    return value

def validate_entry(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid form.")
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValueError("Invalid section.")
    title = clean(data.get("title", ""), 120, True)
    details = clean(data.get("details", ""), 5000)
    rewards = clean(data.get("rewards", ""), 1600)
    points = clean(data.get("points", ""), 1400)
    scoring = clean(data.get("scoring", ""), 3500)
    category = clean(data.get("category", ""), 60)
    author = clean(data.get("author", ""), 80)
    start = clean(data.get("start_utc", ""), 19)
    end = clean(data.get("end_utc", ""), 19)
    if kind in ("events", "alliance"):
        if not start or not end or parse_utc(end) <= parse_utc(start):
            raise ValueError("End must be after start.")
        if kind == "events" and category not in CATEGORIES:
            raise ValueError("Choose a valid category.")
        if kind == "alliance":
            category = "Alliance"
    else:
        start = ""
        end = ""
        category = ""
        rewards = ""
        points = ""
        scoring = ""
        if kind == "announcements" and author not in ("R4", "R5"):
            raise ValueError("Choose R4 or R5.")
        if kind == "updates":
            author = ""
    return kind, title, category, start, end, rewards, details, points, scoring, author

def optional_rss_number(value, field, maximum=1000000000000000):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(field + " must be a non-negative number.")
    if isinstance(value, str) and not re.fullmatch(r"\d+(?:\.\d{1,2})?", value.strip()):
        raise ValueError(field + " must be a non-negative number with up to two decimals.")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(field + " must be a valid number.") from exc
    if not math.isfinite(number) or number < 0 or number > maximum or round(number, 2) != number:
        raise ValueError(field + " is outside the allowed range.")
    return int(number) if number.is_integer() else number

def parse_research_duration(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,3}:[0-5]\d:[0-5]\d", value):
        raise ValueError("Enter time remaining as HH:MM:SS, for example 01:45:00.")
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return hours * 3600 + minutes * 60 + seconds

def research_deadline(value, current=None):
    seconds = parse_research_duration(value)
    if seconds is None:
        return ""
    current = current or datetime.now(timezone.utc)
    return (current + timedelta(seconds=seconds)).isoformat(timespec="seconds")

def validate_rss(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid form.")
    resources = data.get("resources")
    buffs = data.get("buffs")
    if not isinstance(resources, dict) or set(resources) != set(RSS_RESOURCES):
        raise ValueError("Please enter all four resource types.")
    if not isinstance(buffs, dict) or set(buffs) != set(RSS_BUFFS):
        raise ValueError("Invalid territory buffs.")
    normalized_resources = {}
    for key in RSS_RESOURCES:
        item = resources[key]
        if not isinstance(item, dict):
            raise ValueError("Invalid resource details.")
        limit = optional_rss_number(item.get("limit", 1200000), key + " storage limit")
        limit = 1200000 if limit is None else limit
        if limit <= 0:
            raise ValueError(key + " storage limit must be greater than zero.")
        stored = optional_rss_number(item.get("stored"), key + " stored resources")
        if stored is not None and stored > limit:
            raise ValueError(key + " balance cannot exceed its storage limit.")
        normalized_resources[key] = {
            "stored": stored,
            "per_hour": optional_rss_number(item.get("per_hour"), key + " per hour"),
            "limit": limit
        }
    normalized_buffs = {
        key: optional_rss_number(buffs[key], key.replace("_", " ") + " buff", 1000)
        for key in RSS_BUFFS
    }
    tech_progress = optional_rss_number(data.get("tech_progress"), "Technology progress", 100)
    remaining = data.get("tech_remaining")
    if "tech_remaining" in data:
        parse_research_duration(remaining)
    return {
        "resources": normalized_resources,
        "buffs": normalized_buffs,
        "tech_name": clean(data.get("tech_name", ""), 120),
        "tech_plan": clean(data.get("tech_plan", ""), 2500),
        "tech_progress": tech_progress,
        "tech_stage": clean(data.get("tech_stage", ""), 120),
        "tech_remaining": remaining,
        "territory_plan": clean(data.get("territory_plan", ""), 1200)
    }

def rss_state(settings, spending=(), current=None):
    def object_value(key):
        try:
            value = json.loads(settings.get(key) or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

    current = current or datetime.now(timezone.utc)
    anchor = settings.get("rss_base_at") or settings.get("rss_updated_at") or current.isoformat(timespec="seconds")
    try:
        anchor_seconds = datetime.fromisoformat(anchor).timestamp()
    except (ValueError, TypeError):
        anchor_seconds = current.timestamp()
    try:
        included_through_id = int(settings.get("rss_base_spend_id") or 0)
    except (ValueError, TypeError):
        included_through_id = 0
    saved_resources = object_value("rss_resources")
    saved_buffs = object_value("rss_buffs")
    resources = {}
    buffs = {}
    for key in RSS_RESOURCES:
        item = saved_resources.get(key, {})
        if not isinstance(item, dict):
            item = {}
        resources[key] = {}
        for field in ("stored", "per_hour"):
            try:
                resources[key][field] = optional_rss_number(item.get(field), key + " " + field)
            except ValueError:
                resources[key][field] = None
        try:
            limit = optional_rss_number(item.get("limit", 1200000), key + " limit")
            resources[key]["limit"] = limit if limit is not None and limit > 0 else 1200000
        except ValueError:
            resources[key]["limit"] = 1200000
    calculated = {}
    for key, item in resources.items():
        balance = item["stored"]
        if balance is None:
            calculated[key] = None
            continue
        limit = item["limit"]
        balance = min(balance, limit)
        previous = anchor_seconds
        rate = item["per_hour"] or 0
        for spend in sorted(spending, key=lambda row: (row["spent_at"], row["id"])):
            if spend["resource"] != key or spend["id"] <= included_through_id:
                continue
            spent_at = parse_utc(spend["spent_at"])
            if spent_at < anchor_seconds or spent_at > current.timestamp():
                continue
            balance = min(limit, balance + rate * max(0, spent_at - previous) / 3600)
            balance -= spend["amount"]
            if balance < -0.011:
                raise ValueError("Recorded spending exceeds available " + key + ".")
            balance = max(0, balance)
            previous = spent_at
        calculated[key] = round(min(limit, balance + rate * max(0, current.timestamp() - previous) / 3600), 2)
    for key in RSS_RESOURCES:
        resources[key]["current"] = calculated[key]
    for key in RSS_BUFFS:
        try:
            buffs[key] = optional_rss_number(saved_buffs.get(key), key, 1000)
        except ValueError:
            buffs[key] = None
    try:
        progress = optional_rss_number(settings.get("rss_tech_progress"), "Technology progress", 100)
    except ValueError:
        progress = None
    return {
        "resources": resources,
        "buffs": buffs,
        "tech_name": settings.get("rss_tech_name", ""),
        "tech_plan": settings.get("tech_plan", ""),
        "tech_progress": progress,
        "tech_stage": settings.get("rss_tech_stage", ""),
        "tech_ends_at": settings.get("rss_tech_ends_at", ""),
        "territory_plan": settings.get("rss_territory_plan", ""),
        "updated_at": settings.get("rss_updated_at", ""),
        "legacy_hour": settings.get("rss_hour", ""),
        "base_at": anchor,
        "as_of": current.isoformat(timespec="seconds"),
        "spending": [
            {**dict(item), "included": item["id"] > included_through_id and parse_utc(item["spent_at"]) >= anchor_seconds}
            for item in sorted(spending, key=lambda row: (row["spent_at"], row["id"]), reverse=True)[:100]
        ]
    }

def current_session(handler):
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
    except Exception:
        return None
    value = cookie.get("sas_session")
    if not value:
        return None
    token_hash = __import__("hashlib").sha256(value.value.encode()).hexdigest()
    now = int(time.time())
    with LOCK, connect() as db:
        row = db.execute("""SELECT * FROM sessions WHERE token_hash=? AND expires_at>?
            AND last_activity_at>?""", (token_hash, now, now - ADMIN_IDLE_SECONDS)).fetchone()
        if not row:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    return dict(row) if row else None


def login_throttled(category, source, limit=10):
    cutoff = int(time.time()) - 900
    with LOCK, connect() as db:
        db.execute("DELETE FROM auth_failures WHERE happened_at<?", (cutoff,))
        count = db.execute("SELECT COUNT(*) FROM auth_failures WHERE category=? AND source=? AND happened_at>=?",
                           (category, source, cutoff)).fetchone()[0]
    return count >= limit

def note_login_failure(category, source):
    with LOCK, connect() as db:
        db.execute("INSERT INTO auth_failures(category,source,happened_at) VALUES(?,?,?)",
                   (category, source, int(time.time())))

def clear_login_failures(category, source):
    with LOCK, connect() as db:
        db.execute("DELETE FROM auth_failures WHERE category=? AND source=?", (category, source))

READ_KINDS = ("events", "alliance", "rss", "updates", "announcements")

def member_read_snapshot(db):
    snapshot = {kind: {} for kind in READ_KINDS if kind != "rss"}
    snapshot["rss"] = ""
    for row in db.execute("""SELECT id,kind,modified_at,created_at FROM entries
        WHERE kind IN ('events','alliance','updates','announcements')"""):
        snapshot[row["kind"]][str(row["id"])] = row["modified_at"] or row["created_at"] or str(row["id"])
    rss_row = db.execute("SELECT value FROM settings WHERE key='rss_updated_at'").fetchone()
    snapshot["rss"] = rss_row["value"] if rss_row else ""
    return snapshot

def member_read_state(db, member_id):
    row = db.execute("SELECT seen_json FROM member_reads WHERE member_id=?", (member_id,)).fetchone()
    if not row:
        return {kind: {} if kind != "rss" else "" for kind in READ_KINDS}
    try:
        seen = json.loads(row["seen_json"])
        if isinstance(seen, dict):
            return {kind: seen.get(kind, {} if kind != "rss" else "") for kind in READ_KINDS}
    except (ValueError, TypeError):
        pass
    return {kind: {} if kind != "rss" else "" for kind in READ_KINDS}

def get_state():
    with LOCK, connect() as db:
        rows = db.execute("""SELECT id,kind,title,category,start_utc,end_utc,rewards,details,author,points,scoring,created_at,modified_at
            FROM entries ORDER BY CASE WHEN kind IN ('events','alliance') THEN start_utc ELSE created_at END DESC, id DESC""").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM settings").fetchall()}
        spent = [dict(row) for row in db.execute("SELECT * FROM rss_spending ORDER BY spent_at,id").fetchall()]
    current = datetime.now(timezone.utc)
    return {"entries": [dict(row) for row in rows], "settings": settings,
            "rss": rss_state(settings, spent, current), "utc": current.isoformat(timespec="seconds")}

def webhook_valid(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in ("discord.com", "discordapp.com") and not parts.username
        and not parts.password and parts.port in (None, 443) and not parts.query and not parts.fragment
        and re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9_-]+", parts.path) is not None)

def discord_send(kind, url, payload):
    """Deliver a Discord webhook safely, reporting only status without exposing its secret."""
    with LOCK:
        NOTICE_STATUS[kind]["last_attempt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if not url or not webhook_valid(url):
        state = "not configured" if not url else "invalid URL"
        with LOCK:
            NOTICE_STATUS[kind]["last_result"] = state
        return False
    try:
        request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "SaS-Website/1.0"},
            method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            code = response.status
        success = 200 <= code < 300
        with LOCK:
            NOTICE_STATUS[kind]["last_result"] = "delivered" if success else "HTTP " + str(code)
        if not success:
            logging.warning("Discord %s webhook: HTTP %s", kind, code)
        return success
    except urllib.error.HTTPError as exc:
        # Do not log exception strings or the webhook URL, which contains a secret.
        with LOCK:
            NOTICE_STATUS[kind]["last_result"] = "HTTP " + str(exc.code)
        logging.warning("Discord %s webhook: HTTP %s", kind, exc.code)
    except Exception as exc:
        state = type(exc).__name__
        with LOCK:
            NOTICE_STATUS[kind]["last_result"] = "network error (" + state + ")"
        logging.warning("Discord %s webhook failed: %s", kind, state)
    return False

def discord_account_notice(category, role, username, email="", player_name=""):
    """Best-effort minimal audit event. Webhook tokens are read only from private environment."""
    url = REGISTRATION_WEBHOOK if category == "registration" else LOGIN_WEBHOOK if category == "login" else ""
    if not url:
        return
    if not webhook_valid(url):
        logging.warning("Account notification webhook is invalid or not configured safely.")
        return
    title = "New member registration" if category == "registration" else "Website login"
    fields = [
        {"name": "Role", "value": role, "inline": True},
        {"name": "Username", "value": str(username)[:64] or "Unknown", "inline": True}
    ]
    if email:
        fields.append({"name": "Email", "value": str(email)[:254], "inline": False})
    if player_name and category == "registration":
        fields.append({"name": "In-game name", "value": str(player_name)[:70], "inline": False})
    if category == "login":
        fields.append({"name": "Login (UTC)", "value": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), "inline": False})
    payload = {"username": "SaS Account Notifications", "allowed_mentions": {"parse": []},
               "embeds": [{"title": title, "color": 5916792, "fields": fields}]}
    threading.Thread(target=discord_send, args=(category, url, payload),
        name="sas-discord-account-notice", daemon=True).start()

REMINDER_STAGES = (
    ("yellow", 7200, 6600), # 2h before start; allow a 10-minute delivery window
    ("red", 3600, 3000),    # 1h before start; allow a 10-minute delivery window
)

def reminder_stage_due(start_epoch, now_epoch, stage):
    for kind, upper, lower in REMINDER_STAGES:
        if kind == stage:
            remaining = start_epoch - now_epoch
            return lower <= remaining <= upper
    return False

def reminder_expiry(stage, sent_at):
    # Yellow disappears 50 minutes after its actual send. Red disappears after 24h.
    return sent_at + (50 * 60 if stage == "yellow" else 24 * 3600)

def reminder_cleanup_once(now_epoch=None):
    """Delete outdated cards, with the Discord ID persisted for restart recovery."""
    if not WEBHOOK or not webhook_valid(WEBHOOK):
        return
    now_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
    with LOCK, connect() as db:
        rows = db.execute("""SELECT r.*,
            e.start_utc AS current_start
            FROM reminder_messages r LEFT JOIN entries e ON r.event_id=e.id
            WHERE r.message_id != '' AND r.deleted_at=0 AND r.attempt_at<?
            ORDER BY r.sent_at LIMIT 35""", (now_epoch - 60,)).fetchall()
    for row in rows:
        # Edits and removals must not leave stale reminders visible.
        stale = row["current_start"] is None or row["current_start"] != row["event_start_utc"]
        if not stale and now_epoch < reminder_expiry(row["stage"], row["sent_at"]):
            continue
        with LOCK, connect() as db:
            db.execute("""UPDATE reminder_messages SET attempt_at=?
                WHERE event_id=? AND stage=? AND event_start_utc=?""",
                (now_epoch, row["event_id"], row["stage"], row["event_start_utc"]))
        try:
            if reminder_cards.delete_card(WEBHOOK, row["message_id"]):
                with LOCK, connect() as db:
                    db.execute("""UPDATE reminder_messages SET deleted_at=?
                        WHERE event_id=? AND stage=? AND event_start_utc=? AND message_id=?""",
                        (now_epoch, row["event_id"], row["stage"], row["event_start_utc"], row["message_id"]))
        except Exception as exc:
            logging.warning("Discord reminder cleanup failed: %s", type(exc).__name__)

def reminder_send_once(now_epoch=None):
    """Publish at most one due card, never duplicate an already acknowledged stage."""
    if not WEBHOOK or not webhook_valid(WEBHOOK):
        return False
    now_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
    with LOCK, connect() as db:
        events = db.execute("""SELECT id,kind,title,start_utc,reminded_at
            FROM entries WHERE kind IN ('events','alliance')
            AND start_utc>? AND start_utc<=?
            ORDER BY start_utc,id LIMIT 100""", (
                datetime.fromtimestamp(now_epoch + 3000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.fromtimestamp(now_epoch + 7200, timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )).fetchall()
        candidates=[]
        for event in events:
            try:
                start = parse_utc(event["start_utc"])
            except ValueError:
                continue
            for stage, upper, lower in REMINDER_STAGES:
                if not reminder_stage_due(start, now_epoch, stage):
                    continue
                # Pre-migration 1h reminders had no stored message id.
                if stage == "red" and event["reminded_at"] is not None:
                    continue
                rec = db.execute("""SELECT message_id,attempt_at FROM reminder_messages
                    WHERE event_id=? AND stage=? AND event_start_utc=?""",
                    (event["id"], stage, event["start_utc"])).fetchone()
                if rec and (rec["message_id"] or rec["attempt_at"] > now_epoch - 90):
                    continue
                candidates.append((event,stage))
        if not candidates:
            return False
        event,stage=candidates[0]
        db.execute("""INSERT INTO reminder_messages(event_id,stage,event_start_utc,attempt_at)
            VALUES(?,?,?,?)
            ON CONFLICT(event_id,stage,event_start_utc)
            DO UPDATE SET attempt_at=excluded.attempt_at""",
            (event["id"],stage,event["start_utc"],now_epoch))
    # POST outside the database lock: slow Discord responses must not block logins.
    try:
        msg_id = reminder_cards.send_card(WEBHOOK, event["title"], event["start_utc"], stage)
        with LOCK, connect() as db:
            db.execute("""UPDATE reminder_messages SET message_id=?,sent_at=?
                WHERE event_id=? AND stage=? AND event_start_utc=?""",
                (msg_id,now_epoch,event["id"],stage,event["start_utc"]))
            if stage == "red":
                db.execute("""UPDATE entries SET reminded_at=?
                    WHERE id=? AND start_utc=?""",(now_epoch,event["id"],event["start_utc"]))
        with LOCK:
            NOTICE_STATUS["reminder"]["last_attempt"] = now_utc()
            NOTICE_STATUS["reminder"]["last_result"] = "delivered"
        return True
    except Exception as exc:
        # Never log the webhook secret or sensitive HTTP exception text.
        with LOCK:
            NOTICE_STATUS["reminder"]["last_attempt"] = now_utc()
            NOTICE_STATUS["reminder"]["last_result"] = "failed (" + type(exc).__name__ + ")"
        logging.warning("Discord %s reminder delivery failed (%s)", stage, type(exc).__name__)
        return False

def reminder_loop():
    if not WEBHOOK:
        return
    if not webhook_valid(WEBHOOK):
        logging.error("Discord reminder webhook URL is invalid.")
        return
    logging.info("Discord image reminders enabled: 2h yellow, 1h red.")
    while True:
        try:
            reminder_cleanup_once()
            if not reminder_send_once():
                time.sleep(25)
        except Exception:
            logging.exception("Reminder scheduler error")
            time.sleep(30)

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init()
    for kind, url in (("reminder", WEBHOOK), ("registration", REGISTRATION_WEBHOOK), ("login", LOGIN_WEBHOOK)):
        logging.info("Discord %s webhook: %s", kind,
            "ready" if url and webhook_valid(url) else "invalid URL" if url else "NOT CONFIGURED")
    if WEBHOOK:
        threading.Thread(target=reminder_loop, daemon=True).start()
    logging.info("SaS Website listening on %s:%s", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()

class Handler(BaseHTTPRequestHandler):
    server_version = "SaSWebsite"
    def respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def asset(self, filename, mime, private=False):
        path = ROOT / filename
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.respond(404, {"error": "Not found."})
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "private, no-store" if private else "public, max-age=300")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
        if private:
            self.send_header("Vary", "Cookie")
        self.end_headers()
        self.wfile.write(data)

    def session_cookie(self, name, token, payload):
        result = json.dumps(payload).encode()
        secure = "; Secure" if COOKIE_SECURE else ""
        self.send_response(200)
        self.send_header("Set-Cookie", f"{name}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={30 * 86400 if name == 'sas_member' else 43200}{secure}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def maintenance_response(self, path):
        """Maintenance disables the application, authentication and all API routes."""
        if path == "/":
            try:
                body = (ROOT / "maintenance.html").read_bytes()
            except OSError:
                return self.respond(503, {"error": "Website is under maintenance."})
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Retry-After", "3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
            return
        return self.respond(503, {"error": "Website is under maintenance."})

    def messenger_actor(self):
        admin = current_session(self)
        if admin:
            return messenger.ADMIN, admin["csrf"]
        player = members.member_session(self, connect, LOCK)
        if player and player["status"] == "approved":
            return messenger.member_key(player["id"]), player["csrf"]
        return None, None

    def banned_client(self):
        # The HTTP peer address is used, never an untrusted X-Forwarded-For.
        if current_session(self):
            return False  # Admins must retain an emergency unban path.
        player = members.member_session(self, connect, LOCK)
        with LOCK, connect() as db:
            kwargs = {"ip": self.client_address[0]}
            if player:
                row = db.execute("SELECT username,player_name,email FROM members WHERE id=?",
                                 (player["id"],)).fetchone()
                if row:
                    kwargs.update({key: row[key] for key in ("username","player_name","email")})
            return ban_system.is_banned(db, **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if MAINTENANCE_MODE:
            return self.maintenance_response(path)
        if self.banned_client():
            if path == "/api/session":
                return self.respond(200, {"admin": False, "approved": False, "csrf": None,
                    "username": None, "status": "restricted", "review_message": "",
                    "admin_idle_timeout_seconds": None})
            if path == "/":
                # Keep the sign-in page available so administrators on shared IPs
                # can recover and lift a ban, but never serve the member app.
                return self.asset("login.html", "text/html; charset=utf-8", private=True)
            if path not in ("/auth.js", "/styles.css", "/assets/logo.webp", "/assets/crest.avif"):
                return self.respond(403, {"error": "Access restricted."})
        image_match = re.fullmatch(r"/api/messenger/images/(\d+)", path)
        if image_match:
            actor, csrf = self.messenger_actor()
            if actor is None:
                return self.respond(401, {"error": "An approved account is required."})
            from urllib.parse import parse_qs
            peer = parse_qs(urlsplit(self.path).query).get("peer", [""])[0]
            try:
                with LOCK, connect() as db:
                    data, content_type = rich.read_image(db,actor,peer,int(image_match.group(1)))
            except (ValueError,PermissionError):
                return self.respond(404, {"error": "Image unavailable."})
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(data)
            return
        if path in ("/api/messenger", "/api/messenger/messages",
                    "/api/messenger/mentionables"):
            actor, csrf = self.messenger_actor()
            if actor is None:
                return self.respond(401, {"error": "An approved account is required."})
            if path == "/api/messenger/mentionables":
                from urllib.parse import parse_qs
                peer = parse_qs(urlsplit(self.path).query).get("peer", [""])[0]
                with LOCK, connect() as db:
                    try:
                        choices = rich.mentionable(db, actor, peer)
                    except (ValueError,PermissionError):
                        return self.respond(404, {"error": "Conversation unavailable."})
                return self.respond(200, {"members": choices})
            if path == "/api/messenger":
                with LOCK, connect() as db:
                    contacts = messenger.summaries(db, actor)
                return self.respond(200, {"me": actor, "contacts": contacts,
                    "unread": sum(contact["unread"] for contact in contacts)})
            from urllib.parse import parse_qs
            query = parse_qs(urlsplit(self.path).query)
            peer = query.get("peer", [""])[0]
            cursor = query.get("before", [""])[0]
            if cursor and (not cursor.isdecimal() or len(cursor)>20):
                return self.respond(400, {"error": "Invalid message cursor."})
            with LOCK, connect() as db:
                try:
                    messages, has_more = messenger.history_page(
                        db, actor, peer, int(cursor) if cursor else None)
                    typing_names = rich.typing_names(db, actor, peer)
                except (ValueError,PermissionError) as exc:
                    return self.respond(404, {"error": str(exc)})
            return self.respond(200, {"me": actor, "peer": peer, "messages": messages,
                                      "has_more": has_more, "typing": typing_names})
        if path == "/api/reads":
            player = members.member_session(self, connect, LOCK)
            if not player or player["status"] != "approved":
                return self.respond(401, {"error": "An approved player account is required."})
            with LOCK, connect() as db:
                seen = member_read_state(db, player["id"])
            return self.respond(200, {"seen": seen})
        if path == "/api/state":
            player = members.member_session(self, connect, LOCK)
            if not current_session(self) and not (player and player["status"] == "approved"):
                return self.respond(401, {"error": "An approved account is required."})
            return self.respond(200, get_state())
        if path == "/api/notifications/status":
            if not current_session(self):
                return self.respond(403, {"error": "Administrator access required."})
            with LOCK:
                status = {key: dict(value) for key, value in NOTICE_STATUS.items()}
            return self.respond(200, {"channels": status})
        if path == "/api/bans":
            if not current_session(self):
                return self.respond(403, {"error": "Administrator access required."})
            with LOCK, connect() as db:
                bans = ban_system.list_bans(db)
            return self.respond(200, {"bans": bans, "delay_seconds": ban_system.WAIT_SECONDS})
        if path == "/api/accounts":
            if not current_session(self):
                return self.respond(403, {"error": "Administrator access required."})
            with LOCK, connect() as db:
                accounts = [members.public_member(row) for row in db.execute(
                    "SELECT * FROM members ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, created_at DESC")]
            with LOCK, connect() as db:
                resets = members.list_password_requests(db)
            with LOCK, connect() as db:
                for account in accounts:
                    account["last_ip"] = ban_system.member_ip(db, account["id"])
            return self.respond(200, {"accounts": accounts, "password_requests": resets})
        if path == "/api/session":
            session = current_session(self)
            player = members.member_session(self, connect, LOCK)
            return self.respond(200, {"admin": bool(session), "approved": bool(player and player["status"] == "approved"),
                "username": player["username"] if player else (ADMIN_USER if session else None),
                "status": player["status"] if player else None,
                "review_message": player["review_message"] if player else "",
                "csrf": session["csrf"] if session else (player["csrf"] if player else None),
                "admin_idle_timeout_seconds": ADMIN_IDLE_SECONDS if session else None})
        if path in ("/", "/index.html", "/app"):
            player = members.member_session(self, connect, LOCK)
            permitted = bool(current_session(self)) or bool(player and player["status"] == "approved")
            if permitted:
                return self.asset("index.html", "text/html; charset=utf-8", private=True)
            if path == "/":
                return self.asset("login.html", "text/html; charset=utf-8", private=True)
            return self.respond(401, {"error": "An approved account is required."})
        assets = {"/auth.js": ("auth.js", "text/javascript; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/calendar.js": ("calendar.js", "text/javascript; charset=utf-8"),
                  "/rss.js": ("rss.js", "text/javascript; charset=utf-8"),
                  "/unread.js": ("unread.js", "text/javascript; charset=utf-8"),
                  "/planner.js": ("planner.js", "text/javascript; charset=utf-8"),
                  "/planner-ui.js": ("planner-ui.js", "text/javascript; charset=utf-8"),
                  "/messenger-ui.js": ("messenger-ui.js", "text/javascript; charset=utf-8"),
                  "/reference-data.js": ("reference-data.js", "text/javascript; charset=utf-8"),
                  "/reference-ui.js": ("reference-ui.js", "text/javascript; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                  "/assets/logo.webp": ("assets/logo.webp", "image/webp"),
                  "/assets/crest.avif": ("assets/crest.avif", "image/avif")}
        if path in assets:
            return self.asset(*assets[path])
        return self.respond(404, {"error": "Not found."})

    def read_json(self, max_bytes=16000):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid content length.")
        if size < 1 or size > max_bytes:
            raise ValueError("Invalid request size.")
        try:
            value = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError("Invalid form.")
        return value

    def valid_request_origin(self):
        # Cross-origin requests must never be allowed to use authenticated browser cookies.
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            host = self.headers.get("Host", "").lower()
            return (parsed.scheme in ("http", "https") and parsed.netloc.lower() == host
                    and (parsed.scheme == "https" or not COOKIE_SECURE)
                    and not parsed.username and not parsed.password)
        return True

    def authorized(self):
        session = current_session(self)
        if not session or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
            self.respond(403, {"error": "Administrator access required."})
            return False
        return True

    def write(self, method):
        path = urlsplit(self.path).path
        if MAINTENANCE_MODE:
            return self.respond(503, {"error": "Website is under maintenance."})
        try:
            if not self.valid_request_origin():
                return self.respond(403, {"error": "Cross-origin request rejected."})
            if path != "/api/login" and self.banned_client():
                return self.respond(403, {"error": "Access restricted."})
            if path == "/api/bans/cancel-pending" and method == "POST":
                if not self.authorized():
                    return
                now = int(time.time())
                with LOCK, connect() as db:
                    cursor = db.execute("""UPDATE moderation_bans SET cancelled_at=?
                        WHERE cancelled_at IS NULL AND revoked_at IS NULL AND effective_at>?""",
                        (now, now))
                return self.respond(200, {"ok": True, "cancelled": cursor.rowcount})
            if path == "/api/bans" and method == "POST":
                if not self.authorized():
                    return
                data = self.read_json()
                member_id = data.get("member_id")
                if isinstance(member_id, bool) or not isinstance(member_id, int) or member_id<1:
                    raise ValueError("Select an account.")
                with LOCK, connect() as db:
                    try:
                        ban_id = ban_system.queue(db, member_id, data.get("kind"), data.get("reason", ""))
                    except LookupError:
                        return self.respond(404, {"error": "Account not found."})
                return self.respond(201, {"id": ban_id, "delay_seconds": ban_system.WAIT_SECONDS})
            ban_match = re.fullmatch(r"/api/bans/(\d+)", path)
            if ban_match and method == "DELETE":
                if not self.authorized():
                    return
                with LOCK, connect() as db:
                    try:
                        cancelled = ban_system.stop(db, int(ban_match.group(1)))
                    except LookupError:
                        return self.respond(404, {"error": "Ban not found."})
                return self.respond(200, {"ok": True, "undone": cancelled})
            if path == "/api/messenger/presence" and method == "POST":
                actor, csrf = self.messenger_actor()
                if actor is None:
                    return self.respond(401, {"error": "An approved account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                with LOCK, connect() as db:
                    messenger.heartbeat(db, actor)
                return self.respond(200, {"ok": True})
            if path == "/api/messenger/alliance/join" and method == "POST":
                actor, csrf = self.messenger_actor()
                if actor is None:
                    return self.respond(401, {"error": "An approved account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                with LOCK, connect() as db:
                    joined = messenger.join_alliance(db, actor)
                return self.respond(200, {"joined": joined, "member": True})
            if path == "/api/messenger/groups/join" and method == "POST":
                actor, csrf = self.messenger_actor()
                if actor is None:
                    return self.respond(401, {"error": "An approved account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                data = self.read_json()
                with LOCK, connect() as db:
                    joined = messenger.join_group(db, actor, data.get("peer"))
                return self.respond(200, {"joined": joined})
            if path == "/api/messenger/groups" and method == "POST":
                actor, csrf = self.messenger_actor()
                if actor is None:
                    return self.respond(401, {"error": "An approved account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                data = self.read_json()
                with LOCK, connect() as db:
                    group_id = messenger.create_group(db, actor, data.get("name"),
                        data.get("members"))
                return self.respond(201, {"id": group_id})
            if path in ("/api/messenger/typing", "/api/messenger/messages/edit",
                        "/api/messenger/messages/delete", "/api/messenger/polls",
                        "/api/messenger/polls/vote", "/api/messenger/polls/close",
                        "/api/messenger/images") and method == "POST":
                actor, csrf = self.messenger_actor()
                if actor is None:
                    return self.respond(401, {"error": "An approved account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                data = self.read_json(max_bytes=6000000 if path == "/api/messenger/images" else 16000)
                peer = data.get("peer", "")
                with LOCK, connect() as db:
                    if path == "/api/messenger/typing":
                        rich.set_typing(db,actor,peer,data.get("active") is True)
                        return self.respond(200, {"ok": True})
                    if path == "/api/messenger/messages/edit":
                        return self.respond(200, rich.edit_message(db,actor,peer,
                            data.get("id"),data.get("body")))
                    if path == "/api/messenger/messages/delete":
                        return self.respond(200, rich.delete_message(db,actor,peer,data.get("id")))
                    if path == "/api/messenger/polls":
                        return self.respond(201, {"message":rich.create_poll(db,actor,peer,
                            data.get("question"),data.get("options"),data.get("reply_to"))})
                    if path == "/api/messenger/polls/vote":
                        return self.respond(200, {"poll":rich.vote_poll(db,actor,peer,
                            data.get("id"),data.get("position"))})
                    if path == "/api/messenger/polls/close":
                        return self.respond(200, rich.close_poll(db,actor,peer,data.get("id")))
                    if path == "/api/messenger/images":
                        return self.respond(201, {"message":rich.send_image(db,actor,peer,
                            data.get("image"),data.get("caption",""),data.get("reply_to"))})
            if path in ("/api/messenger/messages", "/api/messenger/read") and method == "POST":
                actor, csrf = self.messenger_actor()
                if actor is None:
                    return self.respond(401, {"error": "An approved account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                values = self.read_json()
                peer = values.get("peer", "")
                with LOCK, connect() as db:
                    if path == "/api/messenger/messages":
                        message = messenger.send(db, actor, peer, values.get("body"),
                            values.get("reply_to"))
                        return self.respond(201, {"message": message})
                    last_read_id = messenger.mark_read(db, actor, peer)
                return self.respond(200, {"ok": True, "last_read_id": last_read_id})
            if path == "/api/notifications/test" and method == "POST":
                if not self.authorized():
                    return
                values = self.read_json()
                channel = values.get("channel")
                urls = {"registration": REGISTRATION_WEBHOOK,
                    "login": LOGIN_WEBHOOK, "reminder": WEBHOOK}
                if channel not in urls:
                    return self.respond(400, {"error": "Choose registration, login or reminder."})
                notice = {"username": "SaS Notifications", "allowed_mentions": {"parse": []},
                    "embeds": [{"title": "SaS notification test",
                        "description": "Test message for " + channel + " notifications."}]}
                delivered = discord_send(channel, urls[channel], notice)
                return self.respond(200 if delivered else 502,
                    {"ok": delivered, "channel": channel,
                     "result": NOTICE_STATUS[channel]["last_result"],
                     "error": None if delivered else "Discord delivery failed: " + NOTICE_STATUS[channel]["last_result"]})
            if path == "/api/admin/activity" and method == "POST":
                if not self.authorized():
                    return
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                digest = hashlib.sha256(cookie["sas_session"].value.encode()).hexdigest()
                now = int(time.time())
                with LOCK, connect() as db:
                    updated = db.execute("""UPDATE sessions SET last_activity_at=?
                        WHERE token_hash=? AND expires_at>? AND last_activity_at>?""",
                        (now, digest, now, now - ADMIN_IDLE_SECONDS))
                if not updated.rowcount:
                    return self.respond(403, {"error": "Administrator session expired."})
                return self.respond(200, {"ok": True, "idle_timeout_seconds": ADMIN_IDLE_SECONDS})
            if path == "/api/reads" and method == "POST":
                player = members.member_session(self, connect, LOCK)
                if not player or player["status"] != "approved":
                    return self.respond(401, {"error": "An approved player account is required."})
                if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), player["csrf"]):
                    return self.respond(403, {"error": "Invalid CSRF token."})
                data = self.read_json()
                kind = data.get("kind")
                if kind not in READ_KINDS:
                    return self.respond(400, {"error": "Unknown section."})
                with LOCK, connect() as db:
                    seen = member_read_state(db, player["id"])
                    current = member_read_snapshot(db)
                    seen[kind] = current[kind]
                    db.execute("""INSERT INTO member_reads(member_id,seen_json,updated_at)
                        VALUES(?,?,?) ON CONFLICT(member_id) DO UPDATE
                        SET seen_json=excluded.seen_json,updated_at=excluded.updated_at""",
                        (player["id"], json.dumps(seen, separators=(",", ":")),
                         datetime.now(timezone.utc).isoformat()))
                return self.respond(200, {"seen": seen})
            if path == "/api/password/request" and method == "POST":
                source = self.client_address[0]
                if login_throttled("password-request", source, limit=25):
                    return self.respond(429, {"error": "Too many password requests. Try later."})
                data = self.read_json()
                with LOCK, connect() as db:
                    result = members.request_password_reset(db, data.get("identifier"))
                note_login_failure("password-request", source)
                return self.respond(200, result)
            if path == "/api/password/complete" and method == "POST":
                data = self.read_json()
                with LOCK, connect() as db:
                    result = members.complete_password_reset(db, data.get("username"),
                        data.get("code"), data.get("new_password"))
                return self.respond(200, result)
            reset_review_match = re.fullmatch(r"/api/password/requests/(\d+)", path)
            if reset_review_match and method == "PATCH":
                if not self.authorized():
                    return
                data = self.read_json()
                with LOCK, connect() as db:
                    try:
                        code = members.review_password_request(db, int(reset_review_match.group(1)),
                            data.get("decision"), data.get("message", ""))
                    except LookupError:
                        return self.respond(404, {"error": "Password request not found."})
                return self.respond(200, {"ok": True, "reset_code": code,
                    "message": "Share the reset code privately with the player. It expires in one hour and is shown only once." if code else "Request rejected."})
            if path == "/api/register" and method == "POST":
                source = self.client_address[0]
                if login_throttled("registration", source, limit=25):
                    return self.respond(429, {"error": "Too many registrations. Try later."})
                values = self.read_json()
                with LOCK, connect() as db:
                    if ban_system.is_banned(db, ip=source, email=values.get("email", ""),
                            username=values.get("username", ""), player_name=values.get("player_name", "")):
                        return self.respond(403, {"error": "Registration restricted."})
                    members.register(db, values)
                    row = db.execute("SELECT id FROM members WHERE username=?", (values["username"],)).fetchone()
                    if row: ban_system.record_ip(db, row["id"], self.client_address[0])
                note_login_failure("registration", source)
                discord_account_notice("registration", "MEMBER", values.get("username", ""),
                    values.get("email", ""), values.get("player_name", ""))
                return self.respond(201, {"status": "pending", "message": "Registration submitted for administrator review."})
            if path == "/api/member/login" and method == "POST":
                data = self.read_json()
                username = str(data.get("username", "")).strip()
                # Include the login identifier to avoid locking out unrelated players
                # when they share a reverse proxy IP.
                source = self.client_address[0] + ":" + hashlib.sha256(username.casefold().encode()).hexdigest()[:20]
                if login_throttled("member", source):
                    return self.respond(429, {"error": "Too many login attempts. Try again later."})
                password = data.get("password", "")
                with LOCK, connect() as db:
                    row = db.execute("SELECT * FROM members WHERE username=? OR email=?", (username, username)).fetchone()
                    if not row or not isinstance(password, str) or not members.check_password(password, row["password_hash"]):
                        note_login_failure("member", source)
                        time.sleep(0.5)
                        return self.respond(401, {"error": "Invalid username or password."})
                    if ban_system.is_banned(db, ip=self.client_address[0], email=row["email"],
                            username=row["username"], player_name=row["player_name"]):
                        return self.respond(403, {"error": "Access restricted."})
                    if row["status"] != "approved":
                        return self.respond(403, {"error": "Your account is awaiting approval." if row["status"] == "pending" else
                            "Your application was declined: " + (row["review_message"] or "Contact an administrator.")})
                    token, csrf = members.new_session(db, row["id"])
                    ban_system.record_ip(db, row["id"], self.client_address[0])
                clear_login_failures("member", source)
                self.session_cookie("sas_member", token, {"approved": True, "admin": False, "csrf": csrf, "username": row["username"]})
                discord_account_notice("login", "MEMBER", row["username"], row["email"])
                return
            if path == "/api/member/logout" and method == "POST":
                player = members.member_session(self, connect, LOCK)
                if not player or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), player["csrf"]):
                    return self.respond(403, {"error": "Invalid session."})
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                item = cookie.get("sas_member")
                if item:
                    with LOCK, connect() as db:
                        db.execute("DELETE FROM member_sessions WHERE token_hash=?", (hashlib.sha256(item.value.encode()).hexdigest(),))
                self.send_response(200)
                self.send_header("Set-Cookie", "sas_member=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            account_match = re.fullmatch(r"/api/accounts/(\d+)", path)
            if account_match and method == "DELETE":
                if not self.authorized():
                    return
                member_id = int(account_match.group(1))
                with LOCK, connect() as db:
                    target = db.execute("SELECT id FROM members WHERE id=?", (member_id,)).fetchone()
                    if not target:
                        return self.respond(404, {"error": "Account not found."})
                    # Explicitly remove all dependent records for databases with older
                    # foreign-key definitions. The account is permanently deleted.
                    db.execute("DELETE FROM password_requests WHERE member_id=?", (member_id,))
                    db.execute("DELETE FROM member_reads WHERE member_id=?", (member_id,))
                    db.execute("DELETE FROM member_sessions WHERE member_id=?", (member_id,))
                    messenger.purge_member(db, member_id)
                    db.execute("DELETE FROM member_ips WHERE member_id=?", (member_id,))
                    db.execute("DELETE FROM members WHERE id=?", (member_id,))
                return self.respond(200, {"ok": True})
            if account_match and method == "PUT":
                if not self.authorized():
                    return
                data = self.read_json()
                username = str(data.get("username", "")).strip()
                player_name = str(data.get("player_name", "")).strip()
                email = str(data.get("email", "")).strip().lower()
                if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
                    raise ValueError("Username must be 3–32 characters.")
                if not 2 <= len(player_name) <= 60:
                    raise ValueError("In-game name must be 2–60 characters.")
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
                    raise ValueError("Enter a valid email.")
                with LOCK, connect() as db:
                    try:
                        cursor = db.execute("UPDATE members SET username=?,player_name=?,email=? WHERE id=?",
                            (username, player_name, email, int(account_match.group(1))))
                    except sqlite3.IntegrityError as exc:
                        raise ValueError("Username or email is already registered.") from exc
                    if not cursor.rowcount:
                        return self.respond(404, {"error": "Account not found."})
                return self.respond(200, {"ok": True})
            if account_match and method == "PATCH":
                if not self.authorized():
                    return
                data = self.read_json()
                status = data.get("status")
                message = clean(data.get("message", ""), 500)
                if status not in ("approved", "rejected", "pending"):
                    raise ValueError("Invalid account status.")
                if status == "rejected" and not message:
                    raise ValueError("A rejection reason is required.")
                if status != "rejected":
                    message = ""
                with LOCK, connect() as db:
                    cursor = db.execute("UPDATE members SET status=?,review_message=?,reviewed_at=? WHERE id=?",
                        (status, message, now_utc(), int(account_match.group(1))))
                    if not cursor.rowcount:
                        return self.respond(404, {"error": "Account not found."})
                    if status != "approved":
                        db.execute("DELETE FROM member_sessions WHERE member_id=?", (int(account_match.group(1)),))
                return self.respond(200, {"ok": True})
            if path == "/api/login" and method == "POST":
                source = self.client_address[0]
                if login_throttled("admin", source):
                    return self.respond(429, {"error": "Too many login attempts. Try again later."})
                data = self.read_json()
                if not ADMIN_PASSWORD or not hmac.compare_digest(str(data.get("username", "")), ADMIN_USER) or not hmac.compare_digest(str(data.get("password", "")), ADMIN_PASSWORD):
                    note_login_failure("admin", source)
                    time.sleep(0.5)
                    return self.respond(401, {"error": "Incorrect credentials or administrator login is not configured."})
                token = secrets.token_urlsafe(32)
                csrf = secrets.token_urlsafe(24)
                digest = __import__("hashlib").sha256(token.encode()).hexdigest()
                with LOCK, connect() as db:
                    db.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
                    stamp = int(time.time())
                    db.execute("""INSERT INTO sessions(token_hash,csrf,expires_at,last_activity_at)
                        VALUES(?,?,?,?)""", (digest, csrf, stamp + 43200, stamp))
                clear_login_failures("admin", source)
                self.session_cookie("sas_session", token, {"admin": True, "csrf": csrf, "idle_timeout_seconds": ADMIN_IDLE_SECONDS})
                discord_account_notice("login", "ADMIN", ADMIN_USER)
                return
            if not self.authorized():
                return
            if path == "/api/logout" and method == "POST":
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                if "sas_session" in cookie:
                    digest = __import__("hashlib").sha256(cookie["sas_session"].value.encode()).hexdigest()
                    with LOCK, connect() as db:
                        db.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
                self.send_response(200)
                self.send_header("Set-Cookie", "sas_session=; Path=/; HttpOnly; Max-Age=0; SameSite=Lax")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            if path == "/api/entries" and method == "POST":
                values = validate_entry(self.read_json())
                with LOCK, connect() as db:
                    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                    cursor = db.execute("""INSERT INTO entries(kind,title,category,start_utc,end_utc,rewards,details,points,scoring,author,created_at,modified_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (*values, stamp, stamp))
                    created_id = cursor.lastrowid
                return self.respond(201, {"id": created_id})
            match = re.fullmatch(r"/api/entries/(\d+)", path)
            if match and method in ("PUT", "DELETE"):
                entry_id = int(match.group(1))
                with LOCK, connect() as db:
                    if method == "DELETE":
                        cursor = db.execute("DELETE FROM entries WHERE id=?", (entry_id,))
                    else:
                        values = validate_entry(self.read_json())
                        stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
                        cursor = db.execute("""UPDATE entries SET kind=?,title=?,category=?,start_utc=?,end_utc=?,
                            rewards=?,details=?,points=?,scoring=?,author=?,modified_at=?,reminded_at=NULL,reminder_claimed_at=NULL WHERE id=?""",
                            (*values, stamp, entry_id))
                    if cursor.rowcount == 0:
                        return self.respond(404, {"error": "Entry not found."})
                return self.respond(200, {"ok": True})
            if path == "/api/rss/spending" and method == "POST":
                payload = self.read_json()
                resource = payload.get("resource")
                if resource not in RSS_RESOURCES:
                    raise ValueError("Choose a valid resource.")
                amount = optional_rss_number(payload.get("amount"), "Spending amount")
                if amount is None or amount <= 0:
                    raise ValueError("Spending amount must be greater than zero.")
                spent_at = clean(payload.get("spent_at", ""), 19, True)
                moment = parse_utc(spent_at)
                note = clean(payload.get("note", ""), 280)
                current = datetime.now(timezone.utc)
                if moment > current.timestamp():
                    raise ValueError("Spending time cannot be in the future.")
                with LOCK, connect() as db:
                    settings = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM settings")}
                    anchor = settings.get("rss_base_at") or settings.get("rss_updated_at") or current.isoformat()
                    if moment < datetime.fromisoformat(anchor).timestamp():
                        raise ValueError("Spending must be dated on or after the last balance update.")
                    history = [dict(row) for row in db.execute("SELECT * FROM rss_spending ORDER BY spent_at,id")]
                    history.append({"id": max((row["id"] for row in history), default=0) + 1,
                                    "resource": resource, "amount": amount, "spent_at": spent_at,
                                    "note": note, "created_at": current.isoformat()})
                    result = rss_state(settings, history, current)
                    if result["resources"][resource]["current"] is None:
                        raise ValueError("Enter a starting balance for this resource before recording spending.")
                    cursor = db.execute("""INSERT INTO rss_spending(resource,amount,spent_at,note,created_at)
                        VALUES(?,?,?,?,?)""", (resource, amount, spent_at, note, current.isoformat(timespec="microseconds")))
                    db.execute("UPDATE settings SET value=? WHERE key='rss_updated_at'",
                               (current.isoformat(timespec="microseconds"),))
                return self.respond(201, {"id": cursor.lastrowid})
            spending_match = re.fullmatch(r"/api/rss/spending/(\d+)", path)
            if spending_match and method == "DELETE":
                with LOCK, connect() as db:
                    cursor = db.execute("DELETE FROM rss_spending WHERE id=?", (int(spending_match.group(1)),))
                    if not cursor.rowcount:
                        return self.respond(404, {"error": "Spending entry not found."})
                    db.execute("UPDATE settings SET value=? WHERE key='rss_updated_at'",
                               (datetime.now(timezone.utc).isoformat(timespec="microseconds"),))
                return self.respond(200, {"ok": True})
            if path == "/api/rss" and method == "PUT":
                data = self.read_json()
                if "resources" in data or "buffs" in data:
                    values = validate_rss(data)
                    current = datetime.now(timezone.utc)
                    updates = {
                        "rss_resources": json.dumps(values["resources"], separators=(",", ":")),
                        "rss_base_at": current.isoformat(timespec="seconds"),
                        "rss_buffs": json.dumps(values["buffs"], separators=(",", ":")),
                        "rss_tech_name": values["tech_name"],
                        "tech_plan": values["tech_plan"],
                        "rss_territory_plan": values["territory_plan"],
                        "rss_updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")
                    }
                    if "tech_progress" in data:
                        updates["rss_tech_progress"] = "" if values["tech_progress"] is None else str(values["tech_progress"])
                    if "tech_stage" in data:
                        updates["rss_tech_stage"] = values["tech_stage"]
                    if "tech_remaining" in data:
                        updates["rss_tech_ends_at"] = research_deadline(values["tech_remaining"])
                else:
                    hourly = clean(data.get("rss_hour", ""), 80)
                    tech = clean(data.get("tech_plan", ""), 2500)
                    if hourly and not re.fullmatch(r"\d[\d,. ]*", hourly):
                        raise ValueError("Enter a numeric hourly RSS amount.")
                    updates = {"rss_hour": hourly, "tech_plan": tech, "rss_updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds")}
                with LOCK, connect() as db:
                    stored_revision = db.execute("SELECT value FROM settings WHERE key='rss_updated_at'").fetchone()
                    current_revision = stored_revision["value"] if stored_revision else ""
                    if "revision" in data and data["revision"] != current_revision:
                        return self.respond(409, {"error": "Alliance RSS changed while you were editing. Reload the page and try again."})
                    if "rss_resources" in updates:
                        latest_spending_id = db.execute("SELECT COALESCE(MAX(id),0) FROM rss_spending").fetchone()[0]
                        updates["rss_base_spend_id"] = str(latest_spending_id)
                    for key, value in updates.items():
                        db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                   (key, value))
                return self.respond(200, {"ok": True})
            return self.respond(404, {"error": "Not found."})
        except PermissionError as exc:
            return self.respond(403, {"error": str(exc)})
        except ValueError as exc:
            return self.respond(400, {"error": str(exc)})
        except Exception:
            logging.exception("Request failed")
            return self.respond(500, {"error": "Server error."})

    def do_POST(self):
        self.write("POST")
    def do_PUT(self):
        self.write("PUT")
    def do_DELETE(self):
        self.write("DELETE")
    def do_PATCH(self):
        self.write("PATCH")

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init()
    for kind, url in (("reminder", WEBHOOK), ("registration", REGISTRATION_WEBHOOK), ("login", LOGIN_WEBHOOK)):
        logging.info("Discord %s webhook: %s", kind,
            "ready" if url and webhook_valid(url) else "invalid URL" if url else "NOT CONFIGURED")
    if WEBHOOK:
        threading.Thread(target=reminder_loop, daemon=True).start()
    logging.info("SaS Website listening on %s:%s", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
