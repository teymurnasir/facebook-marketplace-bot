import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml
from cryptography.fernet import Fernet

from src.scraper import MarketplaceScraper
from src.session_state import (decode_session_secret, restore_session, session_generation,
                               validate_session_state, write_session_state, encrypt_session_cache,
                               restore_encrypted_session, encrypted_session_generation)


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
        self.key = Fernet.generate_key().decode()
        self.cache = self.path.parent / "session.enc"

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

    def test_manual_recovery_replaces_cache_with_original_secret(self):
        write_session_state(self.path, session("rejected-cache"))
        self.assertFalse(restore_session(self.path, self.secret, from_secret=True))
        self.assertEqual(json.loads(self.path.read_text()), self.state)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_expired_secret_recovery_does_not_destroy_existing_cache(self):
        write_session_state(self.path, self.state)
        with self.assertRaises(ValueError):
            restore_session(self.path, encoded(session(expiry=1)), from_secret=True)
        self.assertEqual(json.loads(self.path.read_text()), self.state)

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
                             and s.get("with", {}).get("path") == "facebook_session.enc"]
            self.assertEqual(len(session_steps), 2)
            restore, save = session_steps
            self.assertIn("steps.facebook-session.outputs.generation", restore["with"]["key"])
            self.assertIn("steps.facebook-session.outputs.generation", restore["with"]["restore-keys"])
            self.assertEqual(restore["with"]["key"], save["with"]["key"])
            self.assertIn("success()", save["if"])
            self.assertIn("facebook_session_refreshed == 'true'", save["if"])
            self.assertIn("fb-session-v4-encrypted-", restore["with"]["key"])
            self.assertFalse(any("storage_state.json" in s.get("with", {}).get("path", "")
                                 for s in steps if s.get("uses", "").startswith("actions/cache")))
            encryption = [s for s in steps if s.get("run") == "python -m scripts.prepare_session encrypt"]
            self.assertEqual(len(encryption), 1)
            self.assertIn("success()", encryption[0]["if"])
            self.assertIn("facebook_session_refreshed == 'true'", encryption[0]["if"])
            self.assertIn("FACEBOOK_SESSION_CACHE_KEY", encryption[0]["env"])

    def test_encrypted_cache_round_trip_contains_no_plaintext_credentials(self):
        write_session_state(self.path, self.state)
        encrypt_session_cache(self.path, self.cache, self.secret, self.key)
        self.assertNotIn(b"test-login", self.cache.read_bytes())
        self.assertNotIn(b'"cookies"', self.cache.read_bytes())
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)
        self.path.unlink()
        self.assertTrue(restore_encrypted_session(self.path, self.cache, self.secret, self.key))
        self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_missing_or_invalid_key_fails_closed_without_plaintext_fallback(self):
        for key in ("", "invalid-private-key"):
            with self.assertRaises(ValueError) as error:
                restore_encrypted_session(self.path, self.cache, self.secret, key)
            self.assertNotIn("invalid-private-key", str(error.exception))
            self.assertFalse(self.path.exists())

    def test_key_rotation_changes_generation_and_ignores_old_ciphertext(self):
        write_session_state(self.path, self.state)
        encrypt_session_cache(self.path, self.cache, self.secret, self.key)
        new_key = Fernet.generate_key().decode()
        self.assertNotEqual(encrypted_session_generation(self.secret, self.key),
                            encrypted_session_generation(self.secret, new_key))
        self.assertFalse(restore_encrypted_session(self.path, self.cache, self.secret, new_key))
        self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_tampered_plaintext_or_wrong_generation_cache_uses_secret_only(self):
        for contents in (b"tampered", json.dumps(self.state).encode(),
                         Fernet(self.key.encode()).encrypt(json.dumps({
                             "version": 1, "generation": "wrong", "state": session("different")}).encode())):
            self.cache.write_bytes(contents)
            write_session_state(self.path, session("old-plaintext-cache"))
            self.assertFalse(restore_encrypted_session(self.path, self.cache, self.secret, self.key))
            self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_manual_reset_ignores_valid_encrypted_cache(self):
        refreshed = session()
        refreshed["cookies"][1]["value"] = "refreshed-xs"
        write_session_state(self.path, refreshed)
        encrypt_session_cache(self.path, self.cache, self.secret, self.key)
        self.assertFalse(restore_encrypted_session(self.path, self.cache, self.secret, self.key, from_secret=True))
        self.assertEqual(json.loads(self.path.read_text()), self.state)

    def test_valid_encrypted_cache_can_outlive_cookie_expiry_in_seed(self):
        expired_seed = encoded(session(expiry=1))
        write_session_state(self.path, self.state)
        encrypt_session_cache(self.path, self.cache, expired_seed, self.key)
        self.assertTrue(restore_encrypted_session(self.path, self.cache, expired_seed, self.key))

    def test_different_account_is_not_encrypted(self):
        write_session_state(self.path, session("other-account"))
        with self.assertRaises(ValueError):
            encrypt_session_cache(self.path, self.cache, self.secret, self.key)
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
