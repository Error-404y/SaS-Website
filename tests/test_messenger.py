"""Security and behavior tests for SaS Messenger, including private thread isolation."""
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import members
import messenger
import server


class MessengerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.before_db, self.before_password, self.before_cookie = (
            server.DB, server.ADMIN_PASSWORD, server.COOKIE_SECURE)
        server.DB = Path(self.folder.name) / "messages.sqlite3"
        server.ADMIN_PASSWORD = "admin-test-secret-long"
        server.COOKIE_SECURE = False
        server.init()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"
        for name,status in [("Alpha","approved"),("Bravo","approved"),
                            ("Charlie","approved"),("Pending","pending"),
                            ("Rejected","rejected")]:
            with server.connect() as db:
                members.register(db, {"username":name,"player_name":name+" Game",
                    "email":name.lower()+"@example.com","password":"long-member-secret-1"})
                db.execute("UPDATE members SET status=? WHERE username=?", (status,name))

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join(timeout=5)
        server.DB, server.ADMIN_PASSWORD, server.COOKIE_SECURE = (
            self.before_db, self.before_password, self.before_cookie)
        self.folder.cleanup()

    def call(self, path, method="GET", body=None, cookie=None, csrf=None):
        h={}
        if body is not None: h["Content-Type"]="application/json"
        if cookie: h["Cookie"]=cookie
        if csrf: h["X-CSRF-Token"]=csrf
        request=Request(self.base+path, headers=h,method=method,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(request,timeout=6) as response:
                return response.status,json.loads(response.read())
        except HTTPError as exc:
            return exc.code,json.loads(exc.read())

    def login(self,name):
        status,data=self.call("/api/member/login","POST",{
            "username":name,"password":"long-member-secret-1"})
        self.assertEqual(status,200)
        # Fetch cookie via an explicit call to retain urllib response headers.
        # It is easier to use a direct member session issued by the database for tests.
        with server.connect() as db:
            row=db.execute("SELECT id FROM members WHERE username=?",(name,)).fetchone()
            token,csrf=members.new_session(db,row["id"])
        return "sas_member="+token,csrf, messenger.member_key(row["id"])

    def login_admin(self):
        with server.connect() as db:
            import hashlib,secrets,time
            token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
            now=int(time.time())
            db.execute("INSERT INTO sessions(token_hash,csrf,expires_at,last_activity_at) VALUES(?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(),csrf,now+43200,now))
        return "sas_session="+token,csrf

    def test_guest_pending_rejected_cannot_read_or_send(self):
        for path in ("/api/messenger","/api/messenger/messages?peer=alliance"):
            self.assertEqual(self.call(path)[0],401)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":"alliance","body":"hi"})[0],401)
        for name in ("Pending","Rejected"):
            with server.connect() as db:
                row=db.execute("SELECT id FROM members WHERE username=?",(name,)).fetchone()
                token,csrf=members.new_session(db,row["id"])
            cookie="sas_member="+token
            self.assertEqual(self.call("/api/messenger",cookie=cookie)[0],401)
            self.assertEqual(self.call("/api/messenger/messages","POST",
                {"peer":"alliance","body":"hi"},cookie,csrf)[0],401)

    def test_private_messages_are_isolated_and_unread_clear_only_when_read(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        c,cc,cid=self.login("Charlie")
        status,data=self.call("/api/messenger",cookie=a)
        self.assertEqual(status,200)
        self.assertFalse(any("email" in item for item in data["contacts"]))
        self.assertNotIn("Pending",json.dumps(data))
        self.assertNotIn("Rejected",json.dumps(data))
        self.assertEqual(data["unread"],0)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":bid,"body":"Secret for Bravo","sender_key":cid},a)[0],403)
        status,data=self.call("/api/messenger/messages","POST",
            {"peer":bid,"body":"Secret for Bravo","sender_key":cid},a,ac)
        self.assertEqual(status,201)
        self.assertEqual(data["message"]["sender_key"],aid)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["messages"][0]["body"],
            "Secret for Bravo")
        self.assertEqual(self.call("/api/messenger",cookie=b)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger",cookie=c)[1]["unread"],0)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=c)[1]["messages"],[])
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":aid},b)[0],403)
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":aid},b,bc)[0],200)
        self.assertEqual(self.call("/api/messenger",cookie=b)[1]["unread"],0)

    def test_alliance_group_and_admin_conversation(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        admin,adcsrf=self.login_admin()
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"SvS soon"},admin,adcsrf)[0],201)
        self.assertEqual(self.call("/api/messenger",cookie=a)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger/messages?peer=alliance",cookie=b)[1]["messages"][0]["body"],"SvS soon")
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":"alliance"},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger",cookie=a)[1]["unread"],0)
        self.assertEqual(self.call("/api/messenger",cookie=b)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"admin","body":"Hello admin"},a,ac)[0],201)
        self.assertEqual(self.call("/api/messenger",cookie=admin)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=admin)[1]["messages"][0]["body"],"Hello admin")

    def test_validation_and_account_deletion(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        admin,adcsrf=self.login_admin()
        for peer in ("member:999999","member:0","member:bad",aid):
            self.assertIn(self.call("/api/messenger/messages","POST",
                {"peer":peer,"body":"test"},a,ac)[0],(400,))
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":bid,"body":"  "},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":bid,"body":"x"*2001},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":bid,"body":"<script>attack</script>"},a,ac)[0],201)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":"alliance","body":"Group"},
            a,ac)[0],201)
        self.assertEqual(self.call("/api/accounts/"+bid[7:],"DELETE",cookie=admin,csrf=adcsrf)[0],200)
        self.assertEqual(self.call("/api/messenger/messages?peer="+bid,cookie=a)[0],404)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chat_messages WHERE thread_key LIKE 'dm:%'").fetchone()[0],0)
            sender=db.execute("SELECT sender_key FROM chat_messages WHERE thread_key='alliance'").fetchone()[0]
        self.assertEqual(sender,aid)
        self.assertEqual(self.call("/api/messenger",cookie=b)[0],401)

    def test_chat_rate_limit_blocks_bulk_spam(self):
        a,ac,aid=self.login("Alpha")
        for i in range(30):
            self.assertEqual(self.call("/api/messenger/messages","POST",
                {"peer":"alliance","body":"Message "+str(i)},a,ac)[0],201)
        status,data=self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"Excess"},a,ac)
        self.assertEqual(status,400)
        self.assertIn("Too many messages",data["error"])

    def test_maintenance_switch_blocks_all_chat_apis(self):
        old=server.MAINTENANCE_MODE
        server.MAINTENANCE_MODE=True
        self.addCleanup(setattr,server,"MAINTENANCE_MODE",old)
        self.assertEqual(self.call("/api/messenger")[0],503)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":"alliance","body":"test"})[0],503)


if __name__=="__main__":
    unittest.main()
