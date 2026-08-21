"""Clearance verification and decimal-separator handling.

CLAUDE_CODE_HANDOVER states the rule as "every torque value, clearance, or
spec", but only torque was enforced: GAP_RE was defined in specverify.py and
never called, and verify_answer scanned for torque units alone. On the app's own
demo question -- "what is the spark plug gap and tightening torque?" -- the
torque half was gated and the gap half passed unchecked.
"""

import unittest

from specverify import extract_clearances, extract_specs, verify_answer

PLUGS = {
    "manual_id": "vw_cc_engine",
    "page_physical": 42,
    "chunk_id": "c1",
    "text": "Spark plugs: electrode gap 0.9 mm. Tighten spark plugs to 30 Nm.",
}


def chunk(text):
    return {"manual_id": "m", "page_physical": 1, "chunk_id": "c", "text": text}


class ExtractClearanceTests(unittest.TestCase):
    def test_extracts_gap_verbatim(self):
        specs = extract_clearances(PLUGS)
        self.assertEqual([(s.value, s.unit) for s in specs], [("0.9", "mm")])
        self.assertEqual(specs[0].raw, "0.9 mm")

    def test_carries_provenance(self):
        spec = extract_clearances(PLUGS)[0]
        self.assertEqual(spec.manual_id, "vw_cc_engine")
        self.assertEqual(spec.page_physical, 42)

    def test_no_millimetre_values_yields_nothing(self):
        self.assertEqual(extract_clearances(chunk("Tighten to 40 Nm + 180°.")), [])


class VerifyClearanceTests(unittest.TestCase):
    """The hole: a stated gap used to pass unchecked."""

    def test_correct_gap_and_torque_both_verify(self):
        r = verify_answer("Gap is 0.9 mm, torque 30 Nm [c]", [PLUGS])
        self.assertTrue(r["ok"])
        self.assertEqual(r["numbers_checked"], 2)
        self.assertEqual({f["kind"] for f in r["findings"]}, {"torque", "clearance"})

    def test_wrong_gap_is_rejected_even_when_torque_is_right(self):
        r = verify_answer("Gap is 1.1 mm, torque 30 Nm [c]", [PLUGS])
        self.assertFalse(r["ok"])
        rejected = [f for f in r["findings"] if f["status"] == "REJECT"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["kind"], "clearance")

    def test_rounded_gap_is_rejected(self):
        """SYSTEM_PROMPT forbids rounding, so 0.9 -> 1 is not the manual's value."""
        self.assertFalse(verify_answer("Gap is 1 mm [c]", [PLUGS])["ok"])

    def test_uncited_millimetre_value_is_rejected(self):
        self.assertFalse(verify_answer("Use a 10 mm socket [c]", [PLUGS])["ok"])

    def test_millimetre_value_present_in_source_verifies(self):
        source = chunk("Remove the bolts with a 10 mm socket.")
        self.assertTrue(verify_answer("Use a 10 mm socket [c]", [source])["ok"])

    def test_answer_without_numbers_still_passes(self):
        r = verify_answer("Remove the coil pack first [c]", [PLUGS])
        self.assertTrue(r["ok"])
        self.assertEqual(r["numbers_checked"], 0)

    def test_torque_is_not_double_counted_as_a_clearance(self):
        r = verify_answer("Tighten to 40 Nm + 180° [c]",
                          [chunk("Subframe bolt: 40 Nm + 180°")])
        self.assertEqual(r["numbers_checked"], 1)
        self.assertEqual(r["findings"][0]["kind"], "torque")


class DecimalSeparatorTests(unittest.TestCase):
    """A German-origin source writes "0,9 mm". Matching only "." made the pattern
    latch onto the digits after the comma, so "0,9 mm" parsed as "9 mm" -- which
    would APPROVE a ten-fold error, not merely fail to verify a correct answer."""

    COMMA_GAP = chunk("Electrode gap 0,9 mm")
    COMMA_TORQUE = chunk("Tighten to 40,5 Nm")

    def test_comma_source_extracts_the_whole_value(self):
        self.assertEqual(extract_clearances(self.COMMA_GAP)[0].value, "0,9")
        self.assertEqual(extract_specs(self.COMMA_TORQUE)[0].value, "40,5")

    def test_raw_stays_verbatim(self):
        """Copy-only: the source substring is never rewritten."""
        self.assertEqual(extract_clearances(self.COMMA_GAP)[0].raw, "0,9 mm")

    def test_separators_are_interchangeable_for_comparison(self):
        for stated in ("0.9 mm", "0,9 mm"):
            self.assertTrue(verify_answer(f"Gap is {stated} [c]", [self.COMMA_GAP])["ok"])

    def test_tenfold_error_against_comma_source_is_rejected(self):
        self.assertFalse(verify_answer("Gap is 9 mm [c]", [self.COMMA_GAP])["ok"])
        self.assertFalse(verify_answer("Torque 5 Nm [c]", [self.COMMA_TORQUE])["ok"])

    def test_point_source_behaviour_is_unchanged(self):
        self.assertTrue(verify_answer("Gap is 0.9 mm [c]", [PLUGS])["ok"])
        self.assertFalse(verify_answer("Gap is 9 mm [c]", [PLUGS])["ok"])


if __name__ == "__main__":
    unittest.main()
