import json
from datetime import datetime, timedelta, timezone
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class RssTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original_db = server.DB
        self.original_password = server.ADMIN_PASSWORD
        self.original_cookie = server.COOKIE_SECURE
        server.DB = Path(self.folder.name) / "rss.sqlite3"
        server.ADMIN_PASSWORD = "rss-testing-only"
        server.COOKIE_SECURE = False
        server.init()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.state_cookie, _ = self.login()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=5)
        server.DB = self.original_db
        server.ADMIN_PASSWORD = self.original_password
        server.COOKIE_SECURE = self.original_cookie
        self.folder.cleanup()

    def send(self, path, method="GET", payload=None, cookie=None, csrf=None):
        headers = {"Content-Type": "application/json"}
        if path == "/api/state" and cookie is None:
            cookie = self.state_cookie
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        data = None if payload is None else json.dumps(payload).encode()
        request = Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read()), response.headers
        except HTTPError as error:
            return error.code, json.loads(error.read()), error.headers

    def login(self):
        status, response, headers = self.send("/api/login", "POST", {
            "username": server.ADMIN_USER,
            "password": "rss-testing-only"
        })
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0], response["csrf"]

    def payload(self):
        return {
            "resources": {
                "ammo": {"stored": 21200, "per_hour": 122400},
                "cash": {"stored": 374000, "per_hour": 122400},
                "electricity": {"stored": 840400, "per_hour": 93600},
                "gas": {"stored": 1000000, "per_hour": 50400}
            },
            "buffs": {
                "troop_attack": 8,
                "troop_defense": 0,
                "troop_hp": None,
                "resource_gathering": 15.5
            },
            "tech_name": "Territory Expansion",
            "tech_plan": "Expand flags and donate to the research priority.",
            "tech_progress": 72,
            "territory_plan": "Place another flag near the main resource area."
        }

    def test_state_requires_approved_login(self):
        request = Request(self.url + "/api/state")
        with self.assertRaises(HTTPError) as failure:
            urlopen(request, timeout=5)
        self.assertEqual(failure.exception.code, 401)

    def test_first_load_contains_no_fabricated_rss_values(self):
        status, response, _ = self.send("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(set(response["rss"]["resources"]), set(server.RSS_RESOURCES))
        self.assertTrue(all(item["stored"] is None and item["per_hour"] is None
                            for item in response["rss"]["resources"].values()))
        self.assertTrue(all(value is None for value in response["rss"]["buffs"].values()))
        self.assertIsNone(response["rss"]["tech_progress"])
        self.assertEqual(len(response["entries"]), 8)

    def test_edit_requires_login_and_csrf(self):
        status, _, _ = self.send("/api/rss", "PUT", self.payload())
        self.assertEqual(status, 403)
        cookie, csrf = self.login()
        status, _, _ = self.send("/api/rss", "PUT", self.payload(), cookie=cookie)
        self.assertEqual(status, 403)
        status, _, _ = self.send("/api/rss", "PUT", self.payload(), cookie=cookie, csrf=csrf)
        self.assertEqual(status, 200)

    def test_valid_values_persist_and_do_not_modify_other_pages(self):
        original = self.send("/api/state")[1]["entries"]
        cookie, csrf = self.login()
        status, _, _ = self.send("/api/rss", "PUT", self.payload(), cookie, csrf)
        self.assertEqual(status, 200)
        state = self.send("/api/state")[1]
        self.assertEqual(state["rss"]["resources"]["ammo"]["stored"], 21200)
        self.assertEqual(state["rss"]["resources"]["gas"]["per_hour"], 50400)
        self.assertEqual(state["rss"]["buffs"]["troop_defense"], 0)
        self.assertIsNone(state["rss"]["buffs"]["troop_hp"])
        self.assertEqual(state["rss"]["tech_progress"], 72)
        self.assertEqual(state["rss"]["tech_name"], "Territory Expansion")
        self.assertTrue(state["rss"]["updated_at"].endswith("+00:00"))
        self.assertEqual(state["entries"], original)

    def test_invalid_values_do_not_overwrite_existing_data(self):
        cookie, csrf = self.login()
        first = self.payload()
        self.assertEqual(self.send("/api/rss", "PUT", first, cookie, csrf)[0], 200)
        for key, bad_value in [
            ("stored", -1),
            ("stored", True),
            ("per_hour", "12K"),
            ("per_hour", 1000000000000001)
        ]:
            invalid = self.payload()
            invalid["resources"]["ammo"][key] = bad_value
            self.assertEqual(self.send("/api/rss", "PUT", invalid, cookie, csrf)[0], 400)
        bad_buff = self.payload()
        bad_buff["buffs"]["troop_attack"] = 1200
        self.assertEqual(self.send("/api/rss", "PUT", bad_buff, cookie, csrf)[0], 400)
        bad_progress = self.payload()
        bad_progress["tech_progress"] = 101
        self.assertEqual(self.send("/api/rss", "PUT", bad_progress, cookie, csrf)[0], 400)
        state = self.send("/api/state")[1]["rss"]
        self.assertEqual(state["resources"]["ammo"]["stored"], 21200)
        self.assertEqual(state["tech_progress"], 72)

    def test_zero_and_unset_are_distinct(self):
        cookie, csrf = self.login()
        payload = self.payload()
        payload["resources"]["ammo"]["stored"] = 0
        payload["resources"]["ammo"]["per_hour"] = None
        payload["tech_progress"] = 0
        self.assertEqual(self.send("/api/rss", "PUT", payload, cookie, csrf)[0], 200)
        result = self.send("/api/state")[1]["rss"]
        self.assertEqual(result["resources"]["ammo"]["stored"], 0)
        self.assertIsNone(result["resources"]["ammo"]["per_hour"])
        self.assertEqual(result["tech_progress"], 0)

    def test_legacy_total_and_technology_note_survive_migration(self):
        with server.connect() as db:
            db.execute("UPDATE settings SET value='155000' WHERE key='rss_hour'")
            db.execute("UPDATE settings SET value='Research Headquarters' WHERE key='tech_plan'")
        server.init()
        state = self.send("/api/state")[1]["rss"]
        self.assertEqual(state["legacy_hour"], "155000")
        self.assertEqual(state["tech_plan"], "Research Headquarters")
        self.assertIsNone(state["resources"]["ammo"]["per_hour"])
        cookie, csrf = self.login()
        updated = self.payload()
        updated["tech_plan"] = state["tech_plan"]
        self.assertEqual(self.send("/api/rss", "PUT", updated, cookie, csrf)[0], 200)
        self.assertEqual(self.send("/api/state")[1]["rss"]["legacy_hour"], "155000")

    def test_resource_income_stops_at_cap_and_resumes_after_spending(self):
        resources = {
            key: {"stored": None, "per_hour": None, "limit": 1200000}
            for key in server.RSS_RESOURCES
        }
        resources["ammo"] = {"stored": 1000, "per_hour": 3600, "limit": 1200}
        settings = {
            "rss_resources": json.dumps(resources),
            "rss_base_at": "2026-11-10T00:00:00+00:00"
        }
        moment = datetime(2026, 11, 10, 0, 5, 0, tzinfo=timezone.utc)
        without_spending = server.rss_state(settings, [], moment)
        self.assertEqual(without_spending["resources"]["ammo"]["current"], 1200)
        spending = [{
            "id": 1, "resource": "ammo", "amount": 100,
            "spent_at": "2026-11-10 00:04:00", "note": "Research",
            "created_at": "2026-11-10T00:04:00+00:00"
        }]
        with_spending = server.rss_state(settings, spending, moment)
        self.assertEqual(with_spending["resources"]["ammo"]["current"], 1160)
        later = datetime(2026, 11, 10, 0, 15, tzinfo=timezone.utc)
        self.assertEqual(server.rss_state(settings, spending, later)["resources"]["ammo"]["current"], 1200)

    def test_spending_api_validation_permissions_and_recalculation(self):
        cookie, csrf = self.login()
        payload = self.payload()
        payload["resources"]["ammo"] = {"stored": 1000, "per_hour": 0, "limit": 1200000}
        self.assertEqual(self.send("/api/rss", "PUT", payload, cookie, csrf)[0], 200)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        entry = {"resource": "ammo", "amount": 250, "spent_at": now, "note": "Alliance research"}
        self.assertEqual(self.send("/api/rss/spending", "POST", entry)[0], 403)
        self.assertEqual(self.send("/api/rss/spending", "POST", entry, cookie)[0], 403)
        status, response, _ = self.send("/api/rss/spending", "POST", entry, cookie, csrf)
        self.assertEqual(status, 201)
        spending_id = response["id"]
        state = self.send("/api/state")[1]["rss"]
        self.assertEqual(state["resources"]["ammo"]["current"], 750)
        self.assertEqual(state["spending"][0]["note"], "Alliance research")
        self.assertTrue(state["spending"][0]["included"])
        self.assertEqual(self.send("/api/rss/spending", "POST", {**entry, "amount": 900}, cookie, csrf)[0], 400)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(self.send("/api/rss/spending", "POST", {**entry, "spent_at": future}, cookie, csrf)[0], 400)
        self.assertEqual(self.send("/api/rss/spending/" + str(spending_id), "DELETE")[0], 403)
        self.assertEqual(self.send("/api/rss/spending/" + str(spending_id), "DELETE", cookie=cookie, csrf=csrf)[0], 200)
        self.assertEqual(self.send("/api/state")[1]["rss"]["resources"]["ammo"]["current"], 1000)

    def test_spending_history_is_not_counted_twice_after_manual_balance_reset(self):
        cookie, csrf = self.login()
        payload = self.payload()
        payload["resources"]["ammo"] = {"stored": 1000, "per_hour": 0, "limit": 1200000}
        self.assertEqual(self.send("/api/rss", "PUT", payload, cookie, csrf)[0], 200)
        spent_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(self.send("/api/rss/spending", "POST", {
            "resource": "ammo", "amount": 200, "spent_at": spent_at, "note": ""
        }, cookie, csrf)[0], 201)
        reset = self.payload()
        reset["resources"]["ammo"] = {"stored": 800, "per_hour": 0, "limit": 1200000}
        self.assertEqual(self.send("/api/rss", "PUT", reset, cookie, csrf)[0], 200)
        state = self.send("/api/state")[1]["rss"]
        self.assertEqual(state["resources"]["ammo"]["current"], 800)
        self.assertEqual(len(state["spending"]), 1)

    def test_missing_balance_cannot_be_spent(self):
        cookie, csrf = self.login()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(self.send("/api/rss/spending", "POST", {
            "resource": "ammo", "amount": 5, "spent_at": now
        }, cookie, csrf)[0], 400)

    def test_research_deadline_survives_unrelated_resource_edits(self):
        cookie, csrf = self.login()
        payload = self.payload()
        payload["tech_stage"] = "Last Research (5/5)"
        payload["tech_remaining"] = "01:45:00"
        self.assertEqual(self.send("/api/rss", "PUT", payload, cookie, csrf)[0], 200)
        first = self.send("/api/state")[1]["rss"]
        end = datetime.fromisoformat(first["tech_ends_at"])
        duration = (end - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(duration, 6295)
        self.assertLessEqual(duration, 6300)
        self.assertEqual(first["tech_stage"], "Last Research (5/5)")
        payload.pop("tech_remaining")
        payload["revision"] = first["updated_at"]
        payload["resources"]["ammo"]["stored"] = 20000
        payload["resources"]["ammo"]["per_hour"] = 0
        self.assertEqual(self.send("/api/rss", "PUT", payload, cookie, csrf)[0], 200)
        updated = self.send("/api/state")[1]["rss"]
        self.assertEqual(updated["tech_ends_at"], first["tech_ends_at"])
        self.assertEqual(updated["resources"]["ammo"]["current"], 20000)

    def test_stale_admin_edit_is_rejected(self):
        cookie, csrf = self.login()
        first = self.payload()
        self.assertEqual(self.send("/api/rss", "PUT", first, cookie, csrf)[0], 200)
        old = self.send("/api/state")[1]["rss"]["updated_at"]
        changed = self.payload()
        changed["resources"]["ammo"]["stored"] = 5000
        changed["resources"]["ammo"]["per_hour"] = 0
        changed["revision"] = old
        self.assertEqual(self.send("/api/rss", "PUT", changed, cookie, csrf)[0], 200)
        stale = self.payload()
        stale["resources"]["ammo"]["stored"] = 9999
        stale["revision"] = old
        self.assertEqual(self.send("/api/rss", "PUT", stale, cookie, csrf)[0], 409)
        self.assertEqual(self.send("/api/state")[1]["rss"]["resources"]["ammo"]["current"], 5000)

    def test_resource_limits_are_adjustable_and_validated(self):
        cookie, csrf = self.login()
        payload = self.payload()
        payload["resources"]["ammo"] = {"stored": 900, "per_hour": 3600, "limit": 1000}
        self.assertEqual(self.send("/api/rss", "PUT", payload, cookie, csrf)[0], 200)
        state = self.send("/api/state")[1]["rss"]
        self.assertEqual(state["resources"]["ammo"]["limit"], 1000)
        self.assertLessEqual(state["resources"]["ammo"]["current"], 1000)
        bad = self.payload()
        bad["resources"]["ammo"] = {"stored": 1200, "per_hour": 3600, "limit": 1000}
        self.assertEqual(self.send("/api/rss", "PUT", bad, cookie, csrf)[0], 400)

    def test_legacy_editor_request_still_works(self):
        cookie, csrf = self.login()
        status, _, _ = self.send("/api/rss", "PUT",
                                 {"rss_hour": "500000", "tech_plan": "Flag expansion"}, cookie, csrf)
        self.assertEqual(status, 200)
        state = self.send("/api/state")[1]["rss"]
        self.assertEqual(state["legacy_hour"], "500000")
        self.assertEqual(state["tech_plan"], "Flag expansion")


if __name__ == "__main__":
    unittest.main()
