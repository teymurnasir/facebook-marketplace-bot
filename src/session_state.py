"""Validate and save Facebook session state without exposing cookie values."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


def validate_session_state(state: Any, *, check_expiry: bool = True) -> None:
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        raise ValueError("Facebook session must contain a cookies list")
    valid_names = set()
    for cookie in state["cookies"]:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain", "")).lstrip(".")
        if domain not in {"facebook.com", "www.facebook.com"}:
            continue
        expiry = cookie.get("expires", -1)
        if not isinstance(expiry, (int, float)) or (check_expiry and expiry > 0 and expiry <= time.time()):
            continue
        if cookie.get("value"):
            valid_names.add(cookie.get("name"))
    if not {"c_user", "xs"}.issubset(valid_names):
        raise ValueError("Facebook login cookies are missing or expired; a fresh login is required")


def decode_session_secret(encoded: str, *, check_expiry: bool = True) -> dict[str, Any]:
    try:
        state = json.loads(base64.b64decode("".join(encoded.split()), validate=True))
    except (ValueError, UnicodeError):
        raise ValueError("FACEBOOK_STORAGE_STATE_B64 is not valid base64 session JSON") from None
    validate_session_state(state, check_expiry=check_expiry)
    return state


def session_generation(encoded: str) -> str:
    state = decode_session_secret(encoded, check_expiry=False)
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()[:24]


def write_session_state(path: str | Path, state: dict[str, Any]) -> None:
    validate_session_state(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".facebook-session-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def restore_session(path: str | Path, encoded: str, *, from_secret: bool = False) -> bool:
    path = Path(path)
    seed = decode_session_secret(encoded, check_expiry=False)
    if path.is_file() and not from_secret:
        try:
            validate_session_state(json.loads(path.read_text(encoding="utf-8")))
            return True
        except (ValueError, OSError):
            pass
    write_session_state(path, seed)
    return False


def _cache_cipher(key: str) -> Fernet:
    if not key:
        raise ValueError("Missing FACEBOOK_SESSION_CACHE_KEY; plaintext session caching is not allowed")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError):
        raise ValueError("FACEBOOK_SESSION_CACHE_KEY is not a valid encryption key") from None


def encrypted_session_generation(encoded: str, key: str) -> str:
    _cache_cipher(key)
    return f"{session_generation(encoded)}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def encrypt_session_cache(path: str | Path, cache: str | Path, encoded: str, key: str) -> None:
    cipher = _cache_cipher(key)
    seed = decode_session_secret(encoded, check_expiry=False)
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_session_state(state)
    def account(data: dict[str, Any]) -> set[str]:
        return {c["value"] for c in data["cookies"] if c.get("name") == "c_user"
                and str(c.get("domain", "")).lstrip(".") in {"facebook.com", "www.facebook.com"}}
    if account(state) != account(seed):
        raise ValueError("Refreshed session belongs to a different Facebook account")
    payload = json.dumps({"version": 1, "generation": session_generation(encoded), "state": state}).encode()
    cache = Path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".encrypted-session-", dir=cache.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(cipher.encrypt(payload))
        os.replace(temporary, cache)
    finally:
        Path(temporary).unlink(missing_ok=True)


def restore_encrypted_session(path: str | Path, cache: str | Path, encoded: str,
                              key: str, *, from_secret: bool = False) -> bool:
    cipher = _cache_cipher(key)
    seed = decode_session_secret(encoded, check_expiry=False)
    cache = Path(cache)
    if cache.is_file() and not from_secret:
        try:
            payload = json.loads(cipher.decrypt(cache.read_bytes()))
            if payload.get("version") != 1 or payload.get("generation") != session_generation(encoded):
                raise ValueError("Encrypted cache belongs to another session generation")
            state = payload["state"]
            validate_session_state(state)
            write_session_state(path, state)
            return True
        except (InvalidToken, ValueError, KeyError, TypeError, OSError, AttributeError):
            # A corrupt, expired, or rotated cache never falls back to plaintext caches.
            pass
    write_session_state(path, seed)
    return False


def report_session_refresh() -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("facebook_session_refreshed=true\n")
