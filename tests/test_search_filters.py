import unittest
from dataclasses import replace
from unittest.mock import Mock

from src.models import Listing, SearchConfig
from src.search_queries import MAX_EXPANDED_QUERIES
from src.scraper import _extract_listings_from_dom, filter_rejection_reason, matches_filters


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

    def test_optima_searches_include_requested_variants_once(self):
        queries = self.search.all_queries()
        self.assertIn("kia optima huv", queries)
        self.assertIn("kia optima hev", queries)
        self.assertIn("kia optima phev", queries)
        self.assertEqual(len(queries), len(set(queries)))

    def test_description_can_confirm_hybrid_but_huv_alone_cannot(self):
        car = replace(self.car, title="2014 Kia Optima", description="Hybrid engine. Safety included")
        self.assertTrue(matches_filters(car, self.search, []))
        car = replace(car, title="2014 Kia Optima HUV", description="")
        self.assertEqual(filter_rejection_reason(car, self.search, []), "hybrid_not_confirmed")
        car = replace(car, title="2014 Kia Optima", description="Non-hybrid model")
        self.assertEqual(filter_rejection_reason(car, self.search, []), "hybrid_not_confirmed")

    def test_description_references_to_other_models_do_not_match_a_wrong_car(self):
        car = replace(self.car, title="2014 Honda Civic", description="Trading for Kia Optima Hybrid")
        self.assertFalse(matches_filters(car, self.search, []))

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

    def test_general_expansion_for_different_makes_and_model_formats(self):
        examples = {
            "toyota camry hybrid": ["camry hybrid", "toyota camry hev", "toyota camry"],
            "hyundai sonata hybrid": ["sonata hybrid", "hyundai sonata hev", "hyundaisonata hybrid"],
            "honda civic": ["civic", "hondacivic"],
            "ford f150": ["f150", "ford f 150", "ford f-150"],
            "honda crv": ["crv", "honda cr v", "honda cr-v"],
            "honda cr-v": ["cr-v", "honda crv", "crv"],
            "chevrolet cruze": ["cruze", "chevy cruze"],
            "volkswagen golf": ["golf", "vw golf"],
            "mazda cx5": ["cx5", "mazda cx 5", "mazda cx-5"],
            "bmw 320i": ["320i", "bmw 320 i", "bmw320i"],
            "mazda3": ["mazda 3", "mazda3"],
            "land rover discovery": ["discovery", "landroverdiscovery"],
        }
        for query, expected in examples.items():
            with self.subTest(query=query):
                search = replace(self.search, query=query, queries=[], must_include_any=[])
                queries = search.all_queries()
                for variant in expected:
                    self.assertIn(variant, queries)
                self.assertLessEqual(len(queries), MAX_EXPANDED_QUERIES)

    def test_general_aliases_match_but_similar_models_do_not(self):
        examples = [
            ("honda civic", "2014 Civic", "2014 Honda Civicson"),
            ("ford f150", "2014 Ford F-150", "2014 Ford F1500"),
            ("honda crv", "2014 Honda CR-V", "2014 Honda CR-Z"),
            ("honda cr-v", "2014 Honda CRV", "2014 Honda CR-Z"),
            ("chevrolet cruze", "2014 Chevy Cruze", "2014 Chevy Impala"),
            ("mazda 3", "2014 Mazda3", "2014 Mazda 30"),
            ("bmw 320i", "2014 BMW320i", "2014 BMW 3200i"),
            ("toyota camry hybrid", "2014 Camry HEV", "2014 Corolla HEV"),
            ("hyundai sonata hybrid", "2014 Sonata", "2014 Elantra"),
        ]
        for query, good, wrong in examples:
            with self.subTest(query=query):
                search = replace(self.search, query=query, queries=[], must_include_any=[])
                car = replace(self.car, title=good, description="Hybrid engine", card_text="3 km $320")
                self.assertTrue(matches_filters(car, search, []))
                self.assertFalse(matches_filters(replace(car, title=wrong), search, []))

    def test_legacy_wizard_model_rules_allow_brandless_titles(self):
        search = replace(self.search, query="toyota camry hybrid", queries=[],
                         must_include_any=["toyota camry", "toyotacamry"],
                         must_include_all=["toyota", "camry"])
        self.assertTrue(matches_filters(replace(self.car, title="2014 Camry HEV"), search, []))

    def test_brandless_variants_do_not_accept_another_named_manufacturer(self):
        search = replace(self.search, query="subaru liberty", queries=[], must_include_any=[])
        self.assertTrue(matches_filters(replace(self.car, title="2014 Liberty"), search, []))
        self.assertFalse(matches_filters(replace(self.car, title="2014 Jeep Liberty"), search, []))
        search = replace(search, queries=["jeep liberty"])
        self.assertTrue(matches_filters(replace(self.car, title="2014 Jeep Liberty"), search, []))

    def test_genuine_custom_keyword_constraints_are_preserved(self):
        search = replace(self.search, query="honda civic", queries=[],
                         must_include_any=["civic", "civic si"], must_include_all=["manual"])
        car = replace(self.car, title="2014 Civic")
        self.assertEqual(filter_rejection_reason(car, search, []), "required_keywords")
        self.assertTrue(matches_filters(replace(car, description="Manual gearbox"), search, []))

    def test_phev_query_requires_plugin_evidence_not_just_hybrid(self):
        search = replace(self.search, query="mitsubishi outlander phev", queries=[], must_include_any=[])
        for title in ("2014 Outlander PHEV", "2014 Mitsubishi Outlander Plug-in Hybrid"):
            self.assertTrue(matches_filters(replace(self.car, title=title), search, []))
        self.assertEqual(filter_rejection_reason(
            replace(self.car, title="2014 Outlander Hybrid"), search, []), "hybrid_not_confirmed")
        self.assertNotIn("mitsubishi outlander hev", search.all_queries())
        self.assertEqual(filter_rejection_reason(replace(
            self.car, title="2014 Outlander Hybrid", description="Not a PHEV"), search, []),
            "hybrid_not_confirmed")

    def test_hybrid_checkbox_requires_evidence_but_diesel_does_not_expand_hybrids(self):
        search = replace(self.search, query="toyota camry", queries=[], must_include_any=[],
                         powertrain_any=["hybrid", "hev", "phev"])
        self.assertIn("toyota camry hybrid", search.all_queries())
        self.assertEqual(filter_rejection_reason(
            replace(self.car, title="2014 Camry"), search, []), "hybrid_not_confirmed")
        search = replace(search, query="volkswagen golf", powertrain_any=["diesel"])
        self.assertFalse(any("hybrid" in q for q in search.all_queries()))
        self.assertTrue(matches_filters(replace(self.car, title="2014 Golf Diesel"), search, []))

    def test_bounds_deduplication_and_explicit_aliases_are_preserved(self):
        search = replace(self.search, query="toyota camry hybrid",
                         queries=["TOYOTA CAMRY HYBRID", " toyota  camry hybrid ", "toyota camry hv"])
        queries = search.all_queries()
        self.assertIn("toyota camry hv", queries)
        self.assertEqual(len(queries), len({q.lower() for q in queries}))
        self.assertLessEqual(len(queries), MAX_EXPANDED_QUERIES)
        search = replace(search, queries=[f"camry alias {i}" for i in range(12)])
        self.assertEqual(len(search.all_queries()), 13)

    def test_numeric_models_and_unknown_makes_do_not_create_overbroad_queries(self):
        for query in ("mazda 3", "unknownbrand coupe", "tesla", "hybrid"):
            with self.subTest(query=query):
                queries = replace(self.search, query=query, queries=[]).all_queries()
                self.assertNotIn("3", queries)
                self.assertNotIn("coupe", queries)
                self.assertNotIn("", queries)

    def test_localized_badge_does_not_replace_vehicle_title_or_year(self):
        page = Mock()
        page.locator.return_value.count.return_value = 1
        anchor = page.locator.return_value.nth.return_value
        anchor.get_attribute.return_value = "/marketplace/item/123"
        anchor.inner_text.return_value = (
            "Just listed\nCA$ 2.800\n2015 Kia optima\nNorth York, ON"
        )
        rows = _extract_listings_from_dom(page, "Kia Optima Hybrid")
        self.assertEqual(rows[0].title, "2015 Kia optima")
        self.assertEqual(rows[0].year, 2015)
        self.assertEqual(rows[0].price_amount, 2800)
        self.assertEqual(rows[0].location, "North York, ON")


if __name__ == "__main__":
    unittest.main()
