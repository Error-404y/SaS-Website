import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import members
import server


class MemberAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = server.DB
        server.DB = Path(self.temp.name) / "accounts.sqlite3"
        server.init()

    def tearDown(self):
        server.DB = self.previous
        self.temp.cleanup()

    def test_database_is_persistent_and_registration_starts_pending(self):
        with server.connect() as db:
            members.register(db, {"username": "TestPlayer", "player_name": "SaS Member",
                                  "email": "player@example.com", "password": "long-safe-password"})
        server.init()
        with server.connect() as db:
            row = db.execute("SELECT * FROM members WHERE username='TestPlayer'").fetchone()
            self.assertEqual(row["status"], "pending")
            self.assertNotIn("long-safe-password", row["password_hash"])
            self.assertTrue(members.check_password("long-safe-password", row["password_hash"]))
            self.assertFalse(members.check_password("bad-password", row["password_hash"]))
            with self.assertRaises(ValueError):
                members.register(db, {"username": "testplayer", "player_name": "Different",
                                      "email": "other@example.com", "password": "another-long-password"})

    def test_sessions_are_revocable_and_salted(self):
        with server.connect() as db:
            members.register(db, {"username": "Tester", "player_name": "Tester",
                                  "email": "tester@example.com", "password": "unique-safe-password"})
            member_id = db.execute("SELECT id FROM members").fetchone()[0]
            db.execute("UPDATE members SET status='approved' WHERE id=?", (member_id,))
            token, csrf = members.new_session(db, member_id)
        handler = SimpleNamespace(headers={"Cookie": "sas_member=" + token})
        record = members.member_session(handler, server.connect, threading.RLock())
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["csrf"], csrf)
        with server.connect() as db:
            db.execute("UPDATE members SET status='rejected',review_message='Not in the alliance' WHERE id=?", (member_id,))
            db.execute("DELETE FROM member_sessions WHERE member_id=?", (member_id,))
        self.assertIsNone(members.member_session(handler, server.connect, threading.RLock()))


if __name__ == "__main__":
    unittest.main()
