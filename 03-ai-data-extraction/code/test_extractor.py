"""
test_extractor.py — Tests for the schema validator, the confidence/review
scoring, and the end-to-end pipeline.

Run with:  python -m unittest test_extractor

These prove the core properties of the pipeline:
  * well-formed extractions pass, and anything missing a required field is
    rejected rather than trusted (the hard validation gate);
  * every valid extraction gets a deterministic confidence score, and
    low-confidence / boundary cases are flagged for human review with reasons;
  * the review subset is separated out so a person only checks uncertain rows.
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


class TestConfidenceScoring(unittest.TestCase):
    def test_clean_record_high_confidence_no_review(self):
        rec = dict(VALID)
        scored = extractor.score_record(dict(rec))
        self.assertGreaterEqual(scored["confidence"], 0.9)
        self.assertFalse(scored["needs_review"])
        self.assertEqual(scored["review_reasons"], [])
        # Every schema field gets an individual confidence.
        self.assertEqual(
            set(scored["field_confidence"]),
            {"invoice_number", "invoice_date", "vendor", "currency", "total", "line_items"},
        )

    def test_scoring_is_deterministic(self):
        a = extractor.score_record(dict(VALID))
        b = extractor.score_record(dict(VALID))
        self.assertEqual(a["confidence"], b["confidence"])
        self.assertEqual(a["field_confidence"], b["field_confidence"])

    def test_confidence_in_unit_interval(self):
        scored = extractor.score_record(dict(VALID))
        self.assertGreaterEqual(scored["confidence"], 0.0)
        self.assertLessEqual(scored["confidence"], 1.0)
        for v in scored["field_confidence"].values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_non_iso_date_flags_review(self):
        rec = dict(VALID, invoice_date="March 5, 2024")  # parsed but not ISO
        scored = extractor.score_record(dict(rec))
        self.assertTrue(scored["needs_review"])
        self.assertTrue(any("ISO 8601" in r for r in scored["review_reasons"]))
        self.assertLess(scored["field_confidence"]["invoice_date"], 0.5)

    def test_total_not_reconciling_flags_review(self):
        # Stated total far above the line-item sum (e.g. un-itemized fee).
        rec = dict(
            VALID,
            total=329.0,
            line_items=[
                {"description": "A", "quantity": 3.0, "unit_price": 12.0},
                {"description": "B", "quantity": 5.0, "unit_price": 49.0},
            ],
        )
        scored = extractor.score_record(dict(rec))
        self.assertTrue(scored["needs_review"])
        self.assertTrue(any("reconcile" in r for r in scored["review_reasons"]))
        self.assertLess(scored["field_confidence"]["total"], 0.5)

    def test_total_with_tax_within_tolerance_reconciles(self):
        # Line-item sum 1423.98, total 1538.97 (~8% tax) -> within tolerance.
        rec = dict(
            VALID,
            total=1538.97,
            line_items=[
                {"description": "A", "quantity": 2.0, "unit_price": 19.99},
                {"description": "B", "quantity": 10.0, "unit_price": 8.5},
                {"description": "C", "quantity": 1.0, "unit_price": 1299.0},
            ],
        )
        scored = extractor.score_record(dict(rec))
        self.assertEqual(scored["field_confidence"]["total"], 1.0)
        self.assertFalse(
            any("reconcile" in r for r in scored["review_reasons"])
        )

    def test_total_below_line_item_sum_flags_review(self):
        rec = dict(
            VALID,
            total=50.0,  # below the line-item sum of 100
            line_items=[{"description": "X", "quantity": 1.0, "unit_price": 100.0}],
        )
        scored = extractor.score_record(dict(rec))
        self.assertTrue(scored["needs_review"])
        self.assertLess(scored["field_confidence"]["total"], 0.5)

    def test_threshold_controls_flagging(self):
        # A clean record auto-approves by default but can be forced to review
        # by demanding (impossibly) high confidence.
        clean = extractor.score_record(dict(VALID))
        self.assertFalse(clean["needs_review"])
        strict = extractor.score_record(dict(VALID), threshold=1.01)
        self.assertTrue(strict["needs_review"])
        self.assertTrue(
            any("below review threshold" in r for r in strict["review_reasons"])
        )


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

    def test_process_folder_triage(self):
        """The bundled samples yield 2 extracted / 1 rejected, with exactly one
        of the extractions flagged for human review and split into its own
        subset — the demonstration the README and proposal describe."""
        from pathlib import Path

        sample_dir = Path(__file__).resolve().parent.parent / "sample_data"
        outcome = extractor.process_folder(sample_dir, extractor.MockLLMClient())

        self.assertEqual(outcome["summary"]["extracted"], 2)
        self.assertEqual(outcome["summary"]["failed"], 1)
        self.assertEqual(outcome["summary"]["needs_review"], 1)

        # The review subset is a real subset of the extracted records.
        self.assertEqual(len(outcome["needs_review"]), 1)
        for rec in outcome["needs_review"]:
            self.assertTrue(rec["needs_review"])
            self.assertIn(rec, outcome["extracted"])
            self.assertTrue(rec["review_reasons"])  # has at least one reason

        # Every extracted record carries confidence + review fields.
        for rec in outcome["extracted"]:
            self.assertIn("confidence", rec)
            self.assertIn("needs_review", rec)
            self.assertIn("field_confidence", rec)

        # The rejection still carries an explicit reason (validation gate intact).
        self.assertTrue(outcome["failed"][0]["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
