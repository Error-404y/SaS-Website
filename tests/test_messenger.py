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

    def test_existing_approved_accounts_keep_access_on_first_migration(self):
        import sqlite3
        import pathlib
        with tempfile.TemporaryDirectory() as temp:
            db=sqlite3.connect(pathlib.Path(temp)/"migration.sqlite")
            db.row_factory=sqlite3.Row
            try:
                members.setup(db)
                members.register(db, {"username":"Existing","player_name":"Veteran",
                    "email":"existing@example.com","password":"long-password-123"})
                db.execute("UPDATE members SET status='approved' WHERE username='Existing'")
                existing=db.execute("SELECT id FROM members WHERE username='Existing'").fetchone()[0]
                messenger.setup(db)
                self.assertTrue(messenger.alliance_joined(db,messenger.member_key(existing)))
                members.register(db, {"username":"Fresh","player_name":"New Player",
                    "email":"fresh@example.com","password":"long-password-123"})
                db.execute("UPDATE members SET status='approved' WHERE username='Fresh'")
                fresh=db.execute("SELECT id FROM members WHERE username='Fresh'").fetchone()[0]
                self.assertFalse(messenger.alliance_joined(db,messenger.member_key(fresh)))
                messenger.setup(db)
                self.assertFalse(messenger.alliance_joined(db,messenger.member_key(fresh)))
            finally:
                db.close()

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

    def test_presence_heartbeat_is_authenticated_and_expires(self):
        import time
        a, ac, aid = self.login("Alpha")
        b, bc, bid = self.login("Bravo")
        self.assertEqual(self.call("/api/messenger/presence", "POST", {})[0], 401)
        self.assertEqual(self.call("/api/messenger/presence", "POST", {}, a)[0], 403)
        self.assertEqual(self.call("/api/messenger/presence", "POST", {}, a, ac)[0], 200)
        status, data = self.call("/api/messenger", cookie=b)
        self.assertEqual(status, 200)
        alpha = next(item for item in data["contacts"] if item["id"] == aid)
        self.assertTrue(alpha["online"])
        self.assertIsInstance(alpha["last_seen_at"], int)
        self.assertNotIn("online", next(item for item in data["contacts"] if item["group"]))
        with server.connect() as db:
            db.execute("UPDATE chat_presence SET last_seen_at=? WHERE member_key=?",
                       (int(time.time()) - messenger.PRESENCE_ONLINE_SECONDS - 10, aid))
        status, data = self.call("/api/messenger", cookie=b)
        alpha = next(item for item in data["contacts"] if item["id"] == aid)
        self.assertFalse(alpha["online"])
        self.assertIsInstance(alpha["last_seen_at"], int)
        self.assertEqual(self.call("/api/messenger/presence", "POST", {}, b, bc)[0], 200)
        self.assertEqual(self.call("/api/messenger/presence", "POST", {}, a, ac)[0], 200)
        self.assertTrue(next(item for item in self.call("/api/messenger", cookie=b)[1]["contacts"]
                             if item["id"] == aid)["online"])

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
        own = next(item for item in data["contacts"] if item["id"]==aid)
        self.assertTrue(own["self"])
        self.assertEqual(own["username"],"Alpha")
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

    def test_direct_message_read_ticks_only_after_recipient_marks_read(self):
        a, ac, aid = self.login("Alpha")
        b, bc, bid = self.login("Bravo")
        c, cc, cid = self.login("Charlie")
        status, data = self.call("/api/messenger/messages", "POST",
                                 {"peer": bid, "body": "Tick test"}, a, ac)
        self.assertEqual(status, 201)
        message_id = data["message"]["id"]
        sender_history = self.call("/api/messenger/messages?peer="+bid, cookie=a)[1]["messages"]
        self.assertEqual(sender_history[0]["id"], message_id)
        self.assertIs(sender_history[0]["read"], False)
        # Viewing the conversation list or polling messages is not a read receipt.
        self.call("/api/messenger", cookie=b)
        self.call("/api/messenger/messages?peer="+aid, cookie=b)
        self.assertIs(self.call("/api/messenger/messages?peer="+bid, cookie=a)[1]["messages"][0]["read"], False)
        self.assertEqual(self.call("/api/messenger/read", "POST", {"peer": aid}, b, bc)[0], 200)
        self.assertIs(self.call("/api/messenger/messages?peer="+bid, cookie=a)[1]["messages"][0]["read"], True)
        # Others cannot inspect this private conversation or its receipts.
        self.assertEqual(self.call("/api/messenger/messages?peer="+bid, cookie=c)[1]["messages"], [])
        # Reader must not be told sender-only receipt state.
        reader_history = self.call("/api/messenger/messages?peer="+aid, cookie=b)[1]["messages"]
        self.assertNotIn("read", reader_history[0])
        # Self notes and alliance messages must not claim to have recipients.
        self.call("/api/messenger/messages", "POST", {"peer": aid, "body": "Note"}, a, ac)
        self.assertNotIn("read", self.call("/api/messenger/messages?peer="+aid, cookie=a)[1]["messages"][0])
        # Newly approved accounts must explicitly join the alliance chat first.
        # Never bypass the membership gate just to inspect read receipts.
        self.assertEqual(self.call("/api/messenger/messages?peer=alliance", cookie=a)[0], 404)
        self.assertEqual(self.call("/api/messenger/alliance/join", "POST", {}, a, ac)[0], 200)
        self.assertEqual(self.call("/api/messenger/messages", "POST",
                                   {"peer": "alliance", "body": "Hi"}, a, ac)[0], 201)
        status, alliance = self.call("/api/messenger/messages?peer=alliance", cookie=a)
        self.assertEqual(status, 200)
        self.assertNotIn("read", alliance["messages"][-1])


    def test_rich_replies_edit_delete_and_authorization(self):
        a, ac, aid = self.login("Alpha")
        b, bc, bid = self.login("Bravo")
        c, cc, cid = self.login("Charlie")
        sent = self.call("/api/messenger/messages", "POST",
                         {"peer": bid, "body": "Original"}, a, ac)
        self.assertEqual(sent[0], 201, sent)
        msg = sent[1]["message"]["id"]
        self.assertEqual(self.call("/api/messenger/messages", "POST",
            {"peer": cid, "body": "Leaking reply", "reply_to": msg}, a, ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages", "POST",
            {"peer": aid, "body": "Reply", "reply_to": msg}, b, bc)[0],201)
        history = self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["messages"]
        self.assertEqual(history[-1]["reply"]["body"],"Original")
        self.assertEqual(self.call("/api/messenger/messages/edit", "POST",
            {"peer": aid, "id": msg, "body": "Unauthorized"}, b, bc)[0],403)
        self.assertEqual(self.call("/api/messenger/messages/edit", "POST",
            {"peer": bid, "id": msg, "body": "Changed"}, a, ac)[0],200)
        history = self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["messages"]
        self.assertEqual(history[0]["body"],"Changed")
        self.assertTrue(history[0]["edited_at"])
        self.assertEqual(self.call("/api/messenger/messages/delete", "POST",
            {"peer": bid, "id": msg}, a, ac)[0],200)
        history = self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["messages"]
        self.assertEqual(history[0]["kind"],"deleted")
        self.assertEqual(history[0]["body"],"")
        self.assertEqual(history[-1]["reply"]["body"],"Message deleted")
        self.assertEqual(self.call("/api/messenger/messages/edit", "POST",
            {"peer": bid, "id": msg, "body":"Restore"}, a, ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages/edit", "POST",
            {"peer": bid, "id": msg, "body":"X"}, a)[0],403)

    def test_rich_typing_indicator_scoped_by_conversation(self):
        a,ac,aid = self.login("Alpha")
        b,bc,bid = self.login("Bravo")
        c,cc,cid = self.login("Charlie")
        self.assertEqual(self.call("/api/messenger/typing","POST",
            {"peer":bid,"active":True},a)[0],403)
        self.assertEqual(self.call("/api/messenger/typing","POST",
            {"peer":bid,"active":True},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["typing"],
                         ["Alpha Game"])
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=c)[1]["typing"],[])
        self.assertEqual(self.call("/api/messenger/typing","POST",
            {"peer":bid,"active":False},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["typing"],[])
        self.assertEqual(self.call("/api/messenger/typing","POST",
            {"peer":"alliance","active":True},a,ac)[0],400)

    def test_rich_photo_is_private_and_deleted_media_unavailable(self):
        import base64, io
        from PIL import Image
        a,ac,aid = self.login("Alpha")
        b,bc,bid = self.login("Bravo")
        c,cc,cid = self.login("Charlie")
        im=Image.new("RGB",(12,12),(50,100,175))
        out=io.BytesIO()
        im.save(out,format="PNG")
        encoded=base64.b64encode(out.getvalue()).decode()
        self.assertEqual(self.call("/api/messenger/images","POST",
            {"peer":bid,"image":encoded,"caption":"Battle report"},a)[0],403)
        result=self.call("/api/messenger/images","POST",
            {"peer":bid,"image":encoded,"caption":"Battle report"},a,ac)
        self.assertEqual(result[0],201,result)
        mid=result[1]["message"]["id"]
        msg=self.call("/api/messenger/messages?peer="+aid,cookie=b)[1]["messages"][0]
        self.assertEqual(msg["kind"],"image")
        self.assertEqual(msg["body"],"Battle report")
        with urlopen(Request(self.base+"/api/messenger/images/"+str(mid)+"?peer="+aid,
                             headers={"Cookie":b}), timeout=6) as response:
            self.assertEqual(response.headers["Content-Type"],"image/webp")
            self.assertTrue(response.read().startswith(b"RIFF"))
        for cookie,peer in ((None,aid),(c,aid),(b,cid)):
            try:
                urlopen(Request(self.base+"/api/messenger/images/"+str(mid)+"?peer="+peer,
                                headers={"Cookie":cookie} if cookie else {}),timeout=6)
                self.fail("Image exposed outside authorized chat.")
            except HTTPError as exc:
                self.assertIn(exc.code,(401,404))
        self.assertEqual(self.call("/api/messenger/images","POST",
            {"peer":bid,"image":"not-base64"},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages/delete","POST",
            {"peer":bid,"id":mid},a,ac)[0],200)
        try:
            urlopen(Request(self.base+"/api/messenger/images/"+str(mid)+"?peer="+aid,
                            headers={"Cookie":b}),timeout=6)
            self.fail("Deleted image still accessible.")
        except HTTPError as exc:
            self.assertEqual(exc.code,404)

    def test_rich_poll_voting_and_mention_notifications(self):
        a,ac,aid = self.login("Alpha")
        b,bc,bid = self.login("Bravo")
        c,cc,cid = self.login("Charlie")
        for cookie,csrf in ((a,ac),(b,bc)):
            self.assertEqual(self.call("/api/messenger/alliance/join",
                                      "POST",{},cookie,csrf)[0],200)
        self.assertEqual(self.call("/api/messenger/mentionables?peer=alliance",
                                   cookie=c)[0],404)
        self.assertEqual(self.call("/api/messenger/polls","POST",
            {"peer":bid,"question":"Private poll?","options":["Yes","No"]},a,ac)[0],400)
        status,created=self.call("/api/messenger/polls","POST",
            {"peer":"alliance","question":"Raid tonight?","options":["Yes","No"]},a,ac)
        self.assertEqual(status,201,created)
        poll_id=created["message"]["id"]
        self.assertEqual(self.call("/api/messenger/polls/vote","POST",
            {"peer":"alliance","id":poll_id,"position":1},c,cc)[0],400)
        self.assertEqual(self.call("/api/messenger/polls/vote","POST",
            {"peer":"alliance","id":poll_id,"position":1},b,bc)[0],200)
        poll=self.call("/api/messenger/messages?peer=alliance",cookie=a)[1]["messages"][-1]["poll"]
        self.assertEqual(poll["total_votes"],1)
        self.assertEqual(poll["options"][1]["votes"],1)
        self.assertEqual(self.call("/api/messenger/polls/vote","POST",
            {"peer":"alliance","id":poll_id,"position":0},b,bc)[0],200)
        self.assertEqual(self.call("/api/messenger/polls/close","POST",
            {"peer":"alliance","id":poll_id},b,bc)[0],403)
        self.assertEqual(self.call("/api/messenger/polls/close","POST",
            {"peer":"alliance","id":poll_id},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger/polls/vote","POST",
            {"peer":"alliance","id":poll_id,"position":0},b,bc)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"Hey @Bravo ready?"},a,ac)[0],201)
        summary=self.call("/api/messenger",cookie=b)[1]
        alliance=next(x for x in summary["contacts"] if x["id"]=="alliance")
        self.assertEqual(alliance["mentions"],1)
        self.assertEqual(self.call("/api/messenger/read","POST",
            {"peer":"alliance"},b,bc)[0],200)
        alliance=next(x for x in self.call("/api/messenger",cookie=b)[1]["contacts"]
                       if x["id"]=="alliance")
        self.assertEqual(alliance["mentions"],0)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"@everyone must not be allowed"},a,ac)[0],400)

    def test_self_notes_are_private_to_owner_and_survive_new_login(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        status,data=self.call("/api/messenger/messages","POST",
            {"peer":aid,"body":"Remember speedups"},a,ac)
        self.assertEqual(status,201,data)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=a)[1]["messages"][0]["body"],
                         "Remember speedups")
        self.assertEqual(self.call("/api/messenger/messages?peer="+bid,cookie=b)[1]["messages"],[])
        self.assertEqual(self.call("/api/messenger",cookie=a)[1]["unread"],0)
        self.assertTrue(any(x.get("self") for x in self.call("/api/messenger",cookie=a)[1]["contacts"]))
        with server.connect() as db:
            self.assertEqual(db.execute(
                "SELECT thread_key FROM chat_messages WHERE body='Remember speedups'").fetchone()[0],
                "notes:"+aid)

    def test_alliance_join_is_one_time_and_history_locked_before_join(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        admin,adcsrf=self.login_admin()
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"Existing important info"},admin,adcsrf)[0],201)
        first=self.call("/api/messenger",cookie=a)[1]
        self.assertFalse(first["contacts"][0]["joined"])
        self.assertEqual(first["contacts"][0]["unread"],0)
        self.assertEqual(self.call("/api/messenger/messages?peer=alliance",cookie=a)[0],404)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"Spoof"},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/read","POST",
            {"peer":"alliance"},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/alliance/join","POST",{},a)[0],403)
        status,data=self.call("/api/messenger/alliance/join","POST",{},a,ac)
        self.assertEqual(status,200,data)
        self.assertTrue(data["joined"])
        self.assertFalse(self.call("/api/messenger/alliance/join","POST",{},a,ac)[1]["joined"])
        self.assertTrue(self.call("/api/messenger",cookie=a)[1]["contacts"][0]["joined"])
        history=self.call("/api/messenger/messages?peer=alliance",cookie=a)[1]["messages"]
        self.assertEqual(history[0]["body"],"Existing important info")
        self.assertEqual(history[-1]["body"],"Alpha Game just Joined the Group-Chat !")
        self.assertEqual(len([x for x in history if x["sender_key"]=="system"]),1)
        self.assertEqual(self.call("/api/messenger",cookie=b)[1]["unread"],0)
        self.assertEqual(self.call("/api/messenger/messages?peer=alliance",cookie=b)[0],404)

    def test_joined_group_can_retrieve_older_history(self):
        a,ac,aid=self.login("Alpha")
        admin,adcsrf=self.login_admin()
        with server.connect() as db:
            for index in range(95):
                db.execute("""INSERT INTO chat_messages(thread_key,sender_key,body,created_at)
                    VALUES('alliance','admin',?,?)""",(str(index),messenger.now_utc()))
        self.assertEqual(self.call("/api/messenger/alliance/join","POST",{},a,ac)[0],200)
        first=self.call("/api/messenger/messages?peer=alliance",cookie=a)[1]
        self.assertTrue(first["has_more"])
        self.assertEqual(len(first["messages"]),80)
        before=first["messages"][0]["id"]
        older=self.call("/api/messenger/messages?peer=alliance&before="+str(before),cookie=a)[1]
        self.assertFalse(older["has_more"])
        self.assertTrue(older["messages"])
        self.assertEqual(older["messages"][0]["body"],"0")

    def test_alliance_group_and_admin_conversation(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        admin,adcsrf=self.login_admin()
        self.assertEqual(self.call("/api/messenger/alliance/join","POST",{},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger/alliance/join","POST",{},b,bc)[0],200)
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":"alliance"},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":"alliance"},b,bc)[0],200)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"alliance","body":"SvS soon"},admin,adcsrf)[0],201)
        self.assertEqual(self.call("/api/messenger",cookie=a)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger/messages?peer=alliance",cookie=b)[1]["messages"][-1]["body"],"SvS soon")
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":"alliance"},a,ac)[0],200)
        self.assertEqual(self.call("/api/messenger",cookie=a)[1]["unread"],0)
        self.assertEqual(self.call("/api/messenger",cookie=b)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger/read","POST",{"peer":"alliance"},admin,adcsrf)[0],200)
        self.assertEqual(self.call("/api/messenger/messages","POST",
            {"peer":"admin","body":"Hello admin"},a,ac)[0],201)
        self.assertEqual(self.call("/api/messenger",cookie=admin)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger/messages?peer="+aid,cookie=admin)[1]["messages"][0]["body"],"Hello admin")

    def test_private_groups_only_visible_to_invited_members(self):
        alpha, alpha_csrf, alpha_id = self.login("Alpha")
        bravo, bravo_csrf, bravo_id = self.login("Bravo")
        charlie, charlie_csrf, charlie_id = self.login("Charlie")
        admin, admin_csrf = self.login_admin()
        self.assertEqual(self.call("/api/messenger/groups", "POST", {
            "name": "Secret SvS", "members": [bravo_id]}, alpha)[0], 403)
        status, result = self.call("/api/messenger/groups", "POST", {
            "name": "Secret SvS", "members": [bravo_id]}, alpha, alpha_csrf)
        self.assertEqual(status, 201, result)
        group_id = result["id"]
        self.assertTrue(group_id.startswith("group:"))
        for cookie, expected in [(alpha,True),(bravo,True),(charlie,False),(admin,False)]:
            status, payload = self.call("/api/messenger",cookie=cookie)
            self.assertEqual(status,200)
            self.assertEqual(any(c["id"]==group_id for c in payload["contacts"]),expected)
            self.assertEqual(payload["contacts"][0]["username"],"SaS - Group Chat")
        invite=next(c for c in self.call("/api/messenger",cookie=bravo)[1]["contacts"]
                    if c["id"]==group_id)
        self.assertTrue(invite["invitation"])
        self.assertFalse(invite["joined"])
        self.assertEqual(invite["invited_by"],"Alpha Game")
        self.assertEqual(invite["unread"],1)
        self.assertEqual(invite["last_message"],"Alpha Game has invited you to join a Group")
        self.assertNotIn("Top secret",json.dumps(invite))
        self.assertEqual(self.call("/api/messenger/messages","POST",{
            "peer": group_id,"body": "Top secret"},charlie,charlie_csrf)[0],400)
        self.assertEqual(self.call("/api/messenger/messages?peer="+group_id,cookie=charlie)[0],404)
        self.assertEqual(self.call("/api/messenger/messages?peer="+group_id,cookie=admin)[0],404)
        self.assertEqual(self.call("/api/messenger/messages?peer="+group_id,cookie=bravo)[0],404)
        self.assertEqual(self.call("/api/messenger/read","POST",{
            "peer":group_id},bravo,bravo_csrf)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",{
            "peer":group_id,"body":"Top secret"},bravo,bravo_csrf)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",{
            "peer":group_id,"body":"Top secret"},alpha,alpha_csrf)[0],201)
        self.assertEqual(self.call("/api/messenger",cookie=bravo)[1]["unread"],1)
        self.assertEqual(self.call("/api/messenger",cookie=charlie)[1]["unread"],0)
        self.assertEqual(self.call("/api/messenger/groups/join","POST",
            {"peer":group_id},bravo)[0],403)
        joined=self.call("/api/messenger/groups/join","POST",
            {"peer":group_id},bravo,bravo_csrf)
        self.assertEqual(joined,(200,{"joined":True}))
        self.assertEqual(self.call("/api/messenger/groups/join","POST",
            {"peer":group_id},bravo,bravo_csrf),(200,{"joined":False}))
        history=self.call("/api/messenger/messages?peer="+group_id,cookie=bravo)[1]["messages"]
        self.assertEqual(history[0]["body"],"Top secret")
        self.assertEqual(history[1]["body"],"Bravo Game joined the Group !")
        self.assertEqual(history[1]["sender_key"],"system")
        updated=next(c for c in self.call("/api/messenger",cookie=bravo)[1]["contacts"]
                    if c["id"]==group_id)
        self.assertFalse(updated.get("invitation",False))
        self.assertEqual(updated["unread"],0)
        self.assertEqual(self.call("/api/messenger/messages","POST",{
            "peer":group_id,"body":"After joining"},bravo,bravo_csrf)[0],201)
        self.assertEqual(self.call("/api/messenger",cookie=alpha)[1]["unread"],2)
        self.assertEqual(self.call("/api/messenger/read","POST",{
            "peer":group_id},bravo,bravo_csrf)[0],200)
        self.assertEqual(self.call("/api/messenger",cookie=bravo)[1]["unread"],0)

    def test_private_group_invite_cannot_be_accessed_by_nonmember(self):
        alpha, ac, aid=self.login("Alpha")
        bravo, bc, bid=self.login("Bravo")
        charlie, cc, cid=self.login("Charlie")
        status,data=self.call("/api/messenger/groups","POST",{
            "name":"Only Selected", "members":[bid]},alpha,ac)
        self.assertEqual(status,201,data)
        group=data["id"]
        for cookie, token in [(charlie,cc)]:
            self.assertEqual(self.call("/api/messenger/groups/join","POST",{
                "peer":group},cookie,token)[0],400)
            self.assertEqual(self.call("/api/messenger/messages?peer="+group,
                cookie=cookie)[0],404)
            self.assertFalse(any(c["id"]==group for c in
                self.call("/api/messenger",cookie=cookie)[1]["contacts"]))
        self.assertEqual(self.call("/api/messenger/groups/join","POST",{
            "peer":"alliance"},bravo,bc)[0],400)
        self.assertEqual(self.call("/api/messenger/groups/join","POST",{
            "peer":"group:999999"},bravo,bc)[0],400)

    def test_existing_group_memberships_remain_joined_after_schema_upgrade(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        status,data=self.call("/api/messenger/groups","POST",
            {"name":"Already Joined","members":[]},a,ac)
        self.assertEqual(status,201,data)
        group=data["id"]
        with server.connect() as db:
            gid=int(group.split(":")[1])
            db.execute("INSERT INTO chat_group_members(group_id,member_key) VALUES(?,?)",
                       (gid,bid))
            messenger.setup(db)
        member=next(c for c in self.call("/api/messenger",cookie=b)[1]["contacts"]
                    if c["id"]==group)
        self.assertFalse(member.get("invitation",False))
        self.assertEqual(self.call("/api/messenger/messages?peer="+group,
                              cookie=b)[0],200)

    def test_group_with_only_its_creator_is_visible_to_no_other_player(self):
        alpha, csrf, alpha_id = self.login("Alpha")
        bravo, _, bravo_id = self.login("Bravo")
        status, data = self.call("/api/messenger/groups", "POST",
            {"name": "Personal Team", "members": []}, alpha, csrf)
        self.assertEqual(status, 201, data)
        group = data["id"]
        self.assertTrue(any(item["id"] == group for item in
            self.call("/api/messenger", cookie=alpha)[1]["contacts"]))
        self.assertFalse(any(item["id"] == group for item in
            self.call("/api/messenger", cookie=bravo)[1]["contacts"]))
        self.assertEqual(self.call("/api/messenger/messages?peer=" + group,
            cookie=bravo)[0], 404)

    def test_group_rejects_pending_and_duplicate_members(self):
        alpha, csrf, alpha_id = self.login("Alpha")
        bravo, _, bravo_id = self.login("Bravo")
        with server.connect() as db:
            pending_id = db.execute("SELECT id FROM members WHERE username='Pending'").fetchone()["id"]
        for members_list in ([bravo_id,bravo_id], [alpha_id], ["member:"+str(pending_id)],
                             [bravo_id,"member:999999"]):
            status, data = self.call("/api/messenger/groups","POST",
                {"name":"Private Test","members":members_list},alpha,csrf)
            self.assertEqual(status,400,data)
        status,data=self.call("/api/messenger/groups","POST",
            {"name":"Private Test","members":[bravo_id]},alpha,csrf)
        self.assertEqual(status,201,data)
        # Account deletion removes member access to their private groups.
        admin,admin_csrf=self.login_admin()
        self.assertEqual(self.call("/api/accounts/"+bravo_id[7:],"DELETE",cookie=admin,csrf=admin_csrf)[0],200)
        self.assertEqual(self.call("/api/messenger",cookie=alpha)[0],200)

    def test_validation_and_account_deletion(self):
        a,ac,aid=self.login("Alpha")
        b,bc,bid=self.login("Bravo")
        admin,adcsrf=self.login_admin()
        for peer in ("member:999999","member:0","member:bad"):
            self.assertIn(self.call("/api/messenger/messages","POST",
                {"peer":peer,"body":"test"},a,ac)[0],(400,))
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":bid,"body":"  "},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":bid,"body":"x"*2001},a,ac)[0],400)
        self.assertEqual(self.call("/api/messenger/messages","POST",{"peer":bid,"body":"<script>attack</script>"},a,ac)[0],201)
        self.assertEqual(self.call("/api/messenger/alliance/join","POST",{},a,ac)[0],200)
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
        self.assertEqual(self.call("/api/messenger/alliance/join","POST",{},a,ac)[0],200)
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
