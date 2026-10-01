from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from .models import Listing, SearchConfig

logger = logging.getLogger(__name__)

ITEM_ID_RE = re.compile(r"/marketplace/item/(\d+)")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
PRICE_RE = re.compile(r"[\d,]+")
MILEAGE_RE = re.compile(
    r"([\d.,\s\u00a0]+)\s*(km|kilometers?|kilometres?|miles?|mi)\b",
    re.IGNORECASE,
)


def build_search_url(location_slug: str, search: SearchConfig, sort_by: str) -> str:
    params = {
        "query": search.query,
        "minPrice": search.min_price,
        "maxPrice": search.max_price,
        "minYear": search.min_year,
        "maxYear": search.max_year,
        "exact": "false",
        "sortBy": sort_by,
    }
    if search.max_mileage_km is not None:
        # Marketplace vehicle mileage filter (when supported by the UI)
        params["maxMileage"] = search.max_mileage_km
    # Vehicles category + query filters year/price better than generic search
    base = f"https://www.facebook.com/marketplace/{location_slug}/search"
    return f"{base}?{urlencode(params)}"


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _extract_listings_from_graphql(payload: Any, search_name: str) -> list[Listing]:
    found: dict[str, Listing] = {}

    for node in _walk(payload):
        if not isinstance(node, dict):
            continue

        listing_id = node.get("id") or node.get("listing_id")
        story = node.get("story_key") or node.get("listing_key")

        # Marketplace listing cards often look like this
        listing = node.get("listing") if isinstance(node.get("listing"), dict) else None
        candidate = listing or node

        url_path = (
            candidate.get("url")
            or candidate.get("share_uri")
            or candidate.get("marketplace_listing_title")
            or ""
        )
        if isinstance(url_path, str) and "/marketplace/item/" in url_path:
            m = ITEM_ID_RE.search(url_path)
            if m:
                listing_id = m.group(1)

        if listing_id is None:
            continue
        listing_id = str(listing_id)
        if not listing_id.isdigit():
            # Facebook sometimes uses long numeric/string ids; still accept numeric-ish
            if not re.fullmatch(r"\d+", listing_id):
                continue

        title = (
            candidate.get("custom_title")
            or candidate.get("marketplace_listing_title")
            or candidate.get("title")
            or candidate.get("name")
            or ""
        )
        if not isinstance(title, str) or not title.strip():
            continue
        # Skip seller/profile nodes that sneak into the walk
        if not YEAR_RE.search(title) and "mazda" not in title.lower() and "optima" not in title.lower() and "kia" not in title.lower():
            if candidate.get("__typename") not in {
                "GroupCommerceProductItem",
                "MarketplaceVehicleListing",
                "VehicleListing",
            } and not candidate.get("listing_price") and not candidate.get("formatted_price"):
                continue

        price_text = ""
        price_amount = None
        formatted = (
            candidate.get("listing_price")
            or candidate.get("formatted_price")
            or candidate.get("price")
            or candidate.get("min_listing_price")
        )
        if isinstance(formatted, dict):
            price_text = (
                formatted.get("formatted_amount")
                or formatted.get("text")
                or formatted.get("amount")
                or ""
            )
            try:
                if formatted.get("amount") is not None:
                    price_amount = int(round(float(str(formatted["amount"]))))
            except (TypeError, ValueError):
                pass
            if price_amount is None and price_text:
                price_amount = _parse_price_amount(str(price_text))
        elif isinstance(formatted, str):
            price_text = formatted
            price_amount = _parse_price_amount(formatted)

        location = ""
        loc = candidate.get("location") or candidate.get("location_text")
        if isinstance(loc, dict):
            rg = loc.get("reverse_geocode") if isinstance(loc.get("reverse_geocode"), dict) else {}
            location = (
                (rg.get("city_page") or {}).get("display_name")
                if isinstance(rg.get("city_page"), dict)
                else ""
            ) or rg.get("city") or loc.get("name") or ""
            if rg.get("state") and location and "," not in location:
                location = f"{location}, {rg['state']}"
        elif isinstance(loc, str):
            location = loc
        if not location and isinstance(candidate.get("location_text"), dict):
            location = candidate["location_text"].get("text") or ""

        mileage_km = _extract_mileage_from_candidate(candidate)

        url = f"https://www.facebook.com/marketplace/item/{listing_id}"
        year = None
        ym = YEAR_RE.search(title)
        if ym:
            year = int(ym.group(0))

        if not price_text and price_amount is not None:
            price_text = f"CA${price_amount:,}"

        found[listing_id] = Listing(
            listing_id=listing_id,
            title=title.strip(),
            price=str(price_text) if price_text else "Price n/a",
            price_amount=price_amount,
            location=str(location or "").strip(),
            url=url,
            search_name=search_name,
            year=year,
            mileage_km=mileage_km,
            raw={"story": story},
        )

    return list(found.values())


def _parse_mileage_km(text: str) -> int | None:
    """Parse odometer text like '330.000 km', '250,000 km', '120000 miles'."""
    if not text:
        return None
    m = MILEAGE_RE.search(text.replace("\xa0", " "))
    if not m:
        return None
    amount = _parse_number(m.group(1))
    if amount is None:
        return None
    unit = m.group(2).lower()
    if unit.startswith("mi"):
        return int(round(amount * 1.60934))
    return amount


def _extract_mileage_from_candidate(candidate: dict[str, Any]) -> int | None:
    subs = candidate.get("custom_sub_titles_with_rendering_flags") or []
    if isinstance(subs, list):
        for sub in subs:
            if isinstance(sub, dict):
                km = _parse_mileage_km(str(sub.get("subtitle") or ""))
                if km is not None:
                    return km
            elif isinstance(sub, str):
                km = _parse_mileage_km(sub)
                if km is not None:
                    return km
    for key in ("odometer_data", "vehicle_odometer_data", "mileage"):
        val = candidate.get(key)
        if isinstance(val, dict):
            for nested_key in ("value", "amount", "odometer", "text"):
                if val.get(nested_key) is not None:
                    if isinstance(val[nested_key], (int, float)):
                        return int(val[nested_key])
                    km = _parse_mileage_km(str(val[nested_key]))
                    if km is not None:
                        return km
        elif isinstance(val, (int, float)):
            return int(val)
        elif isinstance(val, str):
            km = _parse_mileage_km(val)
            if km is not None:
                return km
    return None


def _parse_number(text: str) -> int | None:
    """Parse locale-aware integers (2.000 / 2,000 / 2000)."""
    if not text:
        return None
    cleaned = text.replace("\xa0", " ").replace(" ", "").strip()
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = "".join(parts) if len(parts[-1]) == 3 and len(parts) > 1 else cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts[-1]) == 3 and len(parts) > 1:
            cleaned = "".join(parts)
    try:
        return int(round(float(cleaned)))
    except ValueError:
        digits = re.sub(r"[^\d]", "", cleaned)
        return int(digits) if digits else None


def _parse_price_amount(price_text: str) -> int | None:
    """Parse Marketplace prices across locales (CA$ 2.000, CA$ 2,000, $2000)."""
    if not price_text:
        return None
    cleaned = (
        price_text.replace("\xa0", " ")
        .replace("CA$", "")
        .replace("US$", "")
        .replace("$", "")
        .replace("zł", "")
        .replace(" ", "")
        .strip()
        .lower()
    )
    if not cleaned or cleaned in {"free", "pulsuz", "gratuit"}:
        return 0
    return _parse_number(cleaned)


def _is_mileage_line(line: str) -> bool:
    return _parse_mileage_km(line) is not None


def _is_price_line(line: str) -> bool:
    low = line.lower()
    if "free" in low or "pulsuz" in low:
        return True
    return bool(re.search(r"(\$|ca\$|zł|\d)", low) and re.search(r"\d", line))


def _extract_listings_from_dom(page: Page, search_name: str) -> list[Listing]:
    found: dict[str, Listing] = {}
    anchors = page.locator('a[href*="/marketplace/item/"]')
    count = anchors.count()
    for i in range(min(count, 80)):
        try:
            a = anchors.nth(i)
            href = a.get_attribute("href") or ""
            m = ITEM_ID_RE.search(href)
            if not m:
                continue
            listing_id = m.group(1)
            if listing_id in found:
                continue

            # Card text order varies by locale: price lines often come before the title
            text = a.inner_text(timeout=2000) or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            price_lines = [ln for ln in lines if "$" in ln or "CA$" in ln or "zł" in ln.lower() or ln.lower() in {"free", "pulsuz"}]
            price = price_lines[0] if price_lines else "Price n/a"

            mileage_km = _parse_mileage_km(text)
            non_price = [
                ln
                for ln in lines
                if ln not in price_lines
                and not YEAR_RE.fullmatch(ln)
                and not _is_mileage_line(ln)
            ]
            title = next((ln for ln in non_price if YEAR_RE.search(ln) or len(ln) > 3), None)
            if not title:
                title = non_price[0] if non_price else f"Listing {listing_id}"

            location = ""
            for ln in non_price:
                if ln == title:
                    continue
                # City lines look like "Toronto, ON" / "Brampton, ON"
                if "," in ln or ln.endswith(" ON") or ln.endswith(" Ontario"):
                    location = ln
                    break
            if not location:
                for ln in non_price:
                    if ln != title and not _is_price_line(ln):
                        location = ln
                        break

            year = None
            ym = YEAR_RE.search(title)
            if ym:
                year = int(ym.group(0))

            found[listing_id] = Listing(
                listing_id=listing_id,
                title=title,
                price=price,
                price_amount=_parse_price_amount(price),
                location=location,
                url=f"https://www.facebook.com/marketplace/item/{listing_id}",
                search_name=search_name,
                year=year,
                mileage_km=mileage_km,
            )
        except Exception as exc:
            logger.debug("DOM card parse skipped: %s", exc)
            continue
    return list(found.values())


def matches_filters(
    listing: Listing,
    search: SearchConfig,
    location_keywords: list[str],
) -> bool:
    hay = f"{listing.title} {listing.location}".lower()

    if search.must_include_any:
        if not any(k.lower() in hay for k in search.must_include_any):
            return False

    if search.must_include_all:
        if not all(k.lower() in hay for k in search.must_include_all):
            return False

    if search.require_body_style and search.body_styles:
        if not any(b.lower() in hay for b in search.body_styles):
            return False

    if listing.year is not None:
        if listing.year < search.min_year or listing.year > search.max_year:
            return False

    if listing.price_amount is not None:
        if listing.price_amount < search.min_price or listing.price_amount > search.max_price:
            return False

    if search.require_mileage and listing.mileage_km is None:
        return False

    if search.max_mileage_km is not None and listing.mileage_km is not None:
        if listing.mileage_km > search.max_mileage_km:
            return False

    if location_keywords:
        loc = listing.location.lower()
        # Empty location: keep (FB sometimes omits it on cards)
        if loc and not any(k.lower() in loc for k in location_keywords):
            return False

    return True


class MarketplaceScraper:
    def __init__(
        self,
        storage_state_path: str,
        headless: bool = True,
        timeout_ms: int = 45000,
    ) -> None:
        self.storage_state_path = storage_state_path
        self.headless = headless
        self.timeout_ms = timeout_ms

    def run_cycle(
        self,
        searches: list[SearchConfig],
        locations: list[str],
        location_keywords: list[str],
        sort_by: str = "creation_time_descend",
        max_scrolls: int = 3,
        delay_between_searches_sec: float = 4,
    ) -> list[Listing]:
        results: dict[str, Listing] = {}

        with sync_playwright() as p:
            browser, page = self._launch(p)
            try:
                for search in searches:
                    for location in locations:
                        url = build_search_url(location, search, sort_by)
                        logger.info("Scanning [%s] @ %s", search.name, location)
                        try:
                            batch = self._scrape_url(page, url, search, max_scrolls)
                        except Exception:
                            logger.exception("Scrape failed for %s / %s", search.name, location)
                            batch = []

                        kept = 0
                        for listing in batch:
                            if not matches_filters(listing, search, location_keywords):
                                continue
                            kept += 1
                            # Prefer first-seen metadata; skip dupes across cities
                            results.setdefault(listing.listing_id, listing)
                        logger.info(
                            "[%s] @ %s → %d raw, %d after filters (total unique %d)",
                            search.name,
                            location,
                            len(batch),
                            kept,
                            len(results),
                        )

                        time.sleep(delay_between_searches_sec)
            finally:
                browser.close()

        return list(results.values())

    def _launch(self, p: Playwright) -> tuple[Browser, Page]:
        browser = p.chromium.launch(headless=self.headless)
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "en-CA",
            "timezone_id": "America/Toronto",
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }
        from pathlib import Path

        if Path(self.storage_state_path).exists():
            context_kwargs["storage_state"] = self.storage_state_path
        else:
            logger.warning(
                "No Facebook session at %s — run: python -m src.save_session",
                self.storage_state_path,
            )

        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return browser, page

    def _scrape_url(
        self,
        page: Page,
        url: str,
        search: SearchConfig,
        max_scrolls: int,
    ) -> list[Listing]:
        graphql_listings: dict[str, Listing] = {}

        def on_response(response) -> None:
            try:
                if "graphql" not in response.url:
                    return
                ctype = response.headers.get("content-type", "")
                if "json" not in ctype and "javascript" not in ctype:
                    return
                text = response.text()
                if "marketplace" not in text.lower() and "Marketplace" not in text:
                    # Still try parse — some payloads omit the word in body
                    if "marketplace_listing" not in text:
                        return
                # FB sometimes returns JSON lines
                for chunk in text.split("\n"):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    try:
                        payload = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    for listing in _extract_listings_from_graphql(payload, search.name):
                        graphql_listings[listing.listing_id] = listing
            except Exception as exc:
                logger.debug("GraphQL response parse skipped: %s", exc)
                return

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)

            # Dismiss common cookie / login banners if present (best-effort)
            for label in ("Allow all cookies", "Decline optional cookies", "Close"):
                try:
                    btn = page.get_by_role("button", name=label)
                    if btn.count() and btn.first.is_visible():
                        btn.first.click(timeout=1000)
                except Exception:
                    pass

            for _ in range(max_scrolls):
                page.mouse.wheel(0, 3200)
                page.wait_for_timeout(1500)

            dom_listings = _extract_listings_from_dom(page, search.name)
        finally:
            page.remove_listener("response", on_response)

        merged: dict[str, Listing] = {l.listing_id: l for l in dom_listings}
        for listing in graphql_listings.values():
            existing = merged.get(listing.listing_id)
            if existing is None:
                merged[listing.listing_id] = listing
                continue
            # Fill gaps from GraphQL without wiping good DOM prices/titles
            if (not existing.price_amount or existing.price == "Price n/a") and listing.price_amount:
                existing.price = listing.price
                existing.price_amount = listing.price_amount
            if listing.title and (
                not existing.title
                or existing.title.startswith("Listing ")
                or _is_price_line(existing.title)
            ):
                existing.title = listing.title
                existing.year = listing.year or existing.year
            if listing.location and not existing.location:
                existing.location = listing.location
            if listing.mileage_km is not None and existing.mileage_km is None:
                existing.mileage_km = listing.mileage_km

        for listing in merged.values():
            listing.search_name = search.name
            if listing.price_amount is None and listing.price:
                listing.price_amount = _parse_price_amount(listing.price)
            if listing.mileage_km is None:
                listing.mileage_km = _parse_mileage_km(
                    f"{listing.title} {listing.location}"
                )

        logger.info(
            "Found %d raw listings at %s (dom=%d graphql=%d)",
            len(merged),
            url,
            len(dom_listings),
            len(graphql_listings),
        )
        return list(merged.values())
