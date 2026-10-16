"""REALTOR.ca rental search, evidence filtering, and isolated delivery history."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
import time


class RentalAccessError(RuntimeError):
    pass


def search_url(cfg: dict) -> str:
    parsed = urlparse(cfg['search_url'])
    if parsed.scheme != 'https' or parsed.hostname != 'www.realtor.ca' or parsed.path != '/map':
        raise ValueError('Rental search_url must be https://www.realtor.ca/map#...')
    params = dict(parse_qsl(parsed.fragment))
    for key in ('LatitudeMin', 'LatitudeMax', 'LongitudeMin', 'LongitudeMax'):
        if key not in params:
            raise ValueError(f'Missing map bound: {key}')
        float(params[key])
    if cfg.get('building_type') != 'House':
        raise ValueError('Only House building type is supported')
    if not 0 < int(cfg['min_rent']) <= int(cfg['max_rent']):
        raise ValueError('Invalid rental price range')
    if int(cfg['min_bedrooms']) < 1 or int(cfg.get('max_pages', 20)) < 1:
        raise ValueError('Bedrooms and max_pages must be positive')
    params.update(TransactionTypeId='3', BuildingTypeId='1',
                  BedRange=f"{int(cfg['min_bedrooms'])}-0",
                  PriceMin=str(int(cfg['min_rent'])), PriceMax=str(int(cfg['max_rent'])),
                  PropertyTypeGroupID='1', Currency='CAD')
    return urlunparse(parsed._replace(fragment=urlencode(params)))


def amount(text: str) -> int | None:
    match = re.search(r'\$\s*([\d,]+(?:\.\d+)?)', text or '')
    return int(float(match[1].replace(',', ''))) if match else None


def bedrooms(text: str) -> int | None:
    # REALTOR.ca represents above/below-ground bedrooms as e.g. "2 + 1".
    if not re.fullmatch(r'\s*\d+(?:\s*\+\s*\d+)?\s*', text or ''):
        return None
    return sum(map(int, re.findall(r'\d+', text)))


def field(text: str, label: str) -> str:
    match = re.search(rf'(?im)^\s*{re.escape(label)}\s*:?\s*\n([^\n]+)', text)
    return match[1].strip() if match else ''


@dataclass
class Rental:
    listing_id: str
    url: str
    address: str
    rent: int | None
    beds: int | None
    building_type: str
    basement: str
    description: str
    latitude: float | None = None
    longitude: float | None = None
    source: str = "REALTOR.ca"
    mls_number: str = ""

    @classmethod
    def from_result(cls, row: dict, detail: str) -> 'Rental':
        prop = row.get('Property') or {}
        building = row.get('Building') or {}
        address = prop.get('Address') or {}
        relative = row.get('RelativeDetailsURL') or ''
        url = urljoin('https://www.realtor.ca', relative)
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'www.realtor.ca' or not re.match(r'^/real-estate/\d+(?:/|$)', parsed.path):
            raise RentalAccessError('Search returned an invalid REALTOR.ca listing URL')
        def coordinate(key):
            try:
                return float(address[key])
            except (KeyError, TypeError, ValueError):
                return None
        return cls(
            listing_id='realtor:' + str(row['Id']), url=url,
            address=str(address.get('AddressText') or '').replace('|', ', '),
            rent=amount(str(prop.get('Price') or '')) if re.search(r'/(?:monthly|month|mo)\b', str(prop.get('Price') or ''), re.I) else None,
            beds=bedrooms(str(building.get('Bedrooms') or '')),
            building_type=str(building.get('Type') or ''),
            basement=field(detail, 'Basement'),
            # Description must come from the listing, never footer or related homes.
            description=detail,
            latitude=coordinate('Latitude'), longitude=coordinate('Longitude'),
        )

    def rejection(self, cfg: dict) -> str | None:
        if self.rent is None or not cfg['min_rent'] <= self.rent <= cfg['max_rent']:
            return 'rent outside range or unknown'
        if self.beds is None or self.beds < cfg['min_bedrooms']:
            return 'bedrooms below minimum or unknown'
        if self.building_type.casefold() != 'house':
            return 'building type is not House'
        bounds = dict(parse_qsl(urlparse(cfg['search_url']).fragment))
        if (self.latitude is None or self.longitude is None or not
            (float(bounds['LatitudeMin']) <= self.latitude <= float(bounds['LatitudeMax']) and
             float(bounds['LongitudeMin']) <= self.longitude <= float(bounds['LongitudeMax']))):
            return 'outside map bounds or coordinates unknown'
        text = self.description.lower().replace('’', "'")
        if cfg.get('entire_house_only', True) and not re.search(r'\b(?:entire|whole)\s+(?:house|home)\b', text) and re.search(
            r'\b(?:basement\s+(?:apartment|unit|suite)|basement\s+(?:only|for (?:rent|lease))|'
            r'(?:main|upper|second)\s+(?:floor|level)\s+(?:only|for (?:rent|lease))|basement\s+(?:is\s+)?(?:not included|excluded))\b', text
        ):
            return 'partial house rental'
        finished = re.search(r'\b(?:fully\s+)?finished\s+(?:\w+\s+){0,2}basement\b|\bbasement\s*[:\-]?\s*(?:is\s+)?(?:fully\s+)?finished\b', text)
        basement_finished = re.search(r'\bfinished\b', self.basement.lower())
        negative_basement = re.search(r'\b(?:unfinished|partially finished|not finished)\b', self.basement.lower()) or re.search(
            r'\b(?:unfinished|partially finished|not (?:fully )?finished|no finished|not a finished)\s+basement\b|\bbasement\s+(?:is\s+)?(?:unfinished|not finished|partially finished)\b', text)
        if cfg.get('require_finished_basement', True) and (negative_basement or not (finished or basement_finished)):
            return 'finished basement not confirmed'
        entrance = re.search(r'\b(?:separat[ea]|private|independent)\s+(?:side\s+|basement\s+)?(?:entrance|entry)\b|\bsep\.?\s+(?:entrance|entry)\b', text)
        negative_entrance = re.search(r'\b(?:no|without|not (?:a |an )?)\s*(?:separat[ea]|private|independent)\s+(?:side\s+|basement\s+)?(?:entrance|entry)\b|\b(?:separate entrance|separate entry)\s+(?:is\s+)?(?:not|unavailable|prohibited)\b', text)
        conditional_entrance = re.search(
            r'\b(?:potential|possibility|option)\s+(?:for\s+)?(?:a\s+)?separate\s+(?:entrance|entry)\b|'
            r'\bseparate\s+(?:entrance|entry)\s+(?:can|could|may|will)\s+be\s+(?:added|built|created)\b', text)
        if cfg.get('require_separate_entrance', True) and (negative_entrance or conditional_entrance or not entrance):
            return 'separate entrance not confirmed'
        return None

    def telegram_message(self) -> str:
        return '\n'.join([
            f'🏠 <b>House rental · {escape(self.source)}</b>', escape(self.address),
            f'MLS: {escape(self.mls_number)}' if self.mls_number else '',
            f'💰 CAD ${self.rent:,}/month · {self.beds} bedrooms',
            'Finished basement and separate entrance stated in listing.',
            f'<a href="{escape(self.url, quote=True)}">Open listing</a>',
        ])


def check_access(page, response=None) -> None:
    text = page.locator('body').inner_text()
    if (response is not None and response.status >= 400) or re.search(
        r'sorry, you have been blocked|verify you are human|access denied|captcha|pardon our interruption', text, re.I
    ):
        raise RentalAccessError('REALTOR.ca blocked automated access. No listings were verified.')


def scrape_realtor(cfg: dict, *, headless: bool = True) -> tuple[list[Rental], dict[str, int]]:
    """Read the site's own search responses; fail if the search cannot be verified."""
    from collections import Counter
    from playwright.sync_api import sync_playwright
    url = search_url(cfg)
    rejected = Counter()
    rows = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            page.set_default_timeout(int(cfg.get('timeout_ms', 60000)))
            batches = []
            def on_response(response):
                if 'PropertySearch' not in urlparse(response.url).path or urlparse(response.url).hostname not in {'www.realtor.ca', 'api.realtor.ca', 'api2.realtor.ca'}:
                    return
                if response.status != 200:
                    return
                try:
                    data = response.json()
                    if isinstance(data, dict) and isinstance(data.get('Results'), list):
                        batches.append(data)
                except Exception:
                    pass
            page.on('response', on_response)
            response = page.goto(url, wait_until='domcontentloaded')
            check_access(page, response)
            for index in range(int(cfg.get('max_pages', 20))):
                deadline = time.monotonic() + int(cfg.get('timeout_ms', 60000)) / 1000
                while not batches and time.monotonic() < deadline:
                    page.wait_for_timeout(250)
                check_access(page)
                if not batches:
                    raise RentalAccessError('REALTOR.ca did not return a verified search response')
                batch = batches[-1]
                batches.clear()
                for row in batch['Results']:
                    rows[str(row['Id'])] = row
                paging = batch.get('Paging') or {}
                try:
                    current, total = int(paging['CurrentPage']), int(paging['TotalPages'])
                except (KeyError, TypeError, ValueError):
                    raise RentalAccessError('Search pagination missing; completeness could not be verified')
                if current >= total:
                    break
                if index + 1 >= int(cfg.get('max_pages', 20)):
                    raise RentalAccessError('Rental search exceeded max_pages; increase it to check all results')
                # Pagination is performed through the public UI, not a private API.
                next_page = page.get_by_role('link', name='Next', exact=True)
                if next_page.count() != 1:
                    raise RentalAccessError('Cannot locate the next results page')
                next_page.click()
            detail_page = browser.new_page()
            matches = []
            for row in rows.values():
                # Validate the URL and cheap structured filters before opening details.
                candidate = Rental.from_result(row, '')
                preliminary = candidate.rejection({**cfg, 'require_finished_basement': False, 'require_separate_entrance': False})
                if preliminary:
                    rejected[preliminary] += 1
                    continue
                response = detail_page.goto(candidate.url, wait_until='domcontentloaded')
                check_access(detail_page, response)
                # Stop before related homes/footer so their text cannot satisfy filters.
                text = detail_page.locator('body').inner_text()
                text = re.split(r'(?im)^\s*(?:Similar Listings|Similar Properties|You May Also Like|Trusted listings from)\s*$', text)[0]
                candidate = Rental.from_result(row, text)
                reason = candidate.rejection(cfg)
                if reason:
                    rejected[reason] += 1
                else:
                    matches.append(candidate)
                detail_page.wait_for_timeout(1500)
            return matches, dict(rejected)
        finally:
            browser.close()


def scrape(cfg: dict, *, headless: bool = True) -> tuple[list[Rental], dict[str, int]]:
    search_url(cfg)
    source = cfg.get('source', 'royallepage')
    if source == 'royallepage':
        from .rental_royallepage import scrape as scrape_public_rentals
        return scrape_public_rentals(cfg)
    if source == 'realtor':
        return scrape_realtor(cfg, headless=headless)
    raise ValueError(f'Unknown rental source: {source}')
