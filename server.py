import hmac
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
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        os.environ.setdefault(key, setting.strip().strip('"').strip("'"))

load_local_env()
DB = Path(os.environ.get("SAS_DB_PATH", str(ROOT / "data" / "website.sqlite3")))
HOST = os.environ.get("SAS_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVER_PORT") or os.environ.get("PORT") or "8080")
ADMIN_USER = os.environ.get("SAS_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("SAS_ADMIN_PASSWORD", "")
COOKIE_SECURE = os.environ.get("SAS_COOKIE_SECURE", "1") != "0"
WEBHOOK = os.environ.get("SAS_DISCORD_WEBHOOK_URL", "")
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
        db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            csrf TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        )""")
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
                    "rss_territory_plan", "rss_updated_at"):
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
        normalized_resources[key] = {
            "stored": optional_rss_number(item.get("stored"), key + " stored resources"),
            "per_hour": optional_rss_number(item.get("per_hour"), key + " per hour")
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

def rss_state(settings):
    def object_value(key):
        try:
            value = json.loads(settings.get(key) or "{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            return {}

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
        "legacy_hour": settings.get("rss_hour", "")
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

def get_state():
    with LOCK, connect() as db:
        rows = db.execute("""SELECT id,kind,title,category,start_utc,end_utc,rewards,details,author,created_at,modified_at
            FROM entries ORDER BY CASE WHEN kind IN ('events','alliance') THEN start_utc ELSE created_at END DESC, id DESC""").fetchall()
        settings = {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM settings").fetchall()}
    return {"entries": [dict(row) for row in rows], "settings": settings,
            "rss": rss_state(settings), "utc": now_utc()}

def webhook_valid(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in ("discord.com", "discordapp.com") and not parts.username
        and not parts.password and parts.port in (None, 443) and not parts.query and not parts.fragment
        and re.fullmatch(r"/api/webhooks/\d+/[A-Za-z0-9_-]+", parts.path) is not None)

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
        self.end_headers()
        self.wfile.write(body)

    def asset(self, filename, mime):
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
        self.send_header("Cache-Control", "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/state":
            return self.respond(200, get_state())
        if path == "/api/session":
            session = current_session(self)
            return self.respond(200, {"admin": bool(session), "csrf": session["csrf"] if session else None})
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/index.html": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/calendar.js": ("calendar.js", "text/javascript; charset=utf-8"),
                  "/rss.js": ("rss.js", "text/javascript; charset=utf-8"),
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

    def authorized(self):
        session = current_session(self)
        if not session or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
            self.respond(403, {"error": "Administrator access required."})
            return False
        return True

    def write(self, method):
        path = urlsplit(self.path).path
        try:
            if path == "/api/login" and method == "POST":
                data = self.read_json()
                if not ADMIN_PASSWORD or not hmac.compare_digest(str(data.get("username", "")), ADMIN_USER) or not hmac.compare_digest(str(data.get("password", "")), ADMIN_PASSWORD):
                    time.sleep(0.5)
                    return self.respond(401, {"error": "Incorrect credentials or administrator login is not configured."})
                token = secrets.token_urlsafe(32)
                csrf = secrets.token_urlsafe(24)
                digest = __import__("hashlib").sha256(token.encode()).hexdigest()
                with LOCK, connect() as db:
                    db.execute("DELETE FROM sessions WHERE expires_at<?", (int(time.time()),))
                    db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest, csrf, int(time.time()) + 43200))
                self.send_response(200)
                secure = "; Secure" if COOKIE_SECURE else ""
                self.send_header("Set-Cookie", f"sas_session={token}; Path=/; HttpOnly; SameSite=Lax{secure}")
                self.send_header("Cache-Control", "no-store")
                result = json.dumps({"admin": True, "csrf": csrf}).encode()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)
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
            if path == "/api/rss" and method == "PUT":
                data = self.read_json()
                if "resources" in data or "buffs" in data:
                    values = validate_rss(data)
                    updates = {
                        "rss_resources": json.dumps(values["resources"], separators=(",", ":")),
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

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init()
    if WEBHOOK:
        threading.Thread(target=reminder_loop, daemon=True).start()
    logging.info("SaS Website listening on %s:%s", HOST, PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
