"""Read Royal LePage's public MLS rental pages without a browser or login."""
from __future__ import annotations

from collections import Counter
import logging
import re
import time
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from .rentals import Rental, RentalAccessError, amount, bedrooms

BASE = 'https://www.royallepage.ca'
SEARCH_PATH = '/en/on/toronto/rentals/properties/'
logger = logging.getLogger(__name__)


def checked_url(value: str, *, listing: bool = False) -> str:
    url = urljoin(BASE, value)
    parsed = urlparse(url)
    prefix = '/en/property/ontario/' if listing else SEARCH_PATH
    if parsed.scheme != 'https' or parsed.hostname != 'www.royallepage.ca' or not parsed.path.startswith(prefix):
        raise RentalAccessError('Royal LePage returned an unexpected URL')
    return url


def filters(cfg: dict) -> dict[str, str]:
    return {
        'transactionType': 'LEASE', 'property_type': '7',
        'min_leaseprice': str(cfg['min_rent']), 'max_leaseprice': str(cfg['max_rent']),
        'beds': f"{cfg['min_bedrooms']}+", 'sortby': 'date',
    }


def parse_search(html: str, cfg: dict) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(html, 'html.parser')
    form = soup.select_one('#property-search-form')
    if form is None:
        raise RentalAccessError('Royal LePage search form missing; results not verified')
    # The server must confirm that this is the requested rental search.
    for name, expected in filters(cfg).items():
        if name == 'sortby':
            continue
        control = form.find(attrs={'name': name})
        if control is None:
            raise RentalAccessError(f'Royal LePage search filter missing: {name}')
        selected = control.select_one('option[selected]') if control.name == 'select' else control
        if selected is None or str(selected.get('value', '')).strip() != expected:
            raise RentalAccessError(f'Royal LePage did not apply search filter: {name}')
    heading = soup.select_one('#seo-heading')
    # Do not claim complete coverage when the provider truncates its results.
    if heading and re.search(r'1,?000\s*\+', heading.get_text()):
        raise RentalAccessError('Royal LePage search is capped at 1,000 results; narrow the source search')
    cards = soup.select('.js-listing[data-id]')
    if not cards and 'No Results Were Found' not in soup.get_text(' ', strip=True):
        raise RentalAccessError('Royal LePage returned neither listings nor a verified empty search')
    rows = []
    for card in cards:
        link = card.select_one('.address-1 a[href]')
        location = card.select_one('[data-lat][data-lng]')
        price = card.select_one('.price')
        meta = card.select_one('.listing-meta')
        if not all((link, location, price, meta)):
            raise RentalAccessError('Royal LePage listing card is incomplete')
        price_text = price.get_text('', strip=True)
        monthly = bool(re.search(r'/\s*month\b', price_text, re.I))
        bed_match = re.search(r'(\d+(?:\s*\+\s*\d+)?)\s*(?:bed|bd)', meta.get_text(' ', strip=True), re.I)
        rows.append({
            'id': str(card['data-id']), 'url': checked_url(link['href'], listing=True),
            'address': link.get_text(' ', strip=True), 'rent': amount(price_text) if monthly else None,
            'beds': bedrooms(bed_match[1]) if bed_match else None,
            'latitude': float(location['data-lat']), 'longitude': float(location['data-lng']),
        })
    next_link = soup.select_one('a.paginator__button.next[href]')
    return rows, checked_url(next_link['href']) if next_link else None


def parse_detail(html: str, url: str) -> Rental:
    soup = BeautifulSoup(html, 'html.parser')
    data = soup.select_one('#rlp-data')
    if data is None:
        raise RentalAccessError('Royal LePage listing details unavailable; scan incomplete')
    if data.get('data-transaction-type') != 'LEASE':
        raise RentalAccessError('Rental listing is no longer available for lease')
    features = {}
    for item in soup.select('.property-features-list li'):
        label, value = item.select_one('.label'), item.select_one('.value')
        if label is not None and value is not None:
            features[label.get_text(' ', strip=True).rstrip(':')] = value.get_text(' ', strip=True)
    heading = soup.find('h4', string=re.compile(r'^\s*Property Information:\s*$'))
    paragraph = heading.find_next_sibling('p') if heading else None
    if paragraph is None:
        raise RentalAccessError('Royal LePage property description missing')
    basement = features.get('Basement Type', '')
    entrance = features.get('Basement Features', '')
    description = paragraph.get_text(' ', strip=True)
    # Only the description and this home's structured basement fields count.
    evidence = f'{description}\nBasement\n{basement}\nBasement Features\n{entrance}'
    try:
        rent = int(float(data['data-price']))
        latitude, longitude = float(data['data-lat']), float(data['data-lng'])
        listing_id = 'royallepage:' + data['data-listingid']
    except (KeyError, TypeError, ValueError) as exc:
        raise RentalAccessError('Royal LePage listing has missing or invalid details') from exc
    return Rental(
        listing_id=listing_id, url=checked_url(url, listing=True),
        address=str(data.get('data-address', '')), rent=rent,
        beds=bedrooms(str(data.get('data-beds', ''))),
        building_type=features.get('Building Type', ''), basement=basement,
        description=evidence, latitude=latitude, longitude=longitude,
        source='Royal LePage · MLS', mls_number=str(data.get('data-mls', '')),
    )


def scrape(cfg: dict) -> tuple[list[Rental], dict[str, int]]:
    bounds = dict(parse_qsl(urlparse(cfg['search_url']).fragment))
    rejected = Counter()
    matches = []
    delay = float(cfg.get('request_delay_seconds', 1))
    max_pages = int(cfg.get('max_pages', 30))
    url = str(httpx.URL(BASE + SEARCH_PATH, params=filters(cfg)))
    visited, seen = set(), set()
    with httpx.Client(timeout=int(cfg.get('timeout_ms', 60000)) / 1000, follow_redirects=True) as client:
        def get(target):
            response = client.get(target)
            if response.status_code != 200:
                raise RentalAccessError(f'Royal LePage returned HTTP {response.status_code}; scan incomplete')
            checked_url(str(response.url), listing='/en/property/' in urlparse(target).path)
            return response.text
        for page in range(max_pages):
            if url in visited:
                raise RentalAccessError('Royal LePage pagination repeated a page')
            visited.add(url)
            rows, next_url = parse_search(get(url), cfg)
            logger.info('Royal LePage page %d: %d rental cards', page + 1, len(rows))
            for row in rows:
                if row['id'] in seen:
                    continue
                seen.add(row['id'])
                if not (float(bounds['LatitudeMin']) <= row['latitude'] <= float(bounds['LatitudeMax']) and
                        float(bounds['LongitudeMin']) <= row['longitude'] <= float(bounds['LongitudeMax'])):
                    rejected['outside selected map area'] += 1
                    continue
                if row['rent'] is None or not cfg['min_rent'] <= row['rent'] <= cfg['max_rent']:
                    rejected['monthly rent outside range or unknown'] += 1
                    continue
                if row['beds'] is None or row['beds'] < cfg['min_bedrooms']:
                    rejected['bedrooms below minimum or unknown'] += 1
                    continue
                # Read details only for geographically relevant cards.
                time.sleep(delay)
                rental = parse_detail(get(row['url']), row['url'])
                reason = rental.rejection(cfg)
                if reason:
                    rejected[reason] += 1
                else:
                    matches.append(rental)
            if not next_url:
                logger.info('Verified %d unique rental cards across %d pages', len(seen), len(visited))
                return matches, dict(rejected)
            url = next_url
            time.sleep(delay)
    raise RentalAccessError('Royal LePage search exceeded max_pages; scan incomplete')
