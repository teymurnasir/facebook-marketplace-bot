import time
import unittest
from playwright.sync_api import sync_playwright
from src.save_session import is_marketplace_url, ready_marketplace_page


class LoginSessionTest(unittest.TestCase):
    def test_user_navigation_while_input_blocks_is_processed_before_saving(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                def reply(route):
                    login = route.request.url.endswith('/login')
                    body = ('<script>setTimeout(() => location.href="/marketplace/", 100)</script>'
                            if login else '<main>Marketplace test</main>')
                    route.fulfill(content_type='text/html', body=body)
                context.route('https://www.facebook.com/**', reply)
                page = context.new_page()
                page.goto('https://www.facebook.com/login', wait_until='domcontentloaded')
                time.sleep(0.3)  # Reproduce waiting for the user in blocking input().
                marketplace = ready_marketplace_page(browser, context, page)
                self.assertIsNotNone(marketplace)
                self.assertTrue(is_marketplace_url(marketplace.url))
                # The user can also open Marketplace in another tab.
                other = context.new_page()
                other.goto('https://www.facebook.com/marketplace/toronto')
                page.goto('https://www.facebook.com/settings')
                self.assertEqual(ready_marketplace_page(browser, context, page), other)
                other.close()
                self.assertIsNone(ready_marketplace_page(browser, context, page))
                self.assertTrue(browser.is_connected())
            finally:
                browser.close()

    def test_login_and_untrusted_urls_are_not_saved_as_marketplace_sessions(self):
        for url in ['https://www.facebook.com/login?next=/marketplace/',
                    'https://www.facebook.com/checkpoint/?next=/marketplace/',
                    'https://evil.invalid/marketplace/',
                    'https://www.facebook.com/marketplace-other/']:
            self.assertFalse(is_marketplace_url(url))
