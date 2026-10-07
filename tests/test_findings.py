import tempfile
import unittest
import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from src.settings_sync import publish_findings
from src.storage import SeenStore
from src.models import Listing


class FindingsTest(unittest.TestCase):
    def test_migrates_existing_database_and_enriches_without_re_notifying(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seen.db"
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE seen_listings (listing_id TEXT PRIMARY KEY, search_name TEXT, "
                             "title TEXT, url TEXT, first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                conn.execute("INSERT INTO seen_listings (listing_id, title) VALUES ('123', '2012 Mazda 3')")
            store = SeenStore(path)
            try:
                before = store.all_findings()[0]
                self.assertIsNone(before["price_amount"])
                car = Listing("123", "2012 Mazda 3", "CA$1,500", 1500, "North York, ON",
                              "https://www.facebook.com/marketplace/item/123", "Mazda",
                              year=2012, mileage_km=210000, description="Safety included",
                              safety="yes", safety_evidence="Safety included",
                              details_checked_at="2026-10-07T10:00:00+00:00")
                store.update_details(car)
                after = store.all_findings()[0]
                self.assertEqual(after["price_amount"], 1500)
                self.assertEqual(after["mileage_km"], 210000)
                self.assertEqual(after["location"], "North York, ON")
                self.assertEqual(after["safety"], "yes")
                self.assertEqual(after["description"], "Safety included")
                self.assertEqual(after["first_seen_at"], before["first_seen_at"])
                self.assertTrue(after["last_seen_at"])
                self.assertTrue(store.is_seen("123"))
                store.update_details(replace(car, price="Price n/a", price_amount=None,
                                             mileage_km=None, location=""))
                self.assertEqual(store.all_findings()[0]["price_amount"], 1500)
                self.assertEqual(store.all_findings()[0]["mileage_km"], 210000)
            finally:
                store.close()
            reopened = SeenStore(path)
            try:
                self.assertEqual(len(reopened.all_findings()), 1)
                self.assertEqual(reopened.all_findings()[0]["price_amount"], 1500)
            finally:
                reopened.close()

    def test_exports_complete_history_including_old_rows_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SeenStore(Path(directory) / "seen.db")
            self.addCleanup(store.close)
            store.mark_seen("123", "Mazda", "2012 Mazda 3", "https://example.invalid/123")
            store.mark_seen("456", "Kia", "2013 Kia Optima", "https://example.invalid/456")
            store.mark_seen("123", "Mazda", "Duplicate", "")
            rows = store.all_findings()
            self.assertEqual([r["listing_id"] for r in rows], ["456", "123"])
            self.assertEqual(rows[1]["title"], "2012 Mazda 3")
            self.assertTrue(rows[0]["first_seen_at"])
            self.assertTrue(store.is_seen("123"))

    def test_publisher_requires_server_confirmation_of_complete_snapshot(self):
        with patch("src.settings_sync.settings_enabled", return_value=True), \
                patch("src.settings_sync._base_url", return_value="https://worker.invalid"), \
                patch("src.settings_sync.httpx.Client") as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.json.return_value = {"ok": True, "count": 1}
            rows = [{"listing_id": "123"}]
            self.assertTrue(publish_findings(rows))
            self.assertEqual(client.return_value.__enter__.return_value.post.call_args.kwargs["json"],
                             {"findings": rows})
            response.json.return_value = {"ok": True, "count": 0}
            with self.assertRaisesRegex(RuntimeError, "complete findings snapshot"):
                publish_findings(rows)

    def test_publish_disabled_without_shared_settings(self):
        with patch("src.settings_sync.settings_enabled", return_value=False), \
                patch("src.settings_sync.httpx.Client") as client:
            self.assertFalse(publish_findings([]))
            client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
