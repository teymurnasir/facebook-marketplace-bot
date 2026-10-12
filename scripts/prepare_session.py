"""Prepare generation-scoped Facebook session caches for GitHub Actions."""

from __future__ import annotations

import argparse
import os

from src.session_state import encrypt_session_cache, encrypted_session_generation, restore_encrypted_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generation", "restore", "encrypt"))
    parser.add_argument("--path", default="storage_state.json")
    parser.add_argument("--cache", default="facebook_session.enc")
    parser.add_argument("--from-secret", action="store_true", help="Ignore the session cache for a manual recovery")
    args = parser.parse_args()
    encoded = os.environ.get("FACEBOOK_STORAGE_STATE_B64", "")
    key = os.environ.get("FACEBOOK_SESSION_CACHE_KEY", "").strip()
    if not encoded:
        parser.exit(1, "Missing FACEBOOK_STORAGE_STATE_B64; add a freshly saved session\n")
    try:
        if args.operation == "generation":
            print(f"generation={encrypted_session_generation(encoded, key)}")
        elif args.operation == "restore":
            cached = restore_encrypted_session(args.path, args.cache, encoded, key, from_secret=args.from_secret)
            print("Using refreshed session cache" if cached else "Restored session from secret")
        else:
            encrypt_session_cache(args.path, args.cache, encoded, key)
            print("Refreshed Facebook session encrypted; plaintext is not cached")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
