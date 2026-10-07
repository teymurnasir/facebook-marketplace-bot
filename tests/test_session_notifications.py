import os
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import main
from src.models import Listing, SearchConfig
from src.scraper import FacebookSessionError, MarketplaceScraper


class SessionNotificationsTest(unittest.TestCase):
    def setUp(self):
        self.search = SearchConfig("Mazda", "mazda", 2010, 2014, 300, 2300)
        self.listing = Listing("123", "2012 Mazda 3", "CA$1000", 1000, "Toronto",
                               "https://www.facebook.com/marketplace/item/123", "Mazda")
        self.cfg = {
            "searches": [self.search], "locations": ["toronto"],
            "location_keywords": [], "scraper": {
                "sort_by": "creation_time_descend", "max_scrolls": 1,
                "delay_between_searches_sec": 0, "timeout_ms": 1000,
            },
        }
        self.scraper = MarketplaceScraper("unused.json")
        self.browser = Mock()
        self.context = Mock()
        self.page = Mock()
        self.page.url = "https://www.facebook.com/marketplace/toronto/search"
        self.page.context.cookies.return_value = [{"name": "c_user", "value": "123"}]
        self.telegram = Mock()
        self.store = Mock()
        self.store.is_seen.return_value = False
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "CUSTOM_SEARCH": "0", "MANUAL_SCAN": "0", "TELEGRAM_SCAN_SUMMARY": "1",
        }))
        self.stack.enter_context(patch("src.scraper.sync_playwright"))
        self.stack.enter_context(patch.object(self.scraper, "_launch",
                                            return_value=(self.browser, self.context, self.page)))
        self.save = self.stack.enter_context(patch.object(self.scraper, "_save_storage_state"))
        self.scrape = self.stack.enter_context(patch.object(self.scraper, "_scrape_url",
                                                          return_value=[self.listing]))

    def run_scan(self, notify=True):
        return main.run_once(self.scraper, self.store, self.telegram, self.cfg, notify=notify)

    def messages(self):
        return [call.args[0] for call in self.telegram.send_text.call_args_list]

    def test_active_session_notified_once_and_in_summary(self):
        self.assertEqual(self.run_scan(), 1)
        messages = self.messages()
        self.assertIn("Checking Facebook session", messages[0])
        self.assertEqual(sum("<b>Facebook session active</b>" in m for m in messages), 1)
        self.assertIn("Marketplace data verified", messages[-1])
        self.save.assert_called_once()

    def test_raw_data_confirms_access_even_when_filters_reject_every_listing(self):
        self.search.must_include_all = ["hybrid"]
        self.assertEqual(self.run_scan(), 0)
        self.assertTrue(self.scraper.session_verified)
        self.assertIn("Facebook session active", self.messages()[-1])

    def test_empty_pages_do_not_claim_active_or_save_session(self):
        self.scrape.return_value = []
        self.assertEqual(self.run_scan(), 0)
        self.assertFalse(self.scraper.session_verified)
        self.assertTrue(any("<b>Facebook status not verified</b>" in m for m in self.messages()))
        self.assertFalse(any("session active" in m for m in self.messages()))
        self.save.assert_not_called()

    def test_listing_data_without_login_cookie_is_unverified(self):
        self.page.context.cookies.return_value = []
        self.run_scan()
        self.assertFalse(self.scraper.session_verified)
        self.save.assert_not_called()

    def test_all_page_errors_fail_scan_instead_of_empty_success(self):
        self.scrape.side_effect = RuntimeError("Network unavailable")
        with self.assertRaisesRegex(RuntimeError, "All Marketplace pages failed"):
            self.run_scan()
        self.assertFalse(any("finished" in m for m in self.messages()))
        self.save.assert_not_called()
        self.browser.close.assert_called_once()

    def test_seed_mode_is_silent(self):
        self.run_scan(notify=False)
        self.telegram.send_text.assert_not_called()
        self.telegram.send_listing.assert_not_called()

    def test_scan_syncs_full_history_even_when_there_are_no_new_cars(self):
        self.store.is_seen.return_value = True
        history = [{"listing_id": "123"}, {"listing_id": "456"}]
        self.store.all_findings.return_value = history
        with patch("main.settings_enabled", return_value=True), patch("main.publish_findings") as publish:
            self.assertEqual(self.run_scan(), 0)
        publish.assert_called_once_with(history)
        self.telegram.send_listing.assert_not_called()

    def test_sync_failure_keeps_scan_result_and_warns_about_old_catalog(self):
        with patch("main.settings_enabled", return_value=True), \
                patch("main.publish_findings", side_effect=RuntimeError("Sync unavailable")):
            self.assertEqual(self.run_scan(), 1)
        self.assertTrue(any("/cars may show the previous scan" in m for m in self.messages()))
        self.assertIn("finished", self.messages()[-1])

    def test_health_notification_is_independent_of_summary_setting(self):
        with patch.dict(os.environ, {"TELEGRAM_SCAN_SUMMARY": "0"}):
            self.run_scan()
        self.assertEqual(len(self.messages()), 2)
        self.assertIn("<b>Facebook session active</b>", self.messages()[1])

    def test_login_failure_gets_actionable_telegram_alert(self):
        self.scrape.side_effect = FacebookSessionError("Login requested")
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "test-chat",
            }))
            stack.enter_context(patch("main.load_dotenv"))
            stack.enter_context(patch("main.sys.argv", ["main.py", "--once"]))
            stack.enter_context(patch("main._prepare_cycle", return_value=(self.cfg, 180, False, None)))
            stack.enter_context(patch("main.MarketplaceScraper", return_value=self.scraper))
            stack.enter_context(patch("main.SeenStore", return_value=self.store))
            stack.enter_context(patch("main.TelegramNotifier", return_value=self.telegram))
            self.assertEqual(main.main(), 1)
        self.assertIn("Facebook session inactive - login needed", self.messages()[-1])
        self.assertIn("FACEBOOK_STORAGE_STATE_B64", self.messages()[-1])
        self.assertFalse(any("finished" in m for m in self.messages()))
        self.save.assert_not_called()

    def test_health_state_resets_on_next_cycle(self):
        self.run_scan()
        self.scrape.return_value = []
        self.telegram.reset_mock()
        self.run_scan()
        self.assertFalse(self.scraper.session_verified)
        self.assertFalse(any("session active" in m for m in self.messages()))

    def test_login_redirect_is_rechecked_after_scrolling(self):
        page = Mock()
        checks = []

        def check(current):
            checks.append(current)
            if len(checks) == 2:
                raise FacebookSessionError("Checkpoint after scrolling")

        with patch.object(self.scraper, "_raise_if_session_problem", side_effect=check):
            with self.assertRaises(FacebookSessionError):
                MarketplaceScraper._scrape_url(self.scraper, page, self.page.url, self.search, 1)
        self.assertEqual(len(checks), 2)
        page.remove_listener.assert_called_once()


if __name__ == "__main__":
    unittest.main()
