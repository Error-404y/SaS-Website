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
