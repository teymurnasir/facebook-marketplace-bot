import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from src.scraper import MarketplaceScraper
from src.session_state import (decode_session_secret, restore_session, session_generation,
                               validate_session_state, write_session_state)


def session(value="test-login", expiry=None):
    return {"cookies": [
        {"name": name, "value": value, "domain": ".facebook.com", "path": "/",
         "expires": expiry if expiry is not None else time.time() + 3600,
         "httpOnly": True, "secure": True, "sameSite": "None"}
        for name in ("c_user", "xs")
    ], "origins": []}


def encoded(state):
    return base64.b64encode(json.dumps(state).encode()).decode()


class SessionStateTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "session.json"
        self.state = session()
        self.secret = encoded(self.state)

    def test_generation_changes_with_new_credentials_not_json_formatting(self):
        generation = session_generation(self.secret)
        pretty = base64.b64encode(json.dumps(self.state, indent=2).encode()).decode()
        self.assertEqual(generation, session_generation(pretty))
        self.assertNotEqual(generation, session_generation(encoded(session("new-login"))))
        self.assertEqual(len(generation), 24)
        self.assertNotIn("test-login", generation)

    def test_invalid_or_missing_login_cookies_rejected_without_leaking_values(self):
        for state in ({}, {"cookies": []}, {"cookies": self.state["cookies"][:1]},
                      {"cookies": [{**c, "domain": ".evil.invalid"} for c in self.state["cookies"]]}):
            with self.subTest(state=state), self.assertRaises(ValueError) as error:
                validate_session_state(state)
            self.assertNotIn("test-login", str(error.exception))

    def test_bad_secret_encoding_and_json_fail_without_echoing_secret(self):
        for secret in ("not base64!", base64.b64encode(b"not-json-secret").decode()):
            with self.subTest(secret=secret), self.assertRaises(ValueError) as error:
                decode_session_secret(secret)
            self.assertNotIn(secret, str(error.exception))
            self.assertNotIn("not-json-secret", str(error.exception))

    def test_expired_cookies_rejected_and_session_cookies_allowed(self):
        with self.assertRaises(ValueError):
            validate_session_state(session(expiry=time.time() - 1))
        validate_session_state(session(expiry=-1))

    def test_restore_falls_back_for_missing_corrupt_or_expired_cache(self):
        for contents in (None, "corrupt", json.dumps(session(expiry=1))):
            with self.subTest(contents=contents):
                self.path.unlink(missing_ok=True)
                if contents is not None:
                    self.path.write_text(contents)
                self.assertFalse(restore_session(self.path, self.secret))
                self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_valid_refreshed_cache_is_preserved_when_seed_cookie_expired(self):
        refreshed = session("refreshed-login")
        write_session_state(self.path, refreshed)
        expired_secret = encoded(session(expiry=1))
        self.assertTrue(session_generation(expired_secret))
        self.assertTrue(restore_session(self.path, expired_secret))
        self.assertEqual(json.loads(self.path.read_text()), refreshed)

    def test_expired_seed_without_usable_cache_requires_login(self):
        with self.assertRaises(ValueError):
            restore_session(self.path, encoded(session(expiry=1)))
        self.assertFalse(self.path.exists())

    def test_saved_state_is_private_and_invalid_state_does_not_replace_it(self):
        write_session_state(self.path, self.state)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            write_session_state(self.path, session(expiry=1))
        self.assertEqual(json.loads(self.path.read_text()), self.state)
        self.assertEqual(list(self.path.parent.glob(".facebook-session-*")), [])

    def test_verified_save_reports_cache_permission_and_invalid_save_does_not(self):
        output = self.path.parent / "github-output"
        context = Mock()
        context.storage_state.return_value = self.state
        scraper = MarketplaceScraper(str(self.path))
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            scraper._save_storage_state(context)
        self.assertEqual(output.read_text(), "facebook_session_refreshed=true\n")
        output.unlink()
        context.storage_state.return_value = session(expiry=1)
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            scraper._save_storage_state(context)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_workflows_share_generation_and_never_cache_failed_or_unverified_session(self):
        root = Path(__file__).resolve().parents[1]
        for workflow in ("marketplace.yml", "sync-findings.yml"):
            steps = yaml.safe_load((root / ".github/workflows" / workflow).read_text())["jobs"]
            steps = next(iter(steps.values()))["steps"]
            session_steps = [s for s in steps if s.get("uses", "").startswith("actions/cache")
                             and s.get("with", {}).get("path") == "storage_state.json"]
            self.assertEqual(len(session_steps), 2)
            restore, save = session_steps
            self.assertIn("steps.facebook-session.outputs.generation", restore["with"]["key"])
            self.assertIn("steps.facebook-session.outputs.generation", restore["with"]["restore-keys"])
            self.assertEqual(restore["with"]["key"], save["with"]["key"])
            self.assertIn("success()", save["if"])
            self.assertIn("facebook_session_refreshed == 'true'", save["if"])


if __name__ == "__main__":
    unittest.main()
