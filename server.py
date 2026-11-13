import hmac
import hashlib
import members
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
LOCK = threading.RLock()
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
        db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            csrf TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        )""")
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
    with LOCK, connect() as db:
        row = db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?", (token_hash, int(time.time()))).fetchone()
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
    def deliver():
        try:
            request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status >= 300:
                    logging.warning("Account Discord notification returned a non-success status.")
        except Exception:
            # Do not log the secret URL or response body containing webhook credentials.
            logging.warning("Unable to deliver account notification.")
    threading.Thread(target=deliver, name="sas-discord-account-notice", daemon=True).start()

def reminder_loop():
    if not WEBHOOK:
        return
    if not webhook_valid(WEBHOOK):
        logging.error("Discord webhook URL is invalid.")
        return
    logging.info("Discord event reminders enabled.")
    while True:
        try:
            current = int(time.time())
            cutoff = datetime.fromtimestamp(current + 3600, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            moment = datetime.fromtimestamp(current, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            with LOCK, connect() as db:
                row = db.execute("""SELECT * FROM entries WHERE kind IN ('events','alliance')
                    AND start_utc>? AND start_utc<=? AND reminded_at IS NULL
                    AND (reminder_claimed_at IS NULL OR reminder_claimed_at<?)
                    ORDER BY start_utc LIMIT 1""", (moment, cutoff, current - 120)).fetchone()
                if row:
                    db.execute("UPDATE entries SET reminder_claimed_at=? WHERE id=?", (current, row["id"]))
            if row:
                data = {
                    "content": "@everyone An event starts within the next hour.",
                    "allowed_mentions": {"parse": ["everyone"]},
                    "embeds": [{"title": row["title"], "fields": [
                        {"name": "Start (UTC)", "value": row["start_utc"]},
                        {"name": "End (UTC)", "value": row["end_utc"]},
                        {"name": "Section", "value": "Alliance Events" if row["kind"] == "alliance" else "Events"}
                    ]}]
                }
                request = urllib.request.Request(WEBHOOK, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="POST")
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        if response.status >= 300:
                            raise RuntimeError("Notification unsuccessful.")
                    with LOCK, connect() as db:
                        db.execute("UPDATE entries SET reminded_at=? WHERE id=? AND start_utc=?",
                            (current, row["id"], row["start_utc"]))
                except Exception:
                    logging.warning("Unable to send event reminder.")
            else:
                time.sleep(25)
        except Exception:
            logging.exception("Reminder check failed.")
            time.sleep(30)

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

    def do_GET(self):
        path = urlsplit(self.path).path
        if MAINTENANCE_MODE:
            return self.maintenance_response(path)
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
        if path == "/api/accounts":
            if not current_session(self):
                return self.respond(403, {"error": "Administrator access required."})
            with LOCK, connect() as db:
                accounts = [members.public_member(row) for row in db.execute(
                    "SELECT * FROM members ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, created_at DESC")]
            with LOCK, connect() as db:
                resets = members.list_password_requests(db)
            return self.respond(200, {"accounts": accounts, "password_requests": resets})
        if path == "/api/session":
            session = current_session(self)
            player = members.member_session(self, connect, LOCK)
            return self.respond(200, {"admin": bool(session), "approved": bool(player and player["status"] == "approved"),
                "username": player["username"] if player else (ADMIN_USER if session else None),
                "status": player["status"] if player else None,
                "review_message": player["review_message"] if player else "",
                "csrf": session["csrf"] if session else (player["csrf"] if player else None)})
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
                  "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                  "/assets/logo.webp": ("assets/logo.webp", "image/webp"),
                  "/assets/crest.avif": ("assets/crest.avif", "image/avif")}
        if path in assets:
            return self.asset(*assets[path])
        return self.respond(404, {"error": "Not found."})

    def read_json(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid content length.")
        if size < 1 or size > 16000:
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
                    members.register(db, values)
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
                    if row["status"] != "approved":
                        return self.respond(403, {"error": "Your account is awaiting approval." if row["status"] == "pending" else
                            "Your application was declined: " + (row["review_message"] or "Contact an administrator.")})
                    token, csrf = members.new_session(db, row["id"])
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
                    db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest, csrf, int(time.time()) + 43200))
                clear_login_failures("admin", source)
                self.session_cookie("sas_session", token, {"admin": True, "csrf": csrf})
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
                    cursor = db.execute("""INSERT INTO entries(kind,title,category,start_utc,end_utc,rewards,details,author,created_at,modified_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""", (*values, stamp, stamp))
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
                            rewards=?,details=?,author=?,modified_at=?,reminded_at=NULL,reminder_claimed_at=NULL WHERE id=?""",
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
    if WEBHOOK:
        threading.Thread(target=reminder_loop, daemon=True).start()
    logging.info("SaS Website listening on %s:%s", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
