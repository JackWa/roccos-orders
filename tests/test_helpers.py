"""No-network unit tests for the pure helpers. Run: python3 -m unittest discover tests"""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import roccos_orders as ro
import roccos_token as rt


def make_jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{body}.sig"


class TestIsLive(unittest.TestCase):
    def test_completed_is_not_live(self):
        for status in ("Completed", "Cancelled", "Refunded", "FAILED"):
            self.assertFalse(ro.is_live({"Status": status}))

    def test_in_progress_is_live(self):
        for status in ("OutForDelivery", "InKitchen", "Placed"):
            self.assertTrue(ro.is_live({"Status": status}))

    def test_missing_status_is_live(self):
        self.assertTrue(ro.is_live({}))


class TestFlatten(unittest.TestCase):
    def test_stable_keys_even_for_empty(self):
        self.assertEqual(
            list(ro.flatten({}).keys()),
            ["OrderId", "PlacedUtc", "Occasion", "Status", "Live", "Total", "Currency", "Payment"],
        )

    def test_maps_fields_and_live_flag(self):
        row = ro.flatten({
            "Id": "o1", "CreatedTimeUtc": "2026-01-01T00:00:00Z", "Occasion": "Delivery",
            "Status": "OutForDelivery", "TotalAmount": 12.5, "CurrencyCode": "GBP",
            "PaymentStatus": "Paid",
        })
        self.assertEqual(row["OrderId"], "o1")
        self.assertEqual(row["Total"], 12.5)
        self.assertEqual(row["Live"], "yes")

    def test_completed_has_no_live_flag(self):
        self.assertEqual(ro.flatten({"Status": "Completed"})["Live"], "")


class TestBasketLines(unittest.TestCase):
    def test_standalone_and_deal_items(self):
        basket = {
            "Items": [{"Charges": [{"Quantity": 1, "Narrative": "Coke", "Total": 1.5}]}],
            "Deals": [{"Items": [
                {"Charges": [{"Quantity": 2, "Narrative": "Pizza", "Total": 20}]},
                {"Charges": [{"Quantity": 1, "Narrative": "Garlic Bread"}]},  # no price
            ]}],
        }
        self.assertEqual(
            ro.basket_lines(basket),
            ["1x Coke  £1.5", "2x Pizza  £20", "1x Garlic Bread"],
        )

    def test_non_dict_returns_empty(self):
        self.assertEqual(ro.basket_lines("not a basket"), [])
        self.assertEqual(ro.basket_lines({}), [])


class TestTokenHelpers(unittest.TestCase):
    def test_decode_jwt(self):
        self.assertEqual(rt.decode_jwt(make_jwt({"sub": "abc"}))["sub"], "abc")

    def test_decode_jwt_opaque_token(self):
        self.assertEqual(rt.decode_jwt("not-a-jwt"), {})

    def test_hidden_fields(self):
        html = (
            '<form action="" method="post">'
            '<input name="__RequestVerificationToken" type="hidden" value="tok&amp;123" />'
            '<input name="ReturnUrl" type="hidden" value="/cb" />'
            '<input name="Username" type="email" value="" />'  # not hidden -> skipped
            "</form>"
        )
        fields = rt.hidden_fields(html)
        self.assertEqual(fields["__RequestVerificationToken"], "tok&123")  # unescaped
        self.assertEqual(fields["ReturnUrl"], "/cb")
        self.assertNotIn("Username", fields)

    def test_seconds_left(self):
        import time
        entry = {"obtained_at": int(time.time()) - 100, "expires_in": 3600}
        self.assertAlmostEqual(rt.seconds_left(entry), 3500, delta=2)
        self.assertEqual(rt.seconds_left(None), -1)


class TestArgParsing(unittest.TestCase):
    def test_selectors_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            ro.parse_args(["--latest", "--live"])

    def test_formats_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            ro.parse_args(["--json", "--csv"])

    def test_selector_and_format_compose(self):
        args = ro.parse_args(["--live", "--json"])
        self.assertTrue(args.live and args.json)

    def test_recent_rejects_non_positive(self):
        with self.assertRaises(SystemExit):
            ro.parse_args(["--recent", "0"])

    def test_defaults(self):
        args = ro.parse_args([])
        self.assertFalse(args.latest or args.live or args.json or args.csv or args.force)
        self.assertIsNone(args.recent)


if __name__ == "__main__":
    unittest.main()
