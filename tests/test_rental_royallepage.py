from pathlib import Path
import unittest
from unittest.mock import patch, Mock

import yaml

from src.rental_royallepage import parse_search, parse_detail, scrape
from src.rentals import RentalAccessError

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / 'rental-config.yaml').read_text())
URL = 'https://www.royallepage.ca/en/property/ontario/toronto/example/123/mlsw123/'


def search_html(next_page=False, weekly=False, wrong_filters=False):
    return f'''<form id="property-search-form">
    <input name="transactionType" value="{'SALE' if wrong_filters else 'LEASE'}">
    <input name="property_type" value="7">
    <select name="min_leaseprice"><option selected value="2000"></option></select>
    <select name="max_leaseprice"><option selected value="4100"></option></select>
    <select name="beds"><option selected value="2+"></option></select></form>
    <h2 id="seo-heading">1 Rental in Toronto</h2>
    <div class="js-listing" data-id="123"><span class="price">$3,200.00/{'week' if weekly else 'month'}</span>
    <div class="address-1"><a href="{URL}">Example address</a></div>
    <span data-lat="43.774075" data-lng="-79.472576"></span>
    <div class="listing-meta">House 2 bds , 1 bth</div></div>
    {'<a class="paginator__button next" href="/en/on/toronto/rentals/properties/2/"></a>' if next_page else ''}'''


def detail_html(transaction='LEASE'):
    return f'''<div id="rlp-data" data-transaction-type="{transaction}" data-price="3200.00"
    data-lat="43.774075" data-lng="-79.472576" data-listingid="123" data-mls="W123"
    data-address="Example address" data-beds="2+1"></div>
    <h4>Property Information:</h4><p>Entire house for lease.</p>
    <ul class="property-features-list">
    <li><span class="label">Building Type:</span><span class="value">House</span></li>
    <li><span class="label">Basement Type:</span><span class="value">Finished</span></li>
    <li><span class="label">Basement Features:</span><span class="value">Separate entrance</span></li></ul>
    <aside>Similar properties: unfinished basements.</aside>'''


class RoyalLePageTests(unittest.TestCase):
    def test_card_parsing_and_pagination(self):
        rows, nxt = parse_search(search_html(next_page=True), CFG)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['rent'], 3200)
        self.assertEqual(rows[0]['beds'], 2)
        self.assertEqual(rows[0]['latitude'], 43.774075)
        self.assertTrue(nxt.endswith('/properties/2/'))
        rows, _ = parse_search(search_html(weekly=True), CFG)
        self.assertIsNone(rows[0]['rent'])

    def test_failures_and_ignored_filters_cannot_be_reported_as_empty(self):
        for html in ('<h1>Blocked</h1>', search_html(wrong_filters=True),
                     search_html().replace('1 Rental', '1,000+ Rentals')):
            with self.subTest(html=html[:50]):
                with self.assertRaises(RentalAccessError):
                    parse_search(html, CFG)

    def test_details_use_structured_fields_and_exclude_unrelated_content(self):
        rental = parse_detail(detail_html(), URL)
        self.assertEqual(rental.listing_id, 'royallepage:123')
        self.assertEqual(rental.mls_number, 'W123')
        self.assertEqual(rental.beds, 3)
        self.assertEqual(rental.rent, 3200)
        self.assertIsNone(rental.rejection(CFG))
        self.assertNotIn('Similar properties', rental.description)
        self.assertIn('Royal LePage', rental.telegram_message())
        with self.assertRaises(RentalAccessError):
            parse_detail(detail_html(transaction='SALE'), URL)

    def test_scanner_reads_details_and_preserves_original_location_constraint(self):
        client = Mock()
        def response(text, url):
            return Mock(status_code=200, text=text, url=url)
        client.get.side_effect = [response(search_html(), 'https://www.royallepage.ca/en/on/toronto/rentals/properties/'), response(detail_html(), URL)]
        with patch('src.rental_royallepage.httpx.Client') as ctor, patch('src.rental_royallepage.time.sleep'):
            ctor.return_value.__enter__.return_value = client
            matches, rejected = scrape(CFG)
        self.assertEqual(len(matches), 1)
        self.assertEqual(rejected, {})
        client.get.side_effect = [response(search_html().replace('43.774075', '44.0'), 'https://www.royallepage.ca/en/on/toronto/rentals/properties/')]
        with patch('src.rental_royallepage.httpx.Client') as ctor:
            ctor.return_value.__enter__.return_value = client
            matches, rejected = scrape(CFG)
        self.assertEqual(matches, [])
        self.assertEqual(rejected['outside selected map area'], 1)

    def test_incomplete_pagination_does_not_send_partial_results(self):
        client = Mock()
        client.get.return_value = Mock(status_code=200, text=search_html(next_page=True).replace('43.774075', '44.0'), url='https://www.royallepage.ca/en/on/toronto/rentals/properties/')
        with patch('src.rental_royallepage.httpx.Client') as ctor, patch('src.rental_royallepage.time.sleep'):
            ctor.return_value.__enter__.return_value = client
            with self.assertRaises(RentalAccessError):
                scrape({**CFG, 'max_pages': 1})
