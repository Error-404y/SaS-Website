"""Browser regression coverage for the real mobile Messenger CSS (no live account needed).

Run: python -m unittest tests.test_mobile_messenger_layout -v
Requires: pip install playwright && python -m playwright install chromium
"""
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    # A representative DOM keeps the exact app class/id hierarchy so CSS cascade,
    # parent flex sizes and absolute positioning are checked together.
    return """<!doctype html><html class="sas-messenger-root"><head>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>""" + css + """</style></head>
      <body class="sas-messenger-page messenger-mobile-chat-open">
      <div id="website" class="website">
        <header class="site-header">
          <div class="header-brand"><strong>SaS</strong><span id="header-section">SaS Messenger</span></div>
          <div class="header-actions"><button class="small-button">Sign out</button></div>
        </header>
        <div id="site-layout" class="layout">
          <main id="main-content" class="content">
            <section id="page-messenger" class="page page-animate">
              <div class="page-title messenger-titlebar"><h1>SaS Messenger</h1></div>
              <div id="messenger-shell" class="messenger-shell chat-open">
                <aside class="messenger-list">
                  <div class="messenger-list-heading"><strong>Messages</strong></div>
                  <label class="messenger-search-label"><input id="messenger-search" placeholder="Find player"></label>
                  <div id="messenger-contact-list" class="messenger-contact-list"></div>
                </aside>
                <div id="messenger-chat" class="messenger-chat">
                  <div class="messenger-chat-header">
                    <button id="messenger-back" class="messenger-back">Back</button>
                    <div class="messenger-avatar">SaS</div>
                    <div class="messenger-chat-identity"><strong>SaS Admin</strong><span>Online</span></div>
                  </div>
                  <div id="messenger-history" class="messenger-history"></div>
                  <form class="messenger-compose" id="messenger-compose">
                    <div id="rich-reply-preview" class="rich-compose-preview" hidden>
                      <span>Replying to a message</span><button type="button">×</button>
                    </div>
                    <div id="rich-photo-preview" class="rich-compose-preview" hidden>
                      <span>Photo ready</span><button type="button">×</button>
                    </div>
                    <button type="button" class="rich-tool-button" id="rich-image-trigger">📷</button>
                    <button type="button" class="rich-tool-button" id="rich-poll-trigger">☷</button>
                    <label class="sr-only" for="messenger-message">Your message</label>
                    <input id="messenger-message" placeholder="Write a message..." value="Test" />
                    <button id="messenger-send" aria-label="Send message">➤</button>
                  </form>
                </div>
              </div>
            </section>
          </main>
          <aside class="right-sidebar">
            <p class="sidebar-heading">EXPLORE <span class="mobile-nav-hint">← Swipe to see more →</span></p>
            <nav class="sidebar-nav">
              <button>Events</button><button class="selected">SaS Messenger</button>
              <button>Alliance Events</button><button>Alliance RSS</button>
            </nav>
          </aside>
        </div>
      </div>
      <script>
      const history = document.querySelector('#messenger-history');
      for(let i=0;i<70;i++){
        const row=document.createElement('div');
        row.className='messenger-line'+(i%2?' mine':'');
        row.innerHTML='<div class="messenger-bubble"><span class="messenger-bubble-text">Test chat message '+i+'</span><span class="messenger-bubble-footer"><time>02:00 UTC</time></span></div>';
        history.append(row);
      }
      const contacts = document.querySelector('#messenger-contact-list');
      for(let i=0;i<65;i++){
        const el=document.createElement('div');
        el.className='messenger-contact';
        el.textContent='Player '+i;
        contacts.append(el);
      }
      </script>
      </body></html>"""


@unittest.skipIf(sync_playwright is None, "Playwright not installed")
class MobileMessengerLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.html = fixture()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_multiple_phone_dimensions(self):
        for width, height in ((320, 568), (375, 667), (390, 520),
                              (390, 844), (430, 932), (744, 900)):
            with self.subTest(width=width, height=height):
                page = self.browser.new_page(viewport={"width":width,"height":height},
                                              device_scale_factor=2,is_mobile=True,has_touch=True)
                try:
                    page.set_content(self.html, wait_until="load")
                    page.evaluate("""(height)=>{
                      document.documentElement.style.setProperty(
                        '--sas-messenger-viewport-height', height+'px');
                    }""", height)
                    self.assert_layout(page, width, height)
                    if (width,height) in ((320,568),(390,520),(390,844)):
                        shots=ROOT / "test-results"
                        shots.mkdir(exist_ok=True)
                        page.screenshot(path=str(shots / (
                            "messenger-"+self.browser.browser_type.name+
                            "-"+str(width)+"x"+str(height)+".png")))
                finally:
                    page.close()

    def test_chat_history_scrolls_without_page_scrolling(self):
        page=self.browser.new_page(viewport={"width":390,"height":744},
                                   is_mobile=True,has_touch=True)
        try:
            page.set_content(self.html, wait_until="load")
            initial=page.evaluate("""()=>{
              const h=document.querySelector('#messenger-history');
              return {max:h.scrollHeight-h.clientHeight,body:document.scrollingElement.scrollTop};
            }""")
            self.assertGreater(initial["max"], 100)
            page.locator("#messenger-history").evaluate("(el)=>{el.scrollTop=el.scrollHeight/2;}")
            after=page.evaluate("""()=>{
              const h=document.querySelector('#messenger-history');
              return {history:h.scrollTop,body:document.scrollingElement.scrollTop};
            }""")
            self.assertGreater(after["history"],0)
            self.assertEqual(after["body"],initial["body"])
            page.locator("#messenger-shell").evaluate("(el)=>el.classList.remove('chat-open')")
            after_list=page.evaluate("""()=>{
              const l=document.querySelector('#messenger-contact-list');
              l.scrollTop=150;
              return {scroll:l.scrollTop,max:l.scrollHeight-l.clientHeight};
            }""")
            self.assertGreater(after_list["max"],100)
            self.assertGreater(after_list["scroll"],0)
        finally:
            page.close()

    def test_send_button_can_be_tapped(self):
        # A click on the actual send control must work, not merely be present
        # in the DOM outside the viewport (the original iPhone regression).
        for width,height in ((320,568),(390,844),(744,900)):
            with self.subTest(width=width,height=height):
                page=self.browser.new_page(viewport={"width":width,"height":height},
                                           is_mobile=True,has_touch=True)
                try:
                    page.set_content(self.html,wait_until="load")
                    page.evaluate("""()=>{
                      window.__sent=null;
                      document.querySelector('#messenger-compose').addEventListener(
                        'submit',e=>{
                          e.preventDefault();
                          window.__sent=document.querySelector('#messenger-message').value;
                        });
                    }""")
                    page.locator("#messenger-message").fill("hello from phone")
                    page.locator("#messenger-send").click(timeout=2500)
                    self.assertEqual(page.evaluate("window.__sent"),"hello from phone")
                finally:
                    page.close()

    def test_rich_composer_with_reply_and_photo_previews(self):
        for width,height in ((320,568),(375,667),(390,844)):
            with self.subTest(width=width,height=height):
                page=self.browser.new_page(viewport={"width":width,"height":height},
                                           is_mobile=True,has_touch=True)
                try:
                    page.set_content(self.html,wait_until="load")
                    page.evaluate("""()=>{
                      document.querySelector('#rich-reply-preview').hidden=false;
                      document.querySelector('#rich-photo-preview').hidden=false;
                    }""")
                    self.assert_layout(page,width,height)
                    for selector in ("#rich-image-trigger","#rich-poll-trigger","#messenger-send"):
                        rect=page.locator(selector).bounding_box()
                        self.assertIsNotNone(rect)
                        self.assertGreater(rect["width"],30,rect)
                        self.assertLessEqual(rect["x"]+rect["width"],width+1,rect)
                finally:
                    page.close()

    def test_rich_message_markup_is_escaped(self):
        page=self.browser.new_page(viewport={"width":390,"height":844},
                                   is_mobile=True,has_touch=True)
        try:
            page.set_content(self.html,wait_until="load")
            page.add_script_tag(content=(ROOT/"messenger-rich-ui.js").read_text(encoding="utf-8"))
            page.evaluate("""()=>{
              const msgs=[
                {id:11,sender_key:"member:1",body:"Hello @Bravo <img src=x onerror=alert(1)>",
                  kind:"text",created_at:"2026-11-14 05:00:00",read:false,
                  reply:{id:9,sender_key:"member:2",body:"Previous message"}},
                {id:12,sender_key:"member:2",body:"Battle screenshot",
                  kind:"image",created_at:"2026-11-14 05:01:00"},
                {id:13,sender_key:"member:2",body:"Raid?",
                  kind:"poll",created_at:"2026-11-14 05:02:00",
                  poll:{question:"Raid?",options:[
                    {position:0,label:"Yes",votes:1},
                    {position:1,label:"No",votes:0}],
                    total_votes:1,my_vote:null,closed:false}}
              ];
              document.querySelector('#messenger-history').innerHTML=
                window.SasRich.messageMarkup(msgs,{
                  peer:"alliance",me:"member:1",
                  contacts:[{id:"member:2",username:"Bravo"}]
                });
            }""")
            self.assertEqual(page.locator(".rich-quoted").count(),1)
            self.assertEqual(page.locator(".rich-image-link img").count(),1)
            self.assertEqual(page.locator(".rich-poll-option").count(),2)
            self.assertEqual(page.locator(".rich-mention").count(),1)
            self.assertEqual(page.locator("img[onerror]").count(),0)
            self.assertIn("<img src=x onerror=alert(1)>",
                          page.locator(".messenger-bubble-text").first.inner_text())
        finally:
            page.close()

    def test_short_chat_and_small_keyboard_viewport(self):
        page=self.browser.new_page(viewport={"width":390,"height":720},
                                   is_mobile=True,has_touch=True)
        try:
            page.set_content(self.html,wait_until="load")
            page.evaluate("""()=>{
                document.querySelector('#messenger-history').replaceChildren();
                document.body.classList.add('sas-messenger-keyboard');
                document.documentElement.style.setProperty(
                  '--sas-messenger-viewport-height','380px');
            }""")
            self.assert_layout(page,390,380)
        finally:
            page.close()

    def test_ios_keyboard_pan_keeps_composer_above_keyboard(self):
        # iOS Safari may pan its visual viewport when the keyboard opens.
        # Regression screenshot: viewport height was applied without pageTop,
        # which left a huge empty band below the message composer.
        for page_top,visible_height in ((300,250),(175,330),(0,420)):
            with self.subTest(page_top=page_top,visible_height=visible_height):
                page=self.browser.new_page(viewport={"width":390,"height":780},
                                           is_mobile=True,has_touch=True)
                try:
                    page.set_content(self.html,wait_until="load")
                    page.add_script_tag(content=(ROOT / "messenger-ui.js").read_text(encoding="utf-8"))
                    page.evaluate("""(geometry)=>{
                      Object.defineProperty(window,'visualViewport',{
                        configurable:true,
                        value:{
                          pageTop:geometry.pageTop,
                          offsetTop:geometry.pageTop,
                          height:geometry.height,
                          addEventListener:()=>{}
                        }
                      });
                      window.SasMessenger.onPage('messenger');
                      document.body.classList.add('sas-messenger-keyboard');
                      window.SasMessenger.onPage('messenger');
                    }""", {"pageTop":page_top,"height":visible_height})
                    target_bottom=page_top+visible_height
                    data=page.evaluate("""()=>{
                      const composer=document.querySelector('#messenger-compose').getBoundingClientRect();
                      const send=document.querySelector('#messenger-send').getBoundingClientRect();
                      return {
                        composerBottom:composer.bottom,
                        composerTop:composer.top,
                        sendRight:send.right,
                        documentScrollTop:document.scrollingElement.scrollTop,
                        effectiveHeight:parseFloat(getComputedStyle(document.documentElement)
                          .getPropertyValue('--sas-messenger-viewport-height')),
                        visible:!!send.width && !!send.height
                      };
                    }""")
                    self.assertAlmostEqual(data["effectiveHeight"],target_bottom,delta=1,msg=data)
                    self.assertLessEqual(data["composerBottom"],target_bottom+1,data)
                    self.assertGreaterEqual(data["composerBottom"],target_bottom-24,data)
                    self.assertLessEqual(data["sendRight"],390,data)
                    self.assertTrue(data["visible"],data)
                    self.assertEqual(data["documentScrollTop"],0,data)
                finally:
                    page.close()

    def assert_layout(self,page,width,height):
        data=page.evaluate("""()=>{
          const box = selector => {
             const r=document.querySelector(selector).getBoundingClientRect();
             return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
          };
          const h=document.querySelector('#messenger-history');
          const b=document.querySelector('#messenger-send');
          const input=document.querySelector('#messenger-message');
          return {
            shell:box('#messenger-shell'),chat:box('#messenger-chat'),
            header:box('.messenger-chat-header'),history:box('#messenger-history'),
            composer:box('#messenger-compose'),input:box('#messenger-message'),
            send:box('#messenger-send'),
            bodyOverflow:getComputedStyle(document.body).overflowY,
            listOverflow:getComputedStyle(h).overflowY,
            documentHeight:document.documentElement.scrollHeight,
            documentWidth:document.documentElement.scrollWidth,
            buttonDisplay:getComputedStyle(b).display,
            buttonVisibility:getComputedStyle(b).visibility,
            disabled:b.disabled,inputDisabled:input.disabled
          };
        }""")
        self.assertLessEqual(data["shell"]["bottom"],height+2,data)
        self.assertLessEqual(data["composer"]["bottom"],height+2,data)
        self.assertLessEqual(data["send"]["right"],width+1,data)
        self.assertLessEqual(data["documentWidth"],width+1,data)
        self.assertGreater(data["send"]["width"],35,data)
        self.assertGreater(data["input"]["width"],90,data)
        self.assertLessEqual(data["input"]["right"],data["send"]["x"],data)
        self.assertGreaterEqual(data["composer"]["y"],data["history"]["bottom"]-2,data)
        self.assertGreaterEqual(data["history"]["y"],data["header"]["bottom"]-2,data)
        self.assertEqual(data["bodyOverflow"],"hidden",data)
        self.assertEqual(data["listOverflow"],"auto",data)
        self.assertNotEqual(data["buttonDisplay"],"none",data)
        self.assertNotEqual(data["buttonVisibility"],"hidden",data)


@unittest.skipIf(sync_playwright is None, "Playwright not installed")
class MobileMessengerWebKitLayoutTests(MobileMessengerLayoutTests):
    """Run identical layout/scroll checks in Safari's WebKit engine."""

    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.webkit.launch(headless=True)
        cls.html = fixture()


if __name__ == "__main__":
    unittest.main()
