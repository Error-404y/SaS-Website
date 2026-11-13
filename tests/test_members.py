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


    def test_password_reset_approved_single_use_and_revokes_sessions(self):
        with server.connect() as db:
            members.register(db, {"username": "RecoverMe", "player_name": "Recover Player",
                                  "email": "recover@example.com", "password": "previous-password-123"})
            row = db.execute("SELECT * FROM members WHERE username='RecoverMe'").fetchone()
            db.execute("UPDATE members SET status='approved' WHERE id=?", (row["id"],))
            members.new_session(db, row["id"])
            members.request_password_reset(db, "recover@example.com")
            request = db.execute("SELECT * FROM password_requests").fetchone()
            self.assertEqual(request["status"], "pending")
            code = members.review_password_request(db, request["id"], "approved")
            self.assertNotEqual(code, db.execute("SELECT code_hash FROM password_requests").fetchone()[0])
            with self.assertRaises(ValueError):
                members.complete_password_reset(db, "RecoverMe", "wrong-code", "next-password-123")
            members.complete_password_reset(db, "RecoverMe", code, "next-password-123")
            changed = db.execute("SELECT password_hash FROM members WHERE id=?", (row["id"],)).fetchone()[0]
            self.assertTrue(members.check_password("next-password-123", changed))
            self.assertFalse(members.check_password("previous-password-123", changed))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM member_sessions").fetchone()[0], 0)
            with self.assertRaises(ValueError):
                members.complete_password_reset(db, "RecoverMe", code, "newer-password-123")

    def test_reviewed_reset_request_visible_for_48_hours_only(self):
        import time
        with server.connect() as db:
            members.register(db, {"username": "TimeKeeper", "player_name": "Time Player",
                                  "email": "time@example.com", "password": "longer-password-123"})
            members.request_password_reset(db, "TimeKeeper")
            req_id = db.execute("SELECT id FROM password_requests").fetchone()[0]
            self.assertEqual(len(members.list_password_requests(db)), 1)
            code = members.review_password_request(db, req_id, "approved")
            self.assertTrue(code)
            self.assertEqual(len(members.list_password_requests(db)), 1)
            db.execute("UPDATE password_requests SET reviewed_at=? WHERE id=?",
                       (int(time.time()) - 47 * 3600, req_id))
            self.assertEqual(len(members.list_password_requests(db)), 1)
            db.execute("UPDATE password_requests SET reviewed_at=? WHERE id=?",
                       (int(time.time()) - 49 * 3600, req_id))
            self.assertEqual(members.list_password_requests(db), [])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM password_requests").fetchone()[0], 1)
            # The code security expiry is independent of admin list visibility.
            with self.assertRaises(ValueError):
                members.complete_password_reset(db, "TimeKeeper", "not-the-code", "new-secret-password-123")

    def test_reset_lookup_supports_username_email_ingame_and_avoids_ambiguous_names(self):
        with server.connect() as db:
            members.register(db, {"username": "ZER", "player_name": "OgX",
                                  "email": "zer@example.com", "password": "old-password-long-1"})
            members.request_password_reset(db, "OgX")
            row = db.execute("SELECT id FROM password_requests WHERE status='pending'").fetchone()
            self.assertIsNotNone(row)
            code = members.review_password_request(db, row["id"], "approved")
            members.complete_password_reset(db, "zer@example.com", code, "new-password-long-1")
            updated = db.execute("SELECT password_hash FROM members WHERE username='ZER'").fetchone()[0]
            self.assertTrue(members.check_password("new-password-long-1", updated))
            # The same ingame nickname may appear on multiple accounts; do not guess.
            members.register(db, {"username": "SecondZER", "player_name": "OgX",
                                  "email": "second@example.com", "password": "another-password-1"})
            before = db.execute("SELECT COUNT(*) FROM password_requests").fetchone()[0]
            result = members.request_password_reset(db, "OgX")
            self.assertIn("If the account exists", result["message"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM password_requests").fetchone()[0], before)
            members.request_password_reset(db, "SecondZER")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM password_requests").fetchone()[0], before + 1)

    def test_reset_requests_are_limited_and_rejection_requires_reason(self):
        with server.connect() as db:
            members.register(db, {"username": "RejectMe", "player_name": "Test Player",
                                  "email": "reject@example.com", "password": "previous-password-123"})
            generic = members.request_password_reset(db, "unknown@example.com")
            self.assertIn("submitted", generic["message"])
            members.request_password_reset(db, "RejectMe")
            members.request_password_reset(db, "RejectMe")
            requests = db.execute("SELECT * FROM password_requests").fetchall()
            self.assertEqual(len(requests), 1)
            with self.assertRaises(ValueError):
                members.review_password_request(db, requests[0]["id"], "rejected", "")
            self.assertIsNone(members.review_password_request(db, requests[0]["id"], "rejected", "Could not verify identity"))
            with self.assertRaises(ValueError):
                members.review_password_request(db, requests[0]["id"], "approved")


if __name__ == "__main__":
    unittest.main()
