"""Test PNG reminder output, posting and expiry/restart behavior without Discord access."""
import io
import json
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import reminder_cards
import server

TEST_URL = "https://discord.com/api/webhooks/123456789/FakeTestWebhookToken"

class ReminderCardTests(unittest.TestCase):
    def test_visual_card_is_png_and_varies_by_stage(self):
        yellow = reminder_cards.make_card("Port Inspection", "2030-01-01 18:00:00", "yellow")
        red = reminder_cards.make_card("Port Inspection", "2030-01-01 18:00:00", "red")
        self.assertTrue(yellow.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertNotEqual(yellow, red)
        from PIL import Image
        img = Image.open(io.BytesIO(yellow))
        self.assertEqual(img.size, (1080, 360))
        with self.assertRaises(ValueError):
            reminder_cards.make_card("Test", "2030-01-01", "invalid")

    def test_send_embeds_a_new_image_per_event_and_uses_wait_true(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self, *a): return b'{"id":"987654321"}'
        with patch.object(reminder_cards.urllib.request, "urlopen", return_value=Response()) as send:
            self.assertEqual(reminder_cards.send_card(TEST_URL, "Port Inspection",
                "2030-01-01 18:00:00", "yellow"), "987654321")
            request = send.call_args.args[0]
            self.assertIn("?wait=true", request.full_url)
            self.assertIn(b"reminder.png", request.data)
            self.assertIn(b"\x89PNG\r\n\x1a\n", request.data)
            self.assertNotIn(b"@everyone", request.data)
            self.assertEqual(reminder_cards.send_card(TEST_URL, "Port Inspection",
                "2030-01-01 18:00:00", "red"), "987654321")
            self.assertIn(b"@everyone", send.call_args.args[0].data)

    def test_delete_can_remove_existing_message_and_treat_404_as_deleted(self):
        from urllib.error import HTTPError
        with patch.object(reminder_cards.urllib.request,"urlopen") as call:
            call.return_value.__enter__.return_value.status = 204
            self.assertTrue(reminder_cards.delete_card(TEST_URL, "23456789"))
        with patch.object(reminder_cards.urllib.request,"urlopen",
                          side_effect=HTTPError(TEST_URL, 404, "Not found", {}, None)):
            self.assertTrue(reminder_cards.delete_card(TEST_URL,"23456789"))
        with self.assertRaises(ValueError):
            reminder_cards.message_url(TEST_URL,"../bad")

    def test_edit_card_updates_existing_discord_message_without_reping(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def read(self, *a): return b'{"id":"987654321"}'
        now = int(datetime(2030,1,1,17,8,0,tzinfo=timezone.utc).timestamp())
        with patch.object(reminder_cards.urllib.request,"urlopen",return_value=Response()) as call:
            self.assertTrue(reminder_cards.edit_card(TEST_URL,"987654321",
                "Vault Trap 1","2030-01-01 18:00:00","red",now_epoch=now))
            request=call.call_args.args[0]
            self.assertEqual(request.get_method(),"PATCH")
            self.assertEqual(request.full_url,reminder_cards.message_url(TEST_URL,"987654321"))
            self.assertIn(b"reminder-"+str(now).encode()+b".png",request.data)
            self.assertIn(b"attachment://reminder-",request.data)
            self.assertIn(b"files[0]",request.data)
            self.assertIn(b"payload_json",request.data)
            self.assertIn(b"\x89PNG\r\n\x1a\n",request.data)
            self.assertNotIn(b"@everyone",request.data)
            # Discord must discard old PNG attachments, not grow the message
            # by one more attachment every single minute.
            payload=json.loads(request.data.split(b"\r\n\r\n",1)[1].split(
                b"\r\n--",1)[0])
            self.assertEqual(payload["allowed_mentions"],{"parse":[]})
            self.assertEqual(payload["attachments"][0]["id"],0)
            self.assertEqual(len(payload["attachments"]),1)
            self.assertNotIn("content",payload)
        # The countdown visibly changes when a minute elapses, and at zero.
        image1=reminder_cards.make_card("Vault Trap 1","2030-01-01 18:00:00",
                                        "red",remaining_seconds=52*60)
        image2=reminder_cards.make_card("Vault Trap 1","2030-01-01 18:00:00",
                                        "red",remaining_seconds=51*60)
        started=reminder_cards.make_card("Vault Trap 1","2030-01-01 18:00:00",
                                         "red",remaining_seconds=0)
        self.assertNotEqual(image1,image2)
        self.assertNotEqual(image2,started)

class ReminderScheduleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(server,"DB",Path(self.tmp.name)/"test.sqlite")
        self.webhook_patch = patch.object(server,"WEBHOOK",TEST_URL)
        self.db_patch.start(); self.webhook_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.webhook_patch.stop)
        server.init()
        self.start = int(datetime(2030,1,1,18,0,0,tzinfo=timezone.utc).timestamp())
        with server.connect() as db:
            cur=db.execute("""INSERT INTO entries(kind,title,category,start_utc,end_utc,created_at)
                VALUES('events','Port Inspection','Events','2030-01-01 18:00:00',
                '2030-01-01 20:00:00','2030-01-01T00:00:00+00:00')""")
            self.event_id=cur.lastrowid

    def test_schedule_send_cleanup_duplicate_prevention_and_restart(self):
        with patch.object(server.reminder_cards,"send_card",side_effect=["111111","222222"]) as send, \
             patch.object(server.reminder_cards,"delete_card",return_value=True) as delete:
            t0=self.start-7200
            self.assertTrue(server.reminder_send_once(t0))
            self.assertFalse(server.reminder_send_once(t0+30))
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args_list[0].args[-1],"yellow")
            server.reminder_cleanup_once(t0+2999)
            delete.assert_not_called()
            server.reminder_cleanup_once(t0+3000)
            self.assertEqual(delete.call_args.args[-1],"111111")
            self.assertTrue(server.reminder_send_once(self.start-3600))
            self.assertEqual(send.call_args_list[1].args[-1],"red")
            self.assertFalse(server.reminder_send_once(self.start-3550))
            server.reminder_cleanup_once(self.start-3600+86399)
            self.assertEqual(delete.call_count,1)
            server.reminder_cleanup_once(self.start-3600+86400)
            self.assertEqual(delete.call_count,2)
            with server.connect() as db:
                records=db.execute("SELECT stage,message_id,deleted_at FROM reminder_messages ORDER BY stage").fetchall()
            self.assertEqual(len(records),2)
            self.assertTrue(all(row["deleted_at"] for row in records))

    def test_all_events_refresh_every_minute_with_existing_discord_ids(self):
        # Every event type, not just Vault Trap, gets a ticking yellow/red card.
        with server.connect() as db:
            db.execute("""INSERT INTO entries(kind,title,category,start_utc,end_utc,created_at)
                VALUES('alliance','Mafia Attack','Events','2030-01-01 18:00:00',
                '2030-01-01 20:00:00','2030-01-01T00:00:00+00:00')""")
        ids=iter(["111111","222222","333333","444444"])
        with patch.object(server.reminder_cards,"send_card",side_effect=lambda *_:next(ids)),\
             patch.object(server.reminder_cards,"edit_card",return_value=True) as edit,\
             patch.object(server.time,"sleep") as sleep:
            t0=self.start-7200
            self.assertTrue(server.reminder_send_once(t0))
            self.assertTrue(server.reminder_send_once(t0))
            self.assertEqual(server.reminder_refresh_once(t0+30),0)
            self.assertEqual(server.reminder_refresh_once(t0+60),2)
            self.assertEqual({args.args[1] for args in edit.call_args_list},
                             {"111111","222222"})
            self.assertEqual({args.args[4] for args in edit.call_args_list},{"yellow"})
            self.assertEqual(server.reminder_refresh_once(t0+85),0)
            self.assertEqual(server.reminder_refresh_once(t0+120),2)
            self.assertEqual(edit.call_count,4)
            # Red stage begins one hour before the exact same event start.
            self.assertTrue(server.reminder_send_once(self.start-3600))
            self.assertTrue(server.reminder_send_once(self.start-3600))
            self.assertEqual(server.reminder_refresh_once(self.start-3540),2)
            self.assertEqual({args.args[4] for args in edit.call_args_list[-2:]},{"red"})
            self.assertEqual({args.args[1] for args in edit.call_args_list[-2:]},
                             {"333333","444444"})
            # Final edit at the event start displays "Event Started" exactly
            # once. The red reminder stays visible until normal expiry.
            self.assertEqual(server.reminder_refresh_once(self.start),2)
            self.assertEqual(server.reminder_refresh_once(self.start+120),0)
            self.assertEqual(edit.call_count,8)
            with server.connect() as db:
                rows=db.execute("SELECT stage,message_id,refresh_at FROM reminder_messages").fetchall()
                self.assertEqual(len(rows),4)
                self.assertEqual(sum(row["refresh_at"]==self.start for row in rows),2)
            self.assertEqual(sleep.call_count,4)
            
    def test_deployment_migrates_existing_reminders_and_refreshes_them(self):
        # Older databases contain no refresh fields; the message ID survives.
        t0=self.start-3600
        with server.connect() as db:
            db.execute("DROP TABLE reminder_messages")
            db.execute("""CREATE TABLE reminder_messages (
                event_id INTEGER NOT NULL,stage TEXT NOT NULL,
                event_start_utc TEXT NOT NULL,message_id TEXT NOT NULL DEFAULT '',
                sent_at INTEGER NOT NULL DEFAULT 0,attempt_at INTEGER NOT NULL DEFAULT 0,
                deleted_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(event_id,stage,event_start_utc))""")
            db.execute("""INSERT INTO reminder_messages
                (event_id,stage,event_start_utc,message_id,sent_at)
                VALUES(?,?,?,?,?)""",
                (self.event_id,"red","2030-01-01 18:00:00","556677",t0))
        server.init()
        with server.connect() as db:
            row=db.execute("SELECT * FROM reminder_messages").fetchone()
            self.assertEqual(row["message_id"],"556677")
            self.assertEqual(row["refresh_at"],0)
            self.assertEqual(row["refresh_attempt_at"],0)
        with patch.object(server.reminder_cards,"edit_card",return_value=True) as edit:
            self.assertEqual(server.reminder_refresh_once(t0+120),1)
            self.assertEqual(edit.call_args.args[1],"556677")

    def test_failed_refresh_retries_without_duplicate_posts(self):
        t0=self.start-3600
        with patch.object(server.reminder_cards,"send_card",return_value="556677") as send:
            self.assertTrue(server.reminder_send_once(t0))
        with patch.object(server.reminder_cards,"edit_card",side_effect=[
            TimeoutError("Discord unavailable"),True]) as edit:
            self.assertEqual(server.reminder_refresh_once(t0+60),0)
            self.assertEqual(server.reminder_refresh_once(t0+85),0)
            self.assertEqual(server.reminder_refresh_once(t0+151),1)
            self.assertEqual(edit.call_count,2)
        self.assertEqual(send.call_count,1)

    def test_editing_event_time_prevents_stale_countdown(self):
        t0=self.start-3600
        with patch.object(server.reminder_cards,"send_card",return_value="556677"):
            self.assertTrue(server.reminder_send_once(t0))
        with server.connect() as db:
            db.execute("UPDATE entries SET start_utc=? WHERE id=?",
                       ("2030-01-01 21:00:00",self.event_id))
        with patch.object(server.reminder_cards,"edit_card") as edit,\
             patch.object(server.reminder_cards,"delete_card",return_value=True) as delete:
            self.assertEqual(server.reminder_refresh_once(t0+70),0)
            edit.assert_not_called()
            server.reminder_cleanup_once(t0+70)
            delete.assert_called_once()

    def test_missing_discord_message_stops_retrying(self):
        from urllib.error import HTTPError
        t0=self.start-3600
        with patch.object(server.reminder_cards,"send_card",return_value="556677"):
            self.assertTrue(server.reminder_send_once(t0))
        with patch.object(server.reminder_cards,"edit_card",
             side_effect=HTTPError(TEST_URL,404,"not found",{},None)) as edit:
            self.assertEqual(server.reminder_refresh_once(t0+60),0)
            self.assertEqual(server.reminder_refresh_once(t0+200),0)
            self.assertEqual(edit.call_count,1)
        with server.connect() as db:
            self.assertGreater(db.execute(
                "SELECT deleted_at FROM reminder_messages WHERE stage='red'").fetchone()[0],0)

    def test_missing_window_is_not_sent_late(self):
        with patch.object(server.reminder_cards,"send_card") as send:
            self.assertFalse(server.reminder_send_once(self.start-5800))
            self.assertFalse(server.reminder_send_once(self.start-2800))
            send.assert_not_called()

    def test_event_removal_cleans_persisted_card(self):
        with patch.object(server.reminder_cards,"send_card",return_value="987654321"), \
             patch.object(server.reminder_cards,"delete_card",return_value=True) as delete:
            self.assertTrue(server.reminder_send_once(self.start-7200))
            with server.connect() as db:
                db.execute("DELETE FROM entries WHERE id=?",(self.event_id,))
            server.reminder_cleanup_once(self.start-7000)
            delete.assert_called_once()
