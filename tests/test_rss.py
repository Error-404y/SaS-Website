import json
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
