import unittest
from dataclasses import replace

from src.models import Listing, SearchConfig
from src.scraper import filter_rejection_reason, matches_filters


class SearchFiltersTest(unittest.TestCase):
    def setUp(self):
        self.search = SearchConfig(
            "Kia Optima Hybrid", "kia optima hybrid", 2011, 2017, 1000, 3000,
            queries=["kia optima hybrid", "optima hybrid", "kia optima", "optima hev"],
            must_include_any=["optima", "k5"], max_mileage_km=250000,
        )
        self.car = Listing("123", "2014 Kia Optima Hybrid", "CA$2,500", 2500,
                           "Toronto, ON", "https://www.facebook.com/marketplace/item/123",
                           "Kia Optima Hybrid", year=2014, mileage_km=220000)

    def test_configured_hybrid_variants_can_match_without_literal_primary_query(self):
        for title in ("2014 Optima Hybrid", "2014 Kia Optima HEV", "2014 Optima HEV"):
            with self.subTest(title=title):
                self.assertTrue(matches_filters(replace(self.car, title=title), self.search, []))

    def test_broad_optima_query_does_not_accept_unconfirmed_gasoline_models(self):
        car = replace(self.car, title="2014 Kia Optima LX")
        self.assertEqual(filter_rejection_reason(car, self.search, []), "hybrid_not_confirmed")

    def test_wrong_model_is_rejected_even_if_it_is_a_hybrid(self):
        self.assertFalse(matches_filters(replace(self.car, title="2014 Kia Niro Hybrid"), self.search, []))

    def test_year_price_and_mileage_limits_still_apply_to_aliases(self):
        for change, reason in (({"year": 2018}, "year_out_of_range"),
                               ({"price_amount": 3500}, "price_out_of_range"),
                               ({"mileage_km": 250001}, "mileage_too_high")):
            with self.subTest(reason=reason):
                car = replace(self.car, title="2014 Optima HEV", **change)
                self.assertEqual(filter_rejection_reason(car, self.search, []), reason)

    def test_custom_single_and_multiword_queries_reject_other_cars(self):
        for query in ("tesla", "kia forte"):
            search = SearchConfig(query, query, 2011, 2017, 1000, 3000)
            self.assertFalse(matches_filters(self.car, search, []))


if __name__ == "__main__":
    unittest.main()
