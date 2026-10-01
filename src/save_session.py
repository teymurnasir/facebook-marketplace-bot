"""
One-time helper: log into Facebook in a real browser window, then save cookies.

Usage:
    python -m src.save_session

A Chromium window opens. Log into Facebook (Canada account is fine),
open Marketplace once, then return here and press Enter.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


def main() -> None:
    load_dotenv()
    out = Path(os.getenv("FACEBOOK_STORAGE_STATE", "storage_state.json"))

    print("Opening Chromium…")
    print("1) Log into Facebook")
    print("2) Visit https://www.facebook.com/marketplace/toronto")
    print("3) Come back to this terminal and press Enter to save the session\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-CA",
            timezone_id="America/Toronto",
        )
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        input("Press Enter after you are logged in and Marketplace loads… ")
        context.storage_state(path=str(out))
        browser.close()

    print(f"Saved session → {out.resolve()}")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
