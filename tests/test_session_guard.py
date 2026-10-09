import os
import unittest
from unittest.mock import Mock, patch

import main
from src.settings_sync import publish_session_status


class SessionGuardTest(unittest.TestCase):
    def test_disabled_settings_do_not_make_requests(self):
        with patch("src.settings_sync.settings_enabled", return_value=False), \
                patch("src.settings_sync.httpx.Client") as client:
            self.assertFalse(publish_session_status("inactive", 1000))
        client.assert_not_called()

    def test_report_contains_status_and_ordering_only(self):
        for status in ("active", "inactive"):
            response = Mock()
            response.json.return_value = {"ok": True, "applied": True}
            with patch.dict(os.environ, {"SETTINGS_CONFIG_URL": "https://worker.invalid/config",
                                         "SETTINGS_CONFIG_TOKEN": "test-token"}), \
                    patch("src.settings_sync.httpx.Client") as client:
                post = client.return_value.__enter__.return_value.post
                post.return_value = response
                self.assertTrue(publish_session_status(status, 1000))
                post.assert_called_once_with("https://worker.invalid/session",
                                             headers={"Authorization": "Bearer test-token"},
                                             json={"status": status, "scan_started_at": 1000})
                response.raise_for_status.assert_called_once()

    def test_stale_result_is_not_claimed_applied(self):
        response = Mock()
        response.json.return_value = {"ok": True, "applied": False}
        with patch("src.settings_sync.settings_enabled", return_value=True), \
                patch("src.settings_sync.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response
            self.assertFalse(publish_session_status("inactive", 1000))

    def test_network_failure_does_not_hide_original_scan_failure(self):
        with patch("main.publish_session_status", side_effect=RuntimeError("unreachable")):
            self.assertFalse(main._report_session_status("inactive", 1000))

    def test_unknown_status_cannot_clear_pause(self):
        with self.assertRaises(ValueError):
            publish_session_status("unknown", 1000)


if __name__ == "__main__":
    unittest.main()
