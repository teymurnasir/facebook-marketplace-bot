from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .models import Listing, SearchConfig
from .listing_details import classify_safety

logger = logging.getLogger(__name__)

ITEM_ID_RE = re.compile(r"/marketplace/item/(\d+)")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
HYBRID_RE = re.compile(r"\b(?:hybrid|hev|phev)\b", re.IGNORECASE)
HYBRID_QUERY_RE = re.compile(r"\b(?:hybrid|hev|phev|huv)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"[\d,]+")
MILEAGE_RE = re.compile(
    r"(\d(?:[\d.,\s\u00a0]*\d)?)\s*(km|kilometers?|kilometres?|miles?|mi)\b",
    re.IGNORECASE,
)


# Facebook Marketplace URL `radius` is in miles. Map user km → nearest FB mile option.
_FB_RADIUS_MILES = (1, 2, 5, 10, 20, 40, 60, 80, 100, 250, 500)


class FacebookSessionError(RuntimeError):
    """Raised when Facebook redirects the browser to login/checkpoint pages."""


def _desktop_chrome_user_agent(chrome_version: str) -> str:
    version = (chrome_version or "120.0.0.0").split()[0]
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version} Safari/537.36"
    )


def km_to_facebook_radius_miles(radius_km: int | float | None) -> int:
    if radius_km is None or radius_km <= 0:
        return 40  # ~65 km, FB default-ish
    miles_approx = float(radius_km) / 1.60934
    return min(_FB_RADIUS_MILES, key=lambda m: abs(m - miles_approx))


def build_search_url(
    location_slug: str,
    search: SearchConfig,
    sort_by: str,
    *,
    query: str | None = None,
    mode: str = "search",
    radius_km: int | None = None,
) -> str:
    params = {
        "query": query or search.query,
        "minPrice": search.min_price,
        "maxPrice": search.max_price,
        "minYear": search.min_year,
        "maxYear": search.max_year,
        "exact": "false",
        "sortBy": sort_by,
        "radius": km_to_facebook_radius_miles(radius_km),
    }
    if search.max_mileage_km is not None:
        # Marketplace vehicle mileage filter (when supported by the UI)
        params["maxMileage"] = search.max_mileage_km
    if mode == "vehicles":
        base = f"https://www.facebook.com/marketplace/{location_slug}/vehicles"
    else:
        base = f"https://www.facebook.com/marketplace/{location_slug}/search"
    return f"{base}?{urlencode(params)}"


def _normalize_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _text_matches_any(hay: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = hay.lower()
    compact = _normalize_alnum(hay)
    for needle in needles:
        n = (needle or "").strip().lower()
        if not n:
            continue
        if n in low or _normalize_alnum(n) in compact:
            return True
    return False


def _text_matches_all(hay: str, needles: list[str]) -> bool:
    if not needles:
        return True
    return all(_text_matches_any(hay, [n]) for n in needles)


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
        card_bits: list[str] = [title.strip()]
        subs = candidate.get("custom_sub_titles_with_rendering_flags") or []
        if isinstance(subs, list):
            for sub in subs:
                if isinstance(sub, dict) and sub.get("subtitle"):
                    card_bits.append(str(sub["subtitle"]))
                elif isinstance(sub, str):
                    card_bits.append(sub)

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
            card_text=" ".join(card_bits),
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
            card_text = " ".join(lines)
            non_price = [
                ln
                for ln in lines
                if ln not in price_lines
                and not YEAR_RE.fullmatch(ln)
                and not _is_mileage_line(ln)
            ]
            title = next((ln for ln in non_price if YEAR_RE.search(ln)), None)
            if not title:
                title = next((ln for ln in non_price if len(ln) > 3), None)
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
                card_text=card_text,
            )
        except Exception as exc:
            logger.debug("DOM card parse skipped: %s", exc)
            continue
    return list(found.values())


def _query_tokens_match(hay: str, query: str) -> bool:
    """
    Multi-word queries must match as a phrase/compact form, or include every
    significant token (len>=3). Prevents "kia forte" matching "kia sorento".
    """
    q = (query or "").strip().lower()
    if not q:
        return True
    low = hay.lower()
    compact_hay = _normalize_alnum(hay)
    compact_q = _normalize_alnum(q)
    if q in low or (compact_q and compact_q in compact_hay):
        return True
    words = [w for w in re.split(r"\s+", q) if len(w) >= 3]
    if len(words) >= 2:
        return _text_matches_all(hay, words)
    return _text_matches_any(hay, [q])


def _query_matches_search(hay: str, search: SearchConfig) -> bool:
    hybrid = bool(HYBRID_QUERY_RE.search(search.query) or search.powertrain_any)
    return any(
        _query_tokens_match(hay, HYBRID_QUERY_RE.sub("", query).strip() if hybrid else query)
        for query in search.all_queries()
    )


def filter_rejection_reason(
    listing: Listing,
    search: SearchConfig,
    location_keywords: list[str],
) -> str | None:
    hay = listing.haystack()
    model_hay = f"{listing.title} {listing.card_text}"

    if search.must_include_any and not _text_matches_any(model_hay, search.must_include_any):
        return "model_keywords"

    if search.must_include_all and not _text_matches_all(hay, search.must_include_all):
        return "required_keywords"

    # Broad query variants must still include evidence of the requested powertrain.
    if not _query_matches_search(model_hay, search):
        return "query_mismatch"

    if search.require_body_style and search.body_styles:
        if not _text_matches_any(hay, search.body_styles):
            return "body_style"

    if listing.year is not None:
        if listing.year < search.min_year or listing.year > search.max_year:
            return "year_out_of_range"

    if listing.price_amount is not None:
        if listing.price_amount < search.min_price or listing.price_amount > search.max_price:
            return "price_out_of_range"

    if search.require_mileage and listing.mileage_km is None:
        return "mileage_missing"

    if search.max_mileage_km is not None and listing.mileage_km is not None:
        if listing.mileage_km > search.max_mileage_km:
            return "mileage_too_high"

    if location_keywords:
        loc = (listing.location or "").strip().lower()
        # Empty / generic location: keep (FB often omits city on cards)
        if loc and loc not in {"ontario", "on", "canada"}:
            if not any(k.lower() in loc for k in location_keywords):
                return "location_out_of_area"

    if HYBRID_QUERY_RE.search(search.query):
        if re.search(r"\b(?:not|non)[ -]+(?:a\s+)?hybrid\b", hay, re.IGNORECASE):
            return "hybrid_not_confirmed"
        if not HYBRID_RE.search(hay):
            return "hybrid_not_confirmed"
    if search.powertrain_any and not _text_matches_any(hay, search.powertrain_any):
        return "powertrain_keywords"

    return None


def matches_filters(listing: Listing, search: SearchConfig, location_keywords: list[str]) -> bool:
    return filter_rejection_reason(listing, search, location_keywords) is None


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
        self.session_verified = False
        self.search_diagnostics: list[dict[str, Any]] = []

    def run_cycle(
        self,
        searches: list[SearchConfig],
        locations: list[str],
        location_keywords: list[str],
        sort_by: str = "creation_time_descend",
        max_scrolls: int = 7,
        delay_between_searches_sec: float = 2.5,
        url_modes: list[str] | None = None,
        search_mode_locations: list[str] | None = None,
        market_areas: list[dict[str, Any]] | None = None,
        on_session_active: Callable[[], None] | None = None,
        detail_cache: dict[str, dict[str, Any]] | None = None,
        max_detail_pages: int = 30,
    ) -> list[Listing]:
        self.session_verified = False
        self.search_diagnostics = []
        observations: dict[str, dict[str, str | None]] = {search.name: {} for search in searches}
        logged_rejections: Counter = Counter()
        checked_details: dict[str, Listing] = {}
        detail_attempts = 0
        cached_details = detail_cache or {}
        results: dict[str, Listing] = {}
        successful_pages = 0
        failed_pages = 0
        modes = url_modes or ["vehicles", "search"]
        search_hubs = set(search_mode_locations or [])

        areas: list[dict[str, Any]] = list(market_areas or [])
        if not areas:
            areas = [{"slug": slug, "radius_km": 65} for slug in locations]

        session_healthy = True
        with sync_playwright() as p:
            browser, context, page = self._launch(p)
            try:
                for search in searches:
                    for query in search.all_queries():
                        for area in areas:
                            location = str(area.get("slug") or "").strip()
                            if not location:
                                continue
                            radius_km = area.get("radius_km", 65)
                            try:
                                radius_km = int(radius_km)
                            except (TypeError, ValueError):
                                radius_km = 65
                            for mode in modes:
                                if (
                                    mode == "search"
                                    and search_hubs
                                    and location not in search_hubs
                                ):
                                    continue
                                url = build_search_url(
                                    location,
                                    search,
                                    sort_by,
                                    query=query,
                                    mode=mode,
                                    radius_km=radius_km,
                                )
                                logger.info(
                                    "Scanning [%s] q=%r @ %s r=%skm (%s)",
                                    search.name,
                                    query,
                                    location,
                                    radius_km,
                                    mode,
                                )
                                try:
                                    batch = self._scrape_url(page, url, search, max_scrolls)
                                    successful_pages += 1
                                except FacebookSessionError:
                                    session_healthy = False
                                    raise
                                except Exception:
                                    failed_pages += 1
                                    logger.exception(
                                        "Scrape failed for %s / %s / %s",
                                        search.name,
                                        location,
                                        mode,
                                    )
                                    batch = []

                                if not self.session_verified and self._has_authenticated_data(page, batch):
                                    self.session_verified = True
                                    logger.info("Facebook session active: authenticated Marketplace data verified")
                                    if on_session_active is not None:
                                        on_session_active()

                                kept = 0
                                for listing in batch:
                                    reason = filter_rejection_reason(listing, search, location_keywords)
                                    if reason in {None, "hybrid_not_confirmed", "powertrain_keywords"}:
                                        previous = checked_details.get(listing.listing_id)
                                        if previous is not None:
                                            self._copy_details(listing, previous)
                                        elif self._restore_details(listing, cached_details.get(listing.listing_id)):
                                            checked_details[listing.listing_id] = listing
                                        elif detail_attempts < max_detail_pages:
                                            detail_attempts += 1
                                            try:
                                                self._read_details(context, listing)
                                            except FacebookSessionError:
                                                session_healthy = False
                                                raise
                                            except Exception:
                                                logger.exception("Could not read seller description for %s", listing.listing_id)
                                            checked_details[listing.listing_id] = listing
                                            time.sleep(delay_between_searches_sec)
                                        reason = filter_rejection_reason(listing, search, location_keywords)
                                    seen = observations[search.name]
                                    if listing.listing_id not in seen or reason is None:
                                        seen[listing.listing_id] = reason
                                    if reason is not None:
                                        key = (search.name, reason)
                                        if logged_rejections[key] < 3:
                                            logger.info(
                                                "Rejected [%s] reason=%s title=%r price=%r year=%s mileage=%s",
                                                search.name, reason, listing.title, listing.price,
                                                listing.year, listing.mileage_km,
                                            )
                                            logged_rejections[key] += 1
                                        continue
                                    kept += 1
                                    prev = results.get(listing.listing_id)
                                    if prev is None:
                                        results[listing.listing_id] = listing
                                    else:
                                        # Merge richer fields from later hits
                                        if listing.mileage_km and not prev.mileage_km:
                                            prev.mileage_km = listing.mileage_km
                                        if listing.card_text and len(listing.card_text) > len(
                                            prev.card_text or ""
                                        ):
                                            prev.card_text = listing.card_text
                                        if listing.location and not prev.location:
                                            prev.location = listing.location
                                        if listing.details_checked_at:
                                            self._copy_details(prev, listing)
                                logger.info(
                                    "[%s] q=%r @ %s/%s r=%skm → %d raw, %d kept (unique %d)",
                                    search.name,
                                    query,
                                    location,
                                    mode,
                                    radius_km,
                                    len(batch),
                                    kept,
                                    len(results),
                                )

                                time.sleep(delay_between_searches_sec)
            finally:
                if session_healthy and self.session_verified:
                    self._save_storage_state(context)
                browser.close()

        if failed_pages and not successful_pages:
            raise RuntimeError("All Marketplace pages failed to load; Facebook status could not be verified.")
        for name, seen in observations.items():
            stats = {
                "name": name, "inspected": len(seen),
                "matched": sum(reason is None for reason in seen.values()),
                "rejected": dict(Counter(reason for reason in seen.values() if reason is not None)),
            }
            self.search_diagnostics.append(stats)
            logger.info("Search diagnostics: %s", json.dumps(stats))
        return list(results.values())

    @staticmethod
    def _copy_details(listing: Listing, previous: Listing) -> None:
        for field in ("description", "safety", "safety_evidence", "details_checked_at"):
            setattr(listing, field, getattr(previous, field))
        if listing.mileage_km is None:
            listing.mileage_km = previous.mileage_km

    @staticmethod
    def _restore_details(listing: Listing, saved: dict[str, Any] | None) -> bool:
        if not saved or not saved.get("details_checked_at"):
            return False
        try:
            checked = datetime.fromisoformat(saved["details_checked_at"])
            now = datetime.now(timezone.utc)
            if checked.tzinfo is None or not timedelta(0) <= now - checked < timedelta(hours=24):
                return False
        except (TypeError, ValueError):
            return False
        listing.description = saved.get("description") or ""
        listing.safety, listing.safety_evidence = classify_safety(listing.description)
        listing.details_checked_at = saved["details_checked_at"]
        if listing.mileage_km is None:
            listing.mileage_km = saved.get("mileage_km")
        return True

    def _read_details(self, context: BrowserContext, listing: Listing) -> None:
        detail = context.new_page()
        descriptions: list[str] = []

        def collect(payload: Any) -> None:
            for node in _walk(payload):
                if str(node.get("id") or node.get("listing_id") or "") != listing.listing_id:
                    continue
                for key in ("redacted_description", "description", "listing_description"):
                    value = node.get(key)
                    if isinstance(value, dict):
                        value = value.get("text")
                    if isinstance(value, str) and value.strip():
                        descriptions.append(value.strip())

        def response_received(response) -> None:
            if "graphql" not in response.url:
                return
            try:
                for line in response.text().splitlines():
                    try:
                        collect(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            except Exception:
                return

        detail.on("response", response_received)
        try:
            detail.goto(
                f"https://www.facebook.com/marketplace/item/{listing.listing_id}",
                wait_until="domcontentloaded", timeout=self.timeout_ms,
            )
            detail.wait_for_timeout(2000)
            self._raise_if_session_problem(detail)
            dom_description = detail.evaluate("""() => {
                const roots = [...document.querySelectorAll('[role="main"], [role="dialog"]')];
                for (const root of roots) {
                    const lines = (root.innerText || '').split(/\\n/).map(s => s.trim());
                    const start = lines.findIndex(s => /^(description|seller.s description|təsvir|açıqlama)$/i.test(s));
                    if (start < 0) continue;
                    const endLabels = /^(seller information|seller details|location|details|satıcı haqqında məlumat|satıcı məlumatları|yer|təfərrüatlar)$/i;
                    const result = [];
                    for (const line of lines.slice(start + 1)) {
                        if (endLabels.test(line)) break;
                        if (/^(see more|see less|daha çox|daha az)$/i.test(line)) continue;
                        result.push(line);
                    }
                    if (result.join(' ').trim()) return result.join('\\n').slice(0, 12000);
                }
                return '';
            }""")
            for script in detail.locator('script[type="application/json"]').all()[:50]:
                try:
                    collect(json.loads(script.text_content(timeout=1000) or "{}"))
                except Exception:
                    continue
            if isinstance(dom_description, str) and dom_description.strip():
                descriptions.append(dom_description.strip())
            if not descriptions:
                logger.info("Seller description unavailable for %s; safety unknown", listing.listing_id)
                return
            listing.description = max(descriptions, key=len)[:12000]
            listing.safety, listing.safety_evidence = classify_safety(listing.description)
            listing.details_checked_at = datetime.now(timezone.utc).isoformat()
            if listing.mileage_km is None:
                listing.mileage_km = _parse_mileage_km(listing.description)
            logger.info("Seller description checked for %s: safety=%s mileage=%s", listing.listing_id,
                        listing.safety, listing.mileage_km)
        finally:
            detail.remove_listener("response", response_received)
            detail.close()

    def _has_authenticated_data(self, page: Page, listings: list[Listing]) -> bool:
        # A saved cookie or an empty page alone does not prove Marketplace access.
        target = urlparse(page.url)
        if not listings or target.hostname not in {"facebook.com", "www.facebook.com"}:
            return False
        if not target.path.startswith("/marketplace/"):
            return False
        return any(
            cookie.get("name") == "c_user" and cookie.get("value")
            for cookie in page.context.cookies(["https://www.facebook.com/"])
        )

    def _launch(self, p: Playwright) -> tuple[Browser, BrowserContext, Page]:
        browser = p.chromium.launch(headless=self.headless)
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 1280, "height": 900},
            "locale": "en-CA",
            "timezone_id": "America/Toronto",
            "user_agent": _desktop_chrome_user_agent(browser.version),
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
        return browser, context, page

    def _save_storage_state(self, context: BrowserContext) -> None:
        from pathlib import Path

        path = Path(self.storage_state_path)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            context.storage_state(path=str(path))
            logger.info("Saved refreshed Facebook session → %s", path)
        except Exception:
            logger.exception("Could not save refreshed Facebook session state")

    def _raise_if_session_problem(self, page: Page) -> None:
        url = page.url.lower()
        if "/login" in url or "/checkpoint" in url:
            raise FacebookSessionError(
                "Facebook session is no longer valid. "
                "Refresh it with: python3 -m src.save_session"
            )
        try:
            login_text = page.get_by_text("Log in to Facebook", exact=False)
            if login_text.count() and login_text.first.is_visible(timeout=1000):
                raise FacebookSessionError(
                    "Facebook is showing the login page. "
                    "Refresh the saved session with: python3 -m src.save_session"
                )
        except FacebookSessionError:
            raise
        except Exception:
            pass

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
            self._raise_if_session_problem(page)

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

            self._raise_if_session_problem(page)
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
            if listing.card_text and len(listing.card_text) > len(existing.card_text or ""):
                existing.card_text = listing.card_text

        for listing in merged.values():
            listing.search_name = search.name
            if listing.price_amount is None and listing.price:
                listing.price_amount = _parse_price_amount(listing.price)
            blob = f"{listing.title} {listing.location} {listing.card_text}"
            if listing.mileage_km is None:
                listing.mileage_km = _parse_mileage_km(blob)

        logger.info(
            "Found %d raw listings at %s (dom=%d graphql=%d)",
            len(merged),
            url,
            len(dom_listings),
            len(graphql_listings),
        )
        return list(merged.values())
