"""End-to-end browser tests for the real SaS Messenger DOM and rich UI scripts.

Uses fake authenticated API responses, never production accounts or networks.
"""
import base64
import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]


def html_fixture():
    html=(ROOT/"index.html").read_text(encoding="utf-8")
    css=(ROOT/"styles.css").read_text(encoding="utf-8")
    html=re.sub(r'<script\b[^>]*\bsrc="/[^"]+"[^>]*></script>',"",html)
    return html.replace("</head>","<base href=\"http://sas-test.local/\"><style>"+css+"</style></head>",1)


@unittest.skipIf(sync_playwright is None, 'Playwright not installed')
class RichMessengerBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(headless=True)
        cls.html=html_fixture()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def open_chat(self):
        page=self.browser.new_page(viewport={"width":390,"height":844},
                                   is_mobile=True,has_touch=True)
        captures=[]
        def api(route):
            u=urlsplit(route.request.url)
            method=route.request.method
            body=json.loads(route.request.post_data) if route.request.post_data else {}
            captures.append((u.path,method,body))
            if u.path=="/api/messenger":
                data={"me":"member:1","contacts":[
                    {"id":"alliance","username":"SaS - Group Chat",
                     "player_name":"Everyone","group":True,"joined":True,
                     "can_mention_everyone":False,"unread":0,"last_id":3,"last_message":"Raid?"},
                    {"id":"member:2","username":"Bravo","player_name":"Bravo Game",
                     "group":False,"unread":0,"last_id":0,"last_message":""},
                    {"id":"member:1","username":"Alpha","player_name":"Alpha Game",
                     "group":False,"self":True,"unread":0,"last_id":0,"last_message":""}]}
            elif u.path=="/api/messenger/mentionables":
                data={"members":[{"id":"member:2","username":"Bravo","player_name":"Bravo Game"}]}
            elif u.path=="/api/messenger/messages" and method=="GET":
                data={"peer":"alliance","me":"member:1","has_more":False,
                  "typing":["Bravo Game"],
                  "messages":[
                    {"id":1,"sender_key":"member:2","body":"Original",
                     "kind":"text","created_at":"2026-11-14 05:00:00",
                     "reply_to_id":None,"edited_at":None,"deleted_at":None},
                    {"id":2,"sender_key":"member:1","body":"My message",
                     "kind":"text","created_at":"2026-11-14 05:01:00",
                     "reply_to_id":None,"edited_at":None,"deleted_at":None},
                    {"id":3,"sender_key":"member:2","body":"Raid?",
                     "kind":"poll","created_at":"2026-11-14 05:02:00",
                     "poll":{"question":"Raid?", "options":[
                       {"position":0,"label":"Yes","votes":0},
                       {"position":1,"label":"No","votes":0}],
                       "total_votes":0,"my_vote":None,"closed":False}},
                    {"id":4,"sender_key":"member:1","body":"Which day?",
                     "kind":"poll","created_at":"2026-11-14 05:04:00",
                     "poll":{"question":"Which day?", "options":[
                       {"position":0,"label":"Friday","votes":1},
                       {"position":1,"label":"Saturday","votes":0}],
                       "total_votes":1,"my_vote":0,"closed":False}}]}
            else:
                data={"ok":True,"message":{"id":50},"poll":{"total_votes":1}}
            route.fulfill(status=200,content_type="application/json",body=json.dumps(data))
        page.route("**/api/**",api)
        # Serve the test document from a real same-origin URL; set_content() uses
        # about:blank, where cross-origin credentialed fetches can be blocked
        # before Playwright's mocked Messenger API receives them.
        page.route("http://sas-test.local/",lambda route: route.fulfill(
            status=200,content_type="text/html",body=self.html))
        page.goto("http://sas-test.local/",wait_until="load")
        page.evaluate("""()=>{
          document.querySelector('#auth-gate')?.remove();
          document.querySelector('#entrance')?.remove();
          document.querySelector('#website').classList.remove('hidden');
          document.querySelector('#page-messenger').classList.remove('hidden');
          document.querySelectorAll('.page:not(#page-messenger)').forEach(x=>x.classList.add('hidden'));
        }""")
        page.add_script_tag(content=(ROOT/"messenger-rich-ui.js").read_text(encoding="utf-8"))
        page.add_script_tag(content=(ROOT/"messenger-ui.js").read_text(encoding="utf-8"))
        page.evaluate("""()=>{
          window.SasMessenger.init();
          window.SasMessenger.onPage('messenger');
          window.SasMessenger.start('test-token');
        }""")
        page.locator('[data-messenger-peer="alliance"]').click(timeout=8000)
        page.locator('[data-rich-message="3"]').wait_for(state="visible",timeout=8000)
        return page,captures

    def test_reply_mentions_edit_and_vote(self):
        page,captured=self.open_chat()
        try:
            self.assertIn("Bravo Game is typing",page.locator("#rich-typing").inner_text())
            page.locator('[data-rich-message="1"] [data-rich-menu]').click()
            page.locator('[data-rich-reply="1"]').click()
            self.assertTrue(page.locator("#rich-reply-preview").is_visible())
            page.locator("#messenger-message").fill("Answer @Br")
            page.locator('[data-rich-mention="Bravo"]').click()
            self.assertIn("@Bravo ",page.locator("#messenger-message").input_value())
            page.locator("#messenger-send").click()
            send=[x for x in captured if x[0]=="/api/messenger/messages" and x[1]=="POST"]
            self.assertTrue(send, captured)
            self.assertEqual(send[-1][2]["reply_to"],1)
            self.assertIn("@Bravo",send[-1][2]["body"])
            # Wait for the async Send handler to finish its history refresh.
            # Otherwise that refresh can replace the message menu mid-click.
            page.wait_for_function("""()=>{
              const send=document.querySelector('#messenger-send');
              return !send.disabled &&
                document.querySelector('#messenger-message').value==='' &&
                document.querySelector('#rich-reply-preview').hidden;
            }""", timeout=8000)
            page.evaluate("""()=>{
              window.__actionTrace=[];
              const dialog=document.querySelector('#rich-actions-dialog');
              const history=document.querySelector('#messenger-history');
              const observe=(phase,e)=>window.__actionTrace.push({
                phase,target:e.target.tagName,
                attr:e.target.getAttribute('data-rich-menu'),
                open:dialog.open,dialogConnected:dialog.isConnected,
                messageCount:history.querySelectorAll('[data-rich-message]').length
              });
              history.addEventListener('click',e=>observe('capture',e),true);
              history.addEventListener('click',e=>observe('bubble',e));
              document.addEventListener('click',e=>observe('document',e));
              window.addEventListener('error',e=>window.__actionTrace.push({phase:'error',message:e.message}));
            }""")
            page.locator('[data-rich-message="2"] [data-rich-menu]').click()
            state=page.evaluate("""()=>({
              open:document.querySelector('#rich-actions-dialog').open,
              trace:window.__actionTrace
            })""")
            self.assertTrue(state["open"],state)
            self.assertTrue(page.locator('[data-rich-edit="2"]').is_visible())
            page.locator('[data-rich-edit="2"]').click(timeout=5000)
            page.locator("#rich-edit-body").fill("Updated text")
            page.locator("#rich-edit-submit").click()
            edits=[x for x in captured if x[0]=="/api/messenger/messages/edit"]
            self.assertTrue(edits)
            self.assertEqual(edits[-1][2]["body"],"Updated text")
            page.locator('[data-rich-vote="3"][data-rich-position="0"]').click()
            votes=[x for x in captured if x[0]=="/api/messenger/polls/vote"]
            self.assertTrue(votes)
            self.assertEqual(votes[-1][2]["position"],0)
        finally:
            page.close()

    def test_close_poll_and_delete_message_use_styled_confirmation(self):
        page,captured=self.open_chat()
        try:
            # Native browser confirm must never be used for these actions.
            page.evaluate("""()=>{
              window.confirm=()=>{throw new Error('Native confirmation should not be used');};
            }""")
            page.locator('[data-rich-close-poll="4"]').click()
            dialog=page.locator("#rich-confirm-dialog")
            self.assertTrue(dialog.evaluate("(d)=>d.open"))
            self.assertEqual(page.locator("#rich-confirm-title").inner_text(),"Close this poll?")
            self.assertIn("no longer be able to vote",
                          page.locator("#rich-confirm-message").inner_text())
            self.assertEqual(page.locator("#rich-confirm-submit").inner_text(),"Close poll")
            # On a narrow phone, the entire dialog and both buttons must fit.
            page.set_viewport_size({"width":320,"height":568})
            box=dialog.bounding_box()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box["x"],-1,box)
            self.assertLessEqual(box["x"]+box["width"],321,box)
            self.assertLessEqual(box["y"]+box["height"],569,box)
            page.locator("#rich-confirm-cancel").click()
            self.assertFalse(dialog.evaluate("(d)=>d.open"))
            self.assertFalse([x for x in captured if x[0]=="/api/messenger/polls/close"])
            page.locator('[data-rich-close-poll="4"]').click()
            page.locator("#rich-confirm-submit").click()
            page.wait_for_function("""()=>!document.querySelector('#rich-confirm-dialog').open""")
            polls=[x for x in captured if x[0]=="/api/messenger/polls/close"]
            self.assertEqual(len(polls),1,polls)
            self.assertEqual(polls[0][2],{"peer":"alliance","id":4})

            # Message deletion uses the exact same popup, not an alert.
            page.locator('[data-rich-message="2"] [data-rich-menu]').click()
            page.locator('[data-rich-delete="2"]').click()
            self.assertTrue(dialog.evaluate("(d)=>d.open"))
            self.assertEqual(page.locator("#rich-confirm-title").inner_text(),"Delete message?")
            self.assertIn("Delete this message for everyone?",
                          page.locator("#rich-confirm-message").inner_text())
            self.assertEqual(page.locator("#rich-confirm-submit").inner_text(),"Delete for everyone")
            self.assertFalse([x for x in captured if x[0]=="/api/messenger/messages/delete"])
            page.keyboard.press("Escape")
            self.assertFalse(dialog.evaluate("(d)=>d.open"))
            self.assertFalse([x for x in captured if x[0]=="/api/messenger/messages/delete"])
            page.locator('[data-rich-message="2"] [data-rich-menu]').click()
            page.locator('[data-rich-delete="2"]').click()
            page.locator("#rich-confirm-submit").click()
            page.wait_for_function("""()=>!document.querySelector('#rich-confirm-dialog').open""")
            deleted=[x for x in captured if x[0]=="/api/messenger/messages/delete"]
            self.assertEqual(len(deleted),1,deleted)
            self.assertEqual(deleted[0][2],{"peer":"alliance","id":2})
        finally:
            page.close()

    def test_poll_creation_and_image_attachment(self):
        page,captured=self.open_chat()
        try:
            page.locator("#rich-poll-trigger").click()
            page.locator("#rich-poll-question").fill("Which event?")
            options=page.locator("#rich-poll-options input")
            options.nth(0).fill("Training")
            options.nth(1).fill("Raid")
            page.locator("#rich-poll-submit").click()
            polls=[x for x in captured if x[0]=="/api/messenger/polls"]
            self.assertTrue(polls)
            self.assertEqual(polls[-1][2]["options"],["Training","Raid"])
            # Valid 24x24 PNG fixture; browser CI needs no Pillow dependency.
            png=base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqv"
                "AAAAIklEQVR4nGNU9s5koAZgooopowaNGjRq0KhBowaNGkQRAABo5gEHfNTLSAAAAABJRU5ErkJggg==")
            page.locator("#rich-image-file").set_input_files({
                "name":"game-screenshot.png","mimeType":"image/png",
                "buffer":png})
            page.locator("#rich-photo-preview").wait_for(state="visible",timeout=8000)
            page.locator("#messenger-message").fill("My screenshot")
            page.locator("#messenger-send").click()
            page.wait_for_timeout(500)
            images=[x for x in captured if x[0]=="/api/messenger/images"]
            self.assertTrue(images)
            self.assertGreater(len(images[-1][2]["image"]),100)
            self.assertEqual(images[-1][2]["caption"],"My screenshot")
        finally:
            page.close()


if __name__=="__main__":
    unittest.main()
