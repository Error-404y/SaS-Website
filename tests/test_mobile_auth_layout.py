"""Browser layout tests for SaS public sign-in, registration, and recovery UI.

Uses the actual HTML, CSS and auth.js (with a stubbed unauthenticated session).
Run in GitHub Actions with Chromium + WebKit, not against production accounts.
"""
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]


def auth_fixture():
    full = (ROOT / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "styles.css").read_text(encoding="utf-8")
    gate = '<section id="auth-gate"' + full.split('<section id="auth-gate"',1)[1].split('</section>',1)[0] + '</section>'
    admin = '<dialog id="login-dialog"' + full.split('<dialog id="login-dialog"',1)[1].split('</dialog>',1)[0] + '</dialog>'
    return ('<!doctype html><html lang="en"><head>'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>' + css + '</style></head><body>' + gate + admin + '</body></html>')


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class LoginMobileLayoutTests(unittest.TestCase):
    engine = 'chromium'

    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = getattr(cls.playwright,cls.engine).launch(headless=True)
        cls.html = auth_fixture()
        cls.js = (ROOT / "auth.js").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def new_page(self,width,height):
        page=self.browser.new_page(viewport={'width':width,'height':height},
                                   is_mobile=True,has_touch=True)
        page.set_content(self.html,wait_until='load')
        page.evaluate("""()=>{
            window.fetch=async()=>({ok:true,status:200,json:async()=>({admin:false,approved:false})});
        }""")
        page.add_script_tag(content=self.js)
        return page

    def metrics(self,page):
        return page.evaluate("""()=>{
          const rect=s=>{
            const r=document.querySelector(s).getBoundingClientRect();
            return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};
          };
          const gate=document.querySelector('#auth-gate');
          return {
            gate:rect('#auth-gate'),brand:rect('.auth-brand'),card:rect('.auth-card'),
            footer:rect('.auth-bottom'),
            documentWidth:document.documentElement.scrollWidth,
            documentScroll:document.documentElement.scrollTop,
            gateScroll:gate.scrollTop,gateScrollable:gate.scrollHeight>gate.clientHeight+5,
            gateOverflow:getComputedStyle(gate).overflowY,
            inputFont:parseFloat(getComputedStyle(document.querySelector(
              '.auth-form:not(.hidden) input')).fontSize)
          };
        }""")

    def check_form(self,page,width,height,submit_selector):
        data=self.metrics(page)
        self.assertLessEqual(data['documentWidth'],width+1,data)
        self.assertEqual(data['gateOverflow'],'auto',data)
        self.assertGreaterEqual(data['card']['left'],-1,data)
        self.assertLessEqual(data['card']['right'],width+1,data)
        self.assertLessEqual(data['gate']['bottom'],height+1,data)
        self.assertGreaterEqual(data['inputFont'],16,data)
        submit=page.locator(submit_selector)
        submit.scroll_into_view_if_needed(timeout=3000)
        bounds=submit.bounding_box()
        self.assertIsNotNone(bounds)
        self.assertGreaterEqual(bounds['y'],-1)
        self.assertLessEqual(bounds['y']+bounds['height'],height+1,bounds)
        self.assertGreaterEqual(bounds['height'],42,bounds)
        self.assertEqual(page.evaluate('document.documentElement.scrollTop'),0)

    def test_signin_register_recovery_at_phone_sizes(self):
        for width,height in ((320,480),(320,568),(375,667),(390,844),(430,932),(744,900)):
            with self.subTest(width=width,height=height):
                page=self.new_page(width,height)
                try:
                    self.check_form(page,width,height,'#member-login-form .auth-primary')
                    page.locator('[data-auth-tab="register"]').click()
                    self.check_form(page,width,height,'#member-register-form .auth-primary')
                    if height<=568:
                        self.assertTrue(self.metrics(page)['gateScrollable'])
                    page.locator('[data-auth-tab="signin"]').click()
                    page.locator('#forgot-password').click()
                    self.check_form(page,width,height,'#password-request-form .auth-primary')
                    page.locator('#have-reset-code').click()
                    self.check_form(page,width,height,'#password-complete-form .auth-primary')
                finally:
                    page.close()

    def test_keyboard_shrink_keeps_focused_input_accessible(self):
        for width,height in ((320,390),(390,360)):
            with self.subTest(width=width,height=height):
                page=self.new_page(width,780)
                try:
                    page.locator('[data-auth-tab="register"]').click()
                    page.set_viewport_size({'width':width,'height':height})
                    page.locator('#member-password').focus()
                    page.locator('#member-password').scroll_into_view_if_needed()
                    rect=page.locator('#member-password').bounding_box()
                    self.assertIsNotNone(rect)
                    self.assertGreaterEqual(rect['y'],-1)
                    self.assertLessEqual(rect['y']+rect['height'],height+1)
                    self.assertGreaterEqual(self.metrics(page)['inputFont'],16)
                    self.check_form(page,width,height,'#member-register-form .auth-primary')
                finally:
                    page.close()

    def test_admin_signin_dialog_fits_small_screen(self):
        page=self.new_page(320,568)
        try:
            page.locator('#auth-admin').click()
            self.assertTrue(page.locator('#login-dialog').evaluate('(d)=>d.open'))
            box=page.locator('#login-dialog').bounding_box()
            self.assertIsNotNone(box)
            self.assertGreaterEqual(box['x'],-1)
            self.assertLessEqual(box['x']+box['width'],321)
            self.assertLessEqual(box['y']+box['height'],569)
            self.assertGreaterEqual(page.locator('#login-password').evaluate(
                '(x)=>parseFloat(getComputedStyle(x).fontSize)'),16)
            page.locator('#login-dialog [data-close]').click()
            self.assertFalse(page.locator('#login-dialog').evaluate('(d)=>d.open'))
        finally:
            page.close()


class LoginWebKitLayoutTests(LoginMobileLayoutTests):
    engine='webkit'


if __name__=='__main__':
    unittest.main()
