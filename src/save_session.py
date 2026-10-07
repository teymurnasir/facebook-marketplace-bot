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

from .session_state import write_session_state


def _desktop_chrome_user_agent(chrome_version: str) -> str:
    version = (chrome_version or "120.0.0.0").split()[0]
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version} Safari/537.36"
    )


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
            user_agent=_desktop_chrome_user_agent(browser.version),
        )
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        input("Press Enter after you are logged in and Marketplace loads… ")
        if "/marketplace" not in page.url or "/login" in page.url or "/checkpoint" in page.url:
            browser.close()
            raise SystemExit("Marketplace is not open. Log in and open Marketplace before saving.")
        write_session_state(out, context.storage_state())
        browser.close()

    print(f"Saved session → {out.resolve()}")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
