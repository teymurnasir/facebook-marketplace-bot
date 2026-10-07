import unittest

from playwright.sync_api import sync_playwright

from src.models import Listing
from src.scraper import MarketplaceScraper


class DescriptionDomTest(unittest.TestCase):
    def test_localized_description_excludes_seller_and_recommended_ads(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                context.route("**/marketplace/item/123", lambda route: route.fulfill(
                    content_type="text/html", body="""
                    <main role="main">
                      <h1>2014 Kia Optima</h1>
                      <h2>Bu nəqliyyat vasitəsi haqqında</h2>
                      <div>232.000 km gedib</div>
                      <h2>Satıcının təsviri</h2>
                      <div>Sold as-is. No safety certificate.</div>
                      <div>Toronto, ON · Məkan təxminidir</div>
                      <h2>Satıcı məlumatları</h2><div>Seller text</div>
                      <h2>Other cars</h2><div>Safety included for a different car</div>
                    </main>
                    """))
                car = Listing("123", "2014 Kia Optima", "$2500", 2500, "Toronto", "", "Kia")
                MarketplaceScraper("unused")._read_details(context, car)
                self.assertEqual(car.description, "Sold as-is. No safety certificate.")
                self.assertEqual(car.safety, "no")
                self.assertEqual(car.mileage_km, 232000)
                self.assertTrue(car.details_checked_at)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
