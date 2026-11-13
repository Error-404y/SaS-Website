"""Delayed moderation ban behavior: 2h queue, cancel, active restrictions, shared IP."""
import tempfile
import unittest
from pathlib import Path
import sqlite3

import ban_system
import members


class BanStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=sqlite3.connect(Path(self.temp.name)/"ban.sqlite")
        self.db.row_factory=sqlite3.Row
        self.addCleanup(self.db.close)
        members.setup(self.db)
        ban_system.setup(self.db)
        for name in ["Alpha","Bravo"]:
            members.register(self.db,{"username":name,"player_name":name+"Chief",
                "email":name.lower()+"@test.example","password":"member-secret-password"})
        self.alpha=self.db.execute("SELECT id FROM members WHERE username='Alpha'").fetchone()[0]
        self.bravo=self.db.execute("SELECT id FROM members WHERE username='Bravo'").fetchone()[0]
        ban_system.record_ip(self.db,self.alpha,"198.51.100.10")
        ban_system.record_ip(self.db,self.bravo,"198.51.100.11")

    def test_queue_waits_two_hours_before_enforcement_and_can_be_cancelled(self):
        now=100000
        bid=ban_system.queue(self.db,self.alpha,"everything","Test reason",now=now)
        self.assertFalse(ban_system.is_banned(self.db,email="alpha@test.example",now=now+7199))
        self.assertFalse(ban_system.is_banned(self.db,ip="198.51.100.10",now=now+7199))
        self.assertEqual(ban_system.list_bans(self.db,now)[0]["status"],"pending")
        self.assertTrue(ban_system.stop(self.db,bid,now=now+7199))
        self.assertFalse(ban_system.is_banned(self.db,email="alpha@test.example",now=now+7201))
        self.assertEqual(ban_system.list_bans(self.db,now+7201)[0]["status"],"cancelled")

    def test_each_type_only_enforces_matching_selector(self):
        now=200000
        bid=ban_system.queue(self.db,self.alpha,"email",now=now)
        self.assertFalse(ban_system.is_banned(self.db,email="alpha@test.example",now=now+7199))
        self.assertTrue(ban_system.is_banned(self.db,email="ALPHA@Test.Example",now=now+7200))
        self.assertFalse(ban_system.is_banned(self.db,ip="198.51.100.10",now=now+7200))
        self.assertTrue(ban_system.stop(self.db,bid,now=now+7201) is False)
        self.assertFalse(ban_system.is_banned(self.db,email="alpha@test.example",now=now+7202))
        ban_system.queue(self.db,self.alpha,"name",now=now)
        self.assertTrue(ban_system.is_banned(self.db,username="ALPHA",now=now+7200))
        self.assertTrue(ban_system.is_banned(self.db,player_name="AlphaChief",now=now+7200))
        self.assertFalse(ban_system.is_banned(self.db,username="Bravo",now=now+7200))

    def test_ip_bans_can_affect_multiple_members_on_shared_address(self):
        now=300000
        ban_system.queue(self.db,self.alpha,"ip",now=now)
        self.assertTrue(ban_system.is_banned(self.db,ip="198.51.100.10",now=now+7200))
        self.assertFalse(ban_system.is_banned(self.db,ip="198.51.100.11",now=now+7200))
        self.assertFalse(ban_system.is_banned(self.db,email="alpha@test.example",now=now+7200))

    def test_missing_ip_prevents_ip_or_everything(self):
        self.db.execute("DELETE FROM member_ips WHERE member_id=?",(self.alpha,))
        for kind in ["ip","everything"]:
            with self.assertRaisesRegex(ValueError,"No verified IP"):
                ban_system.queue(self.db,self.alpha,kind,now=100)
        self.assertIsInstance(ban_system.queue(self.db,self.alpha,"name",now=100),int)

    def test_requeue_restricted_until_cancelled_and_no_double_cancel(self):
        bid=ban_system.queue(self.db,self.alpha,"name",now=200)
        with self.assertRaisesRegex(ValueError,"already exists"):
            ban_system.queue(self.db,self.alpha,"name",now=201)
        self.assertTrue(ban_system.stop(self.db,bid,now=202))
        with self.assertRaisesRegex(ValueError,"already been"):
            ban_system.stop(self.db,bid,now=204)
        self.assertIsInstance(ban_system.queue(self.db,self.alpha,"name",now=205),int)

    def test_reject_invalid_ip_address_data(self):
        ban_system.record_ip(self.db,self.alpha,"forged")
        self.assertEqual(ban_system.member_ip(self.db,self.alpha),"198.51.100.10")
        self.assertEqual(ban_system.normalize_ip("fe80::1"),"fe80::1")
        self.assertEqual(ban_system.normalize_ip("1.1.1.1\n"),"")


if __name__=="__main__":
    unittest.main()
