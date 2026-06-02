"""
test_extractor.py — Tests for the schema validator and the end-to-end pipeline.

Run with:  python -m unittest test_extractor

These prove the core safety property of the pipeline: well-formed extractions
pass, and anything missing a required field is rejected rather than trusted.
"""

import unittest

import extractor


VALID = {
    "invoice_number": "INV-1",
    "invoice_date": "2024-01-01",
    "vendor": "Acme",
    "currency": "USD",
    "total": 100.0,
    "line_items": [{"description": "Widget", "quantity": 1.0, "unit_price": 100.0}],
}


class TestValidate(unittest.TestCase):
    def test_valid_passes(self):
        extractor.validate(VALID, extractor.INVOICE_SCHEMA)  # should not raise

    def test_missing_required_total_fails(self):
        bad = dict(VALID)
        bad.pop("total")
        with self.assertRaises(extractor.ValidationError):
            extractor.validate(bad, extractor.INVOICE_SCHEMA)

    def test_wrong_type_fails(self):
        bad = dict(VALID, total="one hundred")
        with self.assertRaises(extractor.ValidationError):
            extractor.validate(bad, extractor.INVOICE_SCHEMA)

    def test_bad_line_item_fails(self):
        bad = dict(VALID, line_items=[{"description": "x"}])  # missing qty/price
        with self.assertRaises(extractor.ValidationError):
            extractor.validate(bad, extractor.INVOICE_SCHEMA)


class TestPipeline(unittest.TestCase):
    def test_end_to_end_with_mock(self):
        doc = (
            "Invoice #: INV-9\n"
            "Date: 2024-05-01\n"
            "From: Test Vendor\n"
            "2 x Thing @ $5.00\n"
            "Total: 10.00 USD\n"
        )
        data = extractor.extract_document(doc, extractor.MockLLMClient())
        extractor.validate(data, extractor.INVOICE_SCHEMA)
        self.assertEqual(data["invoice_number"], "INV-9")
        self.assertEqual(data["total"], 10.0)
        self.assertEqual(data["currency"], "USD")
        self.assertEqual(len(data["line_items"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
