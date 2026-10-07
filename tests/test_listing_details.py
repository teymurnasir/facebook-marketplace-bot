import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from src.listing_details import classify_safety
from src.models import Listing
from src.scraper import FacebookSessionError, MarketplaceScraper


class SafetyTest(unittest.TestCase):
    def test_yes_requires_clear_certification_statement(self):
        for text in ("Safety included", "Comes with safety certificate", "Freshly safetied",
                     "Passed safety inspection", "Safety: yes"):
            with self.subTest(text=text):
                status, evidence = classify_safety(text)
                self.assertEqual(status, "yes")
                self.assertEqual(evidence, text)

    def test_negative_and_conditional_statements_are_not_positive(self):
        for text in ("No safety", "Selling as-is", "Not safetied", "Needs safety",
                     "Safety not included", "Will not pass safety", "Safety expired"):
            with self.subTest(text=text):
                self.assertEqual(classify_safety(text)[0], "no")
        for text in ("", "Great safety features", "Can provide safety certificate",
                     "Safety available for extra cost", "Should pass safety",
                     "Certified pre-owned", "Was safetied", "Safetied upon request",
                     "Safety included. Sold as-is.", "No safety issues", "No safety recalls"):
            with self.subTest(text=text):
                self.assertEqual(classify_safety(text)[0], "unknown")

    def test_telegram_listing_includes_escaped_seller_evidence(self):
        car = Listing("123", "Car", "$2000", 2000, "Toronto", "https://facebook.com", "Search",
                      safety="no", safety_evidence="No safety <inspection>")
        message = car.telegram_message()
        self.assertIn("Safety: <b>no</b>", message)
        self.assertIn("No safety &lt;inspection&gt;", message)


class DescriptionCheckTest(unittest.TestCase):
    def setUp(self):
        self.scraper = MarketplaceScraper("unused")
        self.car = Listing("123", "2014 Kia Optima", "$2500", 2500, "Toronto",
                           "https://www.facebook.com/marketplace/item/123", "Kia")
        self.context = Mock()
        self.page = self.context.new_page.return_value
        self.page.evaluate.return_value = "Safety included. Hybrid. 220,000 km"
        self.page.locator.return_value.all.return_value = []

    def test_description_populates_safety_and_mileage(self):
        with patch.object(self.scraper, "_raise_if_session_problem"):
            self.scraper._read_details(self.context, self.car)
        self.assertEqual(self.car.safety, "yes")
        self.assertEqual(self.car.mileage_km, 220000)
        self.assertTrue(self.car.details_checked_at)
        self.page.close.assert_called_once()

    def test_graphql_uses_only_description_of_requested_listing(self):
        self.page.evaluate.return_value = ""
        def navigate(*args, **kwargs):
            handler = self.page.on.call_args.args[1]
            response = Mock(url="https://www.facebook.com/api/graphql")
            response.text.return_value = json.dumps({"data": [
                {"id": "999", "description": {"text": "Safety included"}},
                {"id": "123", "redacted_description": {"text": "No safety"}},
            ]})
            handler(response)
        self.page.goto.side_effect = navigate
        with patch.object(self.scraper, "_raise_if_session_problem"):
            self.scraper._read_details(self.context, self.car)
        self.assertEqual(self.car.description, "No safety")
        self.assertEqual(self.car.safety, "no")

    def test_missing_description_remains_unknown_and_is_not_cached_as_verified(self):
        self.page.evaluate.return_value = ""
        with patch.object(self.scraper, "_raise_if_session_problem"):
            self.scraper._read_details(self.context, self.car)
        self.assertEqual(self.car.safety, "unknown")
        self.assertEqual(self.car.details_checked_at, "")

    def test_checkpoint_during_description_check_propagates_and_closes_page(self):
        with patch.object(self.scraper, "_raise_if_session_problem", side_effect=FacebookSessionError("login")):
            with self.assertRaises(FacebookSessionError):
                self.scraper._read_details(self.context, self.car)
        self.page.close.assert_called_once()

    def test_cache_expires_and_reclassifies_saved_description(self):
        saved = {"description": "No safety", "safety": "yes", "mileage_km": 220000,
                 "details_checked_at": datetime.now(timezone.utc).isoformat()}
        self.assertTrue(self.scraper._restore_details(self.car, saved))
        self.assertEqual(self.car.safety, "no")
        saved["details_checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        self.assertFalse(self.scraper._restore_details(self.car, saved))


if __name__ == "__main__":
    unittest.main()
