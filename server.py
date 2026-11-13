import hmac
import hashlib
import members
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
        if kind == "announcements" and author not in ("R4", "R5"):
            raise ValueError("Choose R4 or R5.")
        if kind == "updates":
            author = ""
    return kind, title, category, start, end, rewards, details, author

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
        rows = db.execute("""SELECT id,kind,title,category,start_utc,end_utc,rewards,details,author,created_at,modified_at
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
