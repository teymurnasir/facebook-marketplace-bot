import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.settings_sync import publish_findings
from src.storage import SeenStore


class FindingsTest(unittest.TestCase):
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
