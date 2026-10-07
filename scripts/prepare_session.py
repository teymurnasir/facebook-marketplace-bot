"""Prepare generation-scoped Facebook session caches for GitHub Actions."""

from __future__ import annotations

import argparse
import os

from src.session_state import restore_session, session_generation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generation", "restore"))
    parser.add_argument("--path", default="storage_state.json")
    args = parser.parse_args()
    encoded = os.environ.get("FACEBOOK_STORAGE_STATE_B64", "")
    if not encoded:
        parser.exit(1, "Missing FACEBOOK_STORAGE_STATE_B64; add a freshly saved session\n")
    try:
        if args.operation == "generation":
            print(f"generation={session_generation(encoded)}")
        else:
            cached = restore_session(args.path, encoded)
            print("Using refreshed session cache" if cached else "Restored session from secret")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
