"""HTTP regression tests for server-side authentication boundaries."""
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import members
import server


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original_db = server.DB
        self.original_password = server.ADMIN_PASSWORD
        self.original_cookie = server.COOKIE_SECURE
        server.DB = Path(self.folder.name) / "security.sqlite3"
        server.ADMIN_PASSWORD = "admin-test-secret-long"
        server.COOKIE_SECURE = False
        server.init()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        server.DB = self.original_db
        server.ADMIN_PASSWORD = self.original_password
        server.COOKIE_SECURE = self.original_cookie
        self.folder.cleanup()

    def call(self, path, method="GET", body=None, cookie=None, csrf=None, headers=None):
        h = dict(headers or {})
        if body is not None:
            h["Content-Type"] = "application/json"
        if cookie:
            h["Cookie"] = cookie
        if csrf:
            h["X-CSRF-Token"] = csrf
        request = Request(self.base + path, headers=h,
                          data=json.dumps(body).encode() if body is not None else None, method=method)
        try:
            with urlopen(request, timeout=6) as response:
                return response.status, response.read(), response.headers
        except HTTPError as error:
            return error.code, error.read(), error.headers

    def login_admin(self):
        status, raw, headers = self.call("/api/login", "POST", {
            "username": server.ADMIN_USER, "password": "admin-test-secret-long"})
        self.assertEqual(status, 200, raw)
        return headers.get("Set-Cookie").split(";", 1)[0], json.loads(raw)["csrf"]

    def register(self, username, status):
        with server.connect() as db:
            members.register(db, {
                "username": username, "player_name": username, "email": username + "@example.com",
                "password": "member-password-long"
            })
            db.execute("UPDATE members SET status=? WHERE username=?", (status, username))

    def login_member(self, name):
        status, raw, headers = self.call("/api/member/login", "POST",
                                         {"username": name, "password": "member-password-long"})
        self.assertEqual(status, 200, raw)
        return headers.get("Set-Cookie").split(";", 1)[0], json.loads(raw)["csrf"]

    def test_guest_only_receives_login_html_not_website(self):
        status, raw, headers = self.call("/#events")
        self.assertEqual(status, 200)
        self.assertIn(b'id="auth-gate"', raw)
        self.assertNotIn(b'id="website"', raw)
        self.assertNotIn(b'id="page-accounts"', raw)
        self.assertIn("no-store", headers.get("Cache-Control"))
        for path in ("/index.html", "/app", "/api/state", "/api/accounts"):
            status, raw, _ = self.call(path)
            self.assertIn(status, (401, 403), (path, raw))
        for path in ("/api/entries", "/api/rss", "/api/rss/spending"):
            status, raw, _ = self.call(path, "POST", {})
            self.assertEqual(status, 403, (path, raw))
        status, raw, _ = self.call("/auth.js")
        self.assertEqual(status, 200)
        self.assertNotIn(b"site.entries", raw)

    def test_pending_and_rejected_accounts_are_denied(self):
        self.register("PendingGuy", "pending")
        self.register("RejectedGuy", "rejected")
        for name in ("PendingGuy", "RejectedGuy"):
            status, _, _ = self.call("/api/member/login", "POST", {
                "username": name, "password": "member-password-long"})
            self.assertEqual(status, 403)
        self.assertEqual(self.call("/api/state")[0], 401)

    def test_approved_member_gets_site_but_not_admin(self):
        self.register("ApprovedGuy", "approved")
        cookie, csrf = self.login_member("ApprovedGuy")
        status, raw, headers = self.call("/", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn(b'id="website"', raw)
        self.assertIn("no-store", headers.get("Cache-Control"))
        self.assertIn("Cookie", headers.get("Vary"))
        status, raw, _ = self.call("/api/state", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("entries", json.loads(raw))
        self.assertEqual(self.call("/api/accounts", cookie=cookie)[0], 403)
        self.assertEqual(self.call("/api/entries", "POST", {}, cookie, csrf)[0], 403)
        self.assertEqual(self.call("/api/rss", "PUT", {}, cookie, csrf)[0], 403)
        self.assertEqual(self.call("/api/accounts/1", "PATCH", {"status":"approved"}, cookie, csrf)[0], 403)
        self.assertEqual(self.call("/api/password/requests/1", "PATCH", {"decision":"approved"}, cookie, csrf)[0], 403)

    def test_admin_csrf_and_origin_boundaries(self):
        cookie, csrf = self.login_admin()
        self.assertEqual(self.call("/api/accounts", cookie=cookie)[0], 200)
        self.assertEqual(self.call("/", cookie=cookie)[0], 200)
        self.assertEqual(self.call("/api/entries", "POST", {}, cookie)[0], 403)
        self.assertEqual(self.call("/api/entries", "POST", {}, cookie, csrf)[0], 400)
        self.assertEqual(self.call("/api/entries", "POST", {}, cookie, csrf,
                                   {"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.call("/api/entries", "POST", {}, cookie, csrf,
                                   {"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.call("/api/logout", "POST", {}, cookie, csrf)[0], 200)
        self.assertEqual(self.call("/api/state", cookie=cookie)[0], 401)
        self.assertEqual(self.call("/api/accounts", cookie=cookie)[0], 403)

    def test_expired_sessions_do_not_authorize(self):
        self.register("TimeoutUser", "approved")
        cookie, _ = self.login_member("TimeoutUser")
        with server.connect() as db:
            db.execute("UPDATE member_sessions SET expires_at=?", (int(time.time()) - 1,))
        self.assertEqual(self.call("/")[1].count(b'id="website"'), 0)
        self.assertEqual(self.call("/api/state", cookie=cookie)[0], 401)

    def test_member_revocation_removes_private_access(self):
        self.register("RevokedUser", "approved")
        cookie, _ = self.login_member("RevokedUser")
        with server.connect() as db:
            db.execute("UPDATE members SET status='rejected' WHERE username='RevokedUser'")
        self.assertEqual(self.call("/api/state", cookie=cookie)[0], 401)
        self.assertNotIn(b'id="website"', self.call("/", cookie=cookie)[1])


    def test_admin_can_approve_and_edit_entries(self):
        self.register("ApplicantUser", "pending")
        cookie, csrf = self.login_admin()
        status, raw, _ = self.call("/api/accounts", cookie=cookie)
        self.assertEqual(status, 200)
        item = next(row for row in json.loads(raw)["accounts"] if row["username"] == "ApplicantUser")
        self.assertEqual(self.call("/api/accounts/" + str(item["id"]), "PATCH",
                                   {"status": "approved"}, cookie, csrf)[0], 200)
        player_cookie, _ = self.login_member("ApplicantUser")
        self.assertEqual(self.call("/api/state", cookie=player_cookie)[0], 200)
        event = {
            "kind": "events", "title": "Security verification event", "category": "Events",
            "start_utc": "2026-12-01 00:00:00", "end_utc": "2026-12-01 01:00:00",
            "details": "Only admins create events."
        }
        status, raw, _ = self.call("/api/entries", "POST", event, cookie, csrf)
        self.assertEqual(status, 201, raw)
        self.assertIn("id", json.loads(raw))
        self.assertEqual(self.call("/api/entries", "POST", event, player_cookie)[0], 403)
        self.assertEqual(self.call("/api/accounts/" + str(item["id"]), "PATCH",
                                   {"status": "rejected", "message": "Not in alliance"}, cookie, csrf)[0], 200)
        self.assertEqual(self.call("/api/state", cookie=player_cookie)[0], 401)

    def test_member_logout_and_cookie_flags(self):
        self.register("LogoutPlayer", "approved")
        cookie, csrf = self.login_member("LogoutPlayer")
        status, _, _ = self.call("/api/member/logout", "POST", {}, cookie)
        self.assertEqual(status, 403)  # CSRF required
        status, _, headers = self.call("/api/member/logout", "POST", {}, cookie, csrf)
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", self.call("/api/member/login", "POST", {
            "username": "LogoutPlayer", "password": "member-password-long"
        })[2].get("Set-Cookie"))
        self.assertEqual(self.call("/api/state", cookie=cookie)[0], 401)

    def test_maintenance_mode_blocks_every_app_and_api_route(self):
        previous = server.MAINTENANCE_MODE
        try:
            # Use a valid admin session to make sure maintenance does not trust it.
            cookie, csrf = self.login_admin()
            server.MAINTENANCE_MODE = True
            for path in ("/", "/#events"):
                status, body, headers = self.call(path)
                self.assertEqual(status, 503)
                self.assertIn(b"Under Construction", body)
                self.assertNotIn(b'id="website"', body)
                self.assertNotIn(b'id="auth-gate"', body)
                self.assertNotIn(b'data-view="accounts"', body)
                self.assertEqual(headers.get("Cache-Control"), "no-store, max-age=0")
            status, data, headers = self.call("/assets/logo.webp")
            self.assertEqual(status, 503)
            self.assertIn(b"under maintenance", data)
            self.assertIn(b'data:image/webp;base64,', body)
            for path in ("/index.html", "/app", "/login.html", "/auth.js",
                         "/app.js", "/styles.css", "/api/state", "/api/session",
                         "/api/accounts", "/api/not-real"):
                status, _, _ = self.call(path, cookie=cookie)
                self.assertEqual(status, 503, path)
            requests = [
                ("/api/login", "POST", {"username": "admin", "password": "test"}),
                ("/api/member/login", "POST", {"username": "Somebody", "password": "test"}),
                ("/api/register", "POST", {"username": "Somebody"}),
                ("/api/password/request", "POST", {"identifier": "Somebody"}),
                ("/api/password/complete", "POST", {"username": "Somebody", "code": "test", "new_password": "password"}),
                ("/api/accounts/1", "PATCH", {"status": "approved"}),
                ("/api/entries", "POST", {}),
                ("/api/entries/1", "PUT", {}),
                ("/api/entries/1", "DELETE", None),
                ("/api/rss", "PUT", {}),
                ("/api/logout", "POST", {})
            ]
            for path, method, body in requests:
                status, response, _ = self.call(path, method, body, cookie, csrf)
                self.assertEqual(status, 503, (method, path, response))
        finally:
            server.MAINTENANCE_MODE = previous

    def test_maintenance_design_is_noninteractive(self):
        # The construction screen must not accidentally expose links, forms or site navigation.
        content = (server.ROOT / "maintenance.html").read_text(encoding="utf-8")
        self.assertIn("Under Construction", content)
        self.assertIn("Thank you for your patience.", content)
        self.assertIn("SAINTS AND SINNERS", content)
        self.assertIn("data:image/webp;base64,", content)
        self.assertNotIn("src=\"/assets/logo.webp\"", content)
        for forbidden in ('<nav', '<form', '<button', '<a href=', 'id="website"',
                          'id="auth-gate"', '/app.js', '/auth.js', '/api/'):
            self.assertNotIn(forbidden, content)

    def test_maintenance_mode_off_restores_normal_authentication(self):
        previous = server.MAINTENANCE_MODE
        try:
            server.MAINTENANCE_MODE = False
            status, page, _ = self.call("/")
            self.assertEqual(status, 200)
            self.assertIn(b'id="auth-gate"', page)
            self.assertEqual(self.call("/api/state")[0], 401)
            self.assertEqual(self.call("/api/session")[0], 200)
            self.register("NormalModePlayer", "approved")
            member_cookie, _ = self.login_member("NormalModePlayer")
            status, app, _ = self.call("/", cookie=member_cookie)
            self.assertEqual(status, 200)
            self.assertIn(b'id="website"', app)
        finally:
            server.MAINTENANCE_MODE = previous

    def test_member_unread_counts_are_private_persistent_and_csrf_protected(self):
        self.register("FirstReader", "approved")
        self.register("SecondReader", "approved")
        admin_cookie, admin_csrf = self.login_admin()
        event = {
            "kind": "announcements", "title": "New HR Announcement",
            "details": "Members need to see this", "category": "", "author": "R4",
        }
        status, raw, _ = self.call("/api/entries", "POST", event, admin_cookie, admin_csrf)
        self.assertEqual(status, 201, raw)
        one_cookie, one_csrf = self.login_member("FirstReader")
        two_cookie, two_csrf = self.login_member("SecondReader")
        self.assertEqual(self.call("/api/reads")[0], 401)
        status, raw, _ = self.call("/api/reads", cookie=one_cookie)
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["seen"]["announcements"], {})
        self.assertEqual(self.call("/api/reads", "POST", {"kind": "announcements"}, one_cookie)[0], 403)
        self.assertEqual(self.call("/api/reads", "POST", {"kind": "not_a_page"}, one_cookie, one_csrf)[0], 400)
        status, raw, _ = self.call("/api/reads", "POST",
                                   {"kind": "announcements"}, one_cookie, one_csrf)
        self.assertEqual(status, 200, raw)
        self.assertEqual(len(json.loads(raw)["seen"]["announcements"]), 1)
        status, raw, _ = self.call("/api/reads", cookie=two_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["seen"]["announcements"], {})
        status, raw, _ = self.call("/api/reads", cookie=one_cookie)
        self.assertEqual(len(json.loads(raw)["seen"]["announcements"]), 1)
        self.assertEqual(self.call("/api/reads", "POST",
                                   {"kind": "announcements"}, two_cookie, one_csrf)[0], 403)
        with server.connect() as db:
            row = db.execute("SELECT COUNT(*) FROM member_reads").fetchone()[0]
        self.assertEqual(row, 1)

    def test_discord_account_notifications_only_on_success(self):
        from unittest.mock import patch
        events = []
        signaled = threading.Event()

        def record(*args):
            events.append(args)
            signaled.set()

        with patch.object(server, "discord_account_notice", side_effect=record):
            status, raw, _ = self.call("/api/register", "POST", {
                "username": "NewApplicant", "player_name": "Chief Tester",
                "email": "chief@example.com", "password": "super-secret-pass-123"
            })
            self.assertEqual(status, 201, raw)
            self.assertTrue(signaled.wait(2))
            self.assertEqual(events[0], ("registration", "MEMBER",
                                         "NewApplicant", "chief@example.com", "Chief Tester"))
            signaled.clear()

            bad = self.call("/api/member/login", "POST", {
                "username": "NewApplicant", "password": "incorrect-password"
            })
            self.assertEqual(bad[0], 401)
            pending = self.call("/api/member/login", "POST", {
                "username": "NewApplicant", "password": "super-secret-pass-123"
            })
            self.assertEqual(pending[0], 403)
            self.assertEqual(len(events), 1)

            with server.connect() as db:
                db.execute("UPDATE members SET status='approved' WHERE username='NewApplicant'")
            status, raw, _ = self.call("/api/member/login", "POST", {
                "username": "NewApplicant", "password": "super-secret-pass-123"
            })
            self.assertEqual(status, 200, raw)
            self.assertTrue(signaled.wait(2))
            self.assertEqual(events[1], ("login", "MEMBER", "NewApplicant", "chief@example.com"))
            signaled.clear()
            self.assertEqual(self.call("/api/login", "POST", {
                "username": server.ADMIN_USER, "password": "wrong"
            })[0], 401)
            self.assertEqual(len(events), 2)
            admin_cookie, _ = self.login_admin()
            self.assertIn("sas_session=", admin_cookie)
            self.assertTrue(signaled.wait(2))
            self.assertEqual(events[2], ("login", "ADMIN", server.ADMIN_USER))
            self.assertEqual(len(events), 3)
            self.assertNotIn("super-secret-pass-123", repr(events))
            self.assertNotIn("incorrect-password", repr(events))

    def test_admin_can_edit_and_delete_accounts_with_csrf(self):
        self.register("ManageTest", "approved")
        with server.connect() as db:
            member = db.execute("SELECT id FROM members WHERE username='ManageTest'").fetchone()
            member_id = member["id"]
            members.new_session(db, member_id)
            members.request_password_reset(db, "ManageTest")
        admin_cookie, csrf = self.login_admin()
        member_cookie, member_csrf = self.login_member("ManageTest")
        path = "/api/accounts/" + str(member_id)
        values = {"username": "ManagedTest", "player_name": "Edited Ingame",
                  "email": "edited@example.com"}

        self.assertEqual(self.call(path, "PUT", values)[0], 403)
        self.assertEqual(self.call(path, "DELETE", cookie=member_cookie, csrf=member_csrf)[0], 403)
        self.assertEqual(self.call(path, "PUT", values, admin_cookie)[0], 403)
        self.assertEqual(self.call(path, "DELETE", cookie=admin_cookie)[0], 403)

        self.assertEqual(self.call(path, "PUT", values, admin_cookie, csrf)[0], 200)
        with server.connect() as db:
            row = db.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
            self.assertEqual(row["username"], "ManagedTest")
            self.assertEqual(row["player_name"], "Edited Ingame")
            self.assertEqual(row["email"], "edited@example.com")
        self.assertEqual(self.call(path, "PUT", {
            "username": "bad user", "player_name": "Bad", "email": "bad@example.com"
        }, admin_cookie, csrf)[0], 400)
        self.assertEqual(self.call(path, "DELETE", cookie=admin_cookie, csrf=csrf)[0], 200)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM members WHERE id=?", (member_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM member_sessions WHERE member_id=?", (member_id,)).fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM password_requests WHERE member_id=?", (member_id,)).fetchone()[0], 0)
        self.assertEqual(self.call(path, "DELETE", cookie=admin_cookie, csrf=csrf)[0], 404)
        self.assertEqual(self.call("/api/state", cookie=member_cookie)[0], 401)

    def test_requested_password_reset_reaches_admin_queue(self):
        self.register("LostPass", "approved")
        admin_cookie, _ = self.login_admin()
        status, raw, _ = self.call("/api/password/request", "POST", {"identifier": "LostPass"})
        self.assertEqual(status, 200, raw)
        self.assertIn(b"submitted", raw)
        status, raw, _ = self.call("/api/accounts", cookie=admin_cookie)
        self.assertEqual(status, 200, raw)
        listing = json.loads(raw)["password_requests"]
        self.assertTrue(any(item["username"] == "LostPass" and item["status"] == "pending"
                            for item in listing))

    def test_admin_auto_expires_after_30_minutes_without_human_activity(self):
        cookie, csrf = self.login_admin()
        status, data, _ = self.call("/api/session", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["admin"])
        self.assertEqual(json.loads(data)["admin_idle_timeout_seconds"], 1800)
        # Ordinary background API polling cannot refresh the admin idle window.
        with server.connect() as db:
            db.execute("UPDATE sessions SET last_activity_at=?",
                       (int(time.time()) - 1799,))
        self.assertEqual(self.call("/api/state", cookie=cookie)[0], 200)
        self.assertEqual(self.call("/api/admin/activity", "POST", {}, cookie, csrf)[0], 200)
        with server.connect() as db:
            row = db.execute("SELECT last_activity_at FROM sessions").fetchone()
            self.assertGreaterEqual(row["last_activity_at"], int(time.time())-2)
            db.execute("UPDATE sessions SET last_activity_at=?",
                       (int(time.time())-1801,))
        self.assertEqual(self.call("/api/state", cookie=cookie)[0], 401)
        self.assertEqual(self.call("/api/accounts", cookie=cookie)[0], 403)
        self.assertEqual(self.call("/api/admin/activity", "POST", {}, cookie, csrf)[0], 403)
        self.assertEqual(self.call("/api/entries", "POST", {
            "kind": "updates", "title": "Expired admin", "details": "No write",
        }, cookie, csrf)[0], 403)
        self.assertFalse(json.loads(self.call("/api/session", cookie=cookie)[1])["admin"])

    def test_admin_activity_requires_valid_csrf_and_session(self):
        cookie, csrf = self.login_admin()
        self.assertEqual(self.call("/api/admin/activity", "POST", {}, cookie)[0], 403)
        self.assertEqual(self.call("/api/admin/activity", "POST", {}, cookie, "wrong")[0], 403)
        self.assertEqual(self.call("/api/admin/activity", "POST", {}, cookie, csrf)[0], 200)
        self.assertEqual(self.call("/api/admin/activity", "POST", {})[0], 403)

    def test_discord_delivery_status_and_tests_are_admin_only(self):
        from unittest.mock import patch
        cookie, csrf = self.login_admin()
        self.assertEqual(self.call("/api/notifications/status")[0], 403)
        self.assertEqual(self.call("/api/notifications/test", "POST",
                                   {"channel": "login"})[0], 403)
        self.assertEqual(self.call("/api/notifications/test", "POST",
                                   {"channel": "login"}, cookie)[0], 403)
        self.assertEqual(self.call("/api/notifications/test", "POST",
                                   {"channel": "invalid"}, cookie, csrf)[0], 400)
        with (
            patch.object(server, "LOGIN_WEBHOOK",
                         "https://discord.com/api/webhooks/123456789/FakeTestToken"),
            patch.object(server, "discord_send", return_value=True) as delivery,
        ):
            status, raw, _ = self.call("/api/notifications/test", "POST",
                                       {"channel": "login"}, cookie, csrf)
            self.assertEqual(status, 200, raw)
            delivery.assert_called_once()
            self.assertEqual(delivery.call_args.args[0], "login")
        status, raw, _ = self.call("/api/notifications/status", cookie=cookie)
        self.assertEqual(status, 200, raw)
        self.assertIn("channels", json.loads(raw))
        self.assertNotIn("api/webhooks", raw.decode())

    def test_admin_login_rate_limit(self):
        for _ in range(10):
            status, _, _ = self.call("/api/login", "POST", {
                "username": "admin", "password": "incorrect"})
            self.assertEqual(status, 401)
        self.assertEqual(self.call("/api/login", "POST", {
            "username": "admin", "password": "admin-test-secret-long"})[0], 429)


if __name__ == "__main__":
    unittest.main()
