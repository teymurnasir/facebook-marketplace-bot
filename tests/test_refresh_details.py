import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.sync_findings import refresh_details
from src.scraper import FacebookSessionError
from src.storage import SeenStore


class RefreshDetailsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = SeenStore(Path(directory.name) / "seen.db")
        self.addCleanup(self.store.close)
        self.store.mark_seen("123", "Mazda", "2012 Mazda", "https://example.invalid")
        self.scraper = Mock()
        self.browser, self.context, self.page = Mock(), Mock(), Mock()
        self.scraper._launch.return_value = (self.browser, self.context, self.page)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("src.scraper.MarketplaceScraper", return_value=self.scraper))
        stack.enter_context(patch("playwright.sync_api.sync_playwright"))
        stack.enter_context(patch("time.sleep"))

    def test_updates_database_and_saves_healthy_session_without_new_search(self):
        def read(context, car):
            car.description = "Safety included"
            car.safety = "yes"
            car.safety_evidence = "Safety included"
            car.details_checked_at = "2026-10-07T10:00:00+00:00"
        self.scraper._read_details.side_effect = read
        refresh_details(self.store)
        self.assertEqual(self.store.all_findings()[0]["safety"], "yes")
        self.scraper.run_cycle.assert_not_called()
        self.scraper._save_storage_state.assert_called_once_with(self.context)
        self.browser.close.assert_called_once()

    def test_login_error_does_not_save_session(self):
        self.scraper._read_details.side_effect = FacebookSessionError("Login needed")
        with self.assertRaises(FacebookSessionError):
            refresh_details(self.store)
        self.scraper._save_storage_state.assert_not_called()
        self.browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
