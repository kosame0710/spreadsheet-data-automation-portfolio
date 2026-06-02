"""
test_cleaner.py — Lightweight unit tests for the parsing helpers.

Run with:  python -m unittest test_cleaner   (no third-party test runner needed)

These cover the trickiest, format-sensitive logic (dates, amounts, quantities,
emails) so a future maintainer can refactor with confidence.
"""

import unittest
from datetime import date

import cleaner


class TestParseAmount(unittest.TestCase):
    def test_us_thousands(self):
        self.assertEqual(cleaner.parse_amount("$1,299.00"), 1299.00)

    def test_eu_thousands_decimal_comma(self):
        self.assertEqual(cleaner.parse_amount("1.299,00 €"), 1299.00)

    def test_decimal_comma_only(self):
        self.assertEqual(cleaner.parse_amount("19,99 €"), 19.99)

    def test_plain_integer(self):
        self.assertEqual(cleaner.parse_amount("2980"), 2980.0)

    def test_garbage_is_none(self):
        self.assertIsNone(cleaner.parse_amount("impossible"))


class TestParseDate(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(cleaner.parse_date("2024-01-05"), date(2024, 1, 5))

    def test_eu_dotted(self):
        self.assertEqual(cleaner.parse_date("05.01.2024"), date(2024, 1, 5))

    def test_us_slash(self):
        self.assertEqual(cleaner.parse_date("01/06/2024"), date(2024, 6, 1))

    def test_textual(self):
        self.assertEqual(cleaner.parse_date("Jan 8 2024"), date(2024, 1, 8))

    def test_invalid_is_none(self):
        self.assertIsNone(cleaner.parse_date("2024-13-45"))


class TestParseQuantity(unittest.TestCase):
    def test_int(self):
        self.assertEqual(cleaner.parse_quantity("3"), 3)

    def test_negative(self):
        self.assertEqual(cleaner.parse_quantity("-1"), -1)  # parsed; rejected later by rule

    def test_non_numeric(self):
        self.assertIsNone(cleaner.parse_quantity("abc"))

    def test_fractional_rejected(self):
        self.assertIsNone(cleaner.parse_quantity("2.5"))


class TestEmail(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(cleaner.is_valid_email("a@b.com"))

    def test_double_at(self):
        self.assertFalse(cleaner.is_valid_email("jane@@example.com"))

    def test_no_tld(self):
        self.assertFalse(cleaner.is_valid_email("beta@example"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
