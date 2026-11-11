import tempfile
import unittest
from pathlib import Path

import server


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = server.DB
        server.DB = Path(self.tmp.name) / "test.sqlite3"
        server.init()

    def tearDown(self):
        server.DB = self.previous
        self.tmp.cleanup()

    def test_sections_are_separate(self):
        state = server.get_state()
        self.assertEqual(len([item for item in state["entries"] if item["kind"] == "events"]), 8)
        self.assertEqual(len([item for item in state["entries"] if item["kind"] == "alliance"]), 0)
        self.assertEqual(state["settings"]["rss_hour"], "")

    def test_seed_is_only_inserted_once(self):
        server.init()
        self.assertEqual(len(server.get_state()["entries"]), 8)

    def test_utc_validation(self):
        row = {
            "kind": "events",
            "title": "New event",
            "category": "Events",
            "start_utc": "2026-11-10 00:00:00",
            "end_utc": "2026-11-12 23:59:59"
        }
        result = server.validate_entry(row)
        self.assertEqual(result[3], row["start_utc"])
        with self.assertRaises(ValueError):
            server.validate_entry({**row, "end_utc": "2026-11-09 00:00:00"})
        with self.assertRaises(ValueError):
            server.validate_entry({**row, "start_utc": "2026-11-31 00:00:00"})

    def test_announcements_are_attributed_to_r4_r5(self):
        self.assertEqual(server.validate_entry({"kind": "announcements", "title": "News", "author": "R5"})[-1], "R5")
        with self.assertRaises(ValueError):
            server.validate_entry({"kind": "announcements", "title": "News", "author": "R3"})

    def test_webhook_validation(self):
        self.assertTrue(server.webhook_valid("https://discord.com/api/webhooks/12345/validToken_abc"))
        self.assertFalse(server.webhook_valid("https://evil.example/api/webhooks/12345/validToken_abc"))
        self.assertFalse(server.webhook_valid("http://discord.com/api/webhooks/12345/validToken_abc"))


if __name__ == "__main__":
    unittest.main()
