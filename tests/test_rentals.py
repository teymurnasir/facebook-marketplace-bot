from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlparse

import yaml

from rental_main import deliver
from src.rentals import Rental, RentalAccessError, bedrooms, search_url

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / 'rental-config.yaml').read_text())


def result():
    return {
        'Id': '123', 'RelativeDetailsURL': '/real-estate/123/example-house',
        'Property': {'Price': '$3,200/Monthly', 'Address': {
            'AddressText': '1 Example Street|Toronto, Ontario',
            'Latitude': '43.774075', 'Longitude': '-79.472576'}},
        'Building': {'Type': 'House', 'Bedrooms': '2 + 1'},
    }


def listing(text='Entire house for rent. Finished basement with separate entrance.'):
    return Rental.from_result(result(), text)


class RentalTests(unittest.TestCase):
    def test_url_corrects_sale_and_keeps_original_bounds(self):
        params = dict(parse_qsl(urlparse(search_url(CFG)).fragment))
        original = dict(parse_qsl(urlparse(CFG['search_url']).fragment))
        self.assertEqual(params['TransactionTypeId'], '3')
        self.assertEqual(params['BuildingTypeId'], '1')
        self.assertEqual(params['BedRange'], '2-0')
        self.assertEqual(params['PriceMin'], '2000')
        self.assertEqual(params['PriceMax'], '4100')
        for key in ('LatitudeMin', 'LatitudeMax', 'LongitudeMin', 'LongitudeMax'):
            self.assertEqual(params[key], original[key])

    def test_strict_matching(self):
        self.assertIsNone(listing().rejection(CFG))
        for text in (
            'Unfinished basement with separate entrance.',
            'Not a finished basement with separate entrance.',
            'Finished basement with potential for a separate entrance.',
            'Finished basement. Separate entrance can be added.',
            'Partially finished basement with separate entrance.',
            'Finished basement without separate entrance.',
            'Finished basement with no separate side entrance.',
            'Finished basement. Separate entrance is not available.',
            'Finished basement; entrance could be added.',
            'Separate entrance with no basement details.',
        ):
            with self.subTest(text=text):
                self.assertIsNotNone(listing(text).rejection(CFG))
        self.assertIsNone(listing('Basement\nSeparate entrance (Finished)\nOther details').rejection(CFG))

    def test_partial_house_config(self):
        rental = listing('Basement apartment for rent, finished basement and separate entrance.')
        self.assertEqual(rental.rejection(CFG), 'partial house rental')
        cfg = {**CFG, 'entire_house_only': False}
        self.assertIsNone(rental.rejection(cfg))

    def test_structured_limits_and_unknowns(self):
        for key, value in [('rent', 1999), ('rent', 4101), ('rent', None), ('beds', 1),
                           ('beds', None), ('building_type', 'Apartment'),
                           ('latitude', 44), ('longitude', -80), ('latitude', None)]:
            rental = listing()
            setattr(rental, key, value)
            with self.subTest(key=key, value=value):
                self.assertIsNotNone(rental.rejection(CFG))
        for price in ('$3,200/Yearly', '$3,200/Weekly', '$3,200'):
            row = result()
            row['Property']['Price'] = price
            self.assertIsNone(Rental.from_result(row, '').rent)
        self.assertEqual(bedrooms('2 + 1'), 3)
        self.assertIsNone(bedrooms('unknown'))

    def test_untrusted_listing_urls_are_rejected(self):
        for url in ('https://example.com/real-estate/123', '//evil.invalid/real-estate/123', '/map'):
            row = result()
            row['RelativeDetailsURL'] = url
            with self.assertRaises(RentalAccessError):
                Rental.from_result(row, '')

    def test_per_recipient_deduplication_and_failed_send_retry(self):
        with sqlite3.connect(':memory:') as db:
            telegram = Mock(chat_ids=['one', 'two'])
            telegram._send_one.side_effect = [True, False]
            with self.assertRaises(RuntimeError):
                deliver([listing()], db, telegram)
            self.assertEqual(db.execute('SELECT chat_id FROM deliveries').fetchall(), [('one',)])
            telegram._send_one.side_effect = None
            telegram._send_one.return_value = True
            telegram._send_one.reset_mock()
            self.assertEqual(deliver([listing()], db, telegram), 1)
            telegram._send_one.assert_called_once()
            self.assertEqual(telegram._send_one.call_args.args[0], 'two')
            self.assertEqual(deliver([listing()], db, telegram), 0)

    def test_dry_run_and_seed_never_send(self):
        with sqlite3.connect(':memory:') as db:
            telegram = Mock(chat_ids=['one'])
            deliver([listing()], db, telegram, seed=True)
            telegram._send_one.assert_not_called()
            self.assertEqual(deliver([listing()], db, telegram), 0)


if __name__ == '__main__':
    unittest.main()
