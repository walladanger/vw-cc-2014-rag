"""Vehicle applicability filtering.

specverify proves a stated number was copied from a cited chunk. It cannot tell
whether that chunk applies to the car being asked about, so an index holding
more than one vehicle can return another car's spec and still report it
VERIFIED. These tests pin the retrieval-side scoping that prevents that.

The values used here are the ones ingest_all.ps1 and ingest_unprocessed.ps1
actually stamp: "2014 VW CC 2.0T TSI" / engine "CBFA" by default, plus the
generic "VW" and "VW (multi-model)" entries used for the shared DTC lists.
"""

import unittest

from retrieve import applies_to_vehicle

CC = {"vehicle": "2014 VW CC 2.0T TSI", "engine": "CBFA"}


def chunk(vehicle=None, engine=None):
    return {"vehicle": vehicle, "engine": engine}


class AppliesToVehicleTests(unittest.TestCase):
    # -- fail-open cases: must never empty a working index -------------------
    def test_no_profile_admits_everything(self):
        self.assertTrue(applies_to_vehicle(chunk("2014 Audi A4"), None))

    def test_unstamped_chunk_is_admitted(self):
        """Indexes built before applicability was enforced must keep working."""
        self.assertTrue(applies_to_vehicle(chunk(None), CC))
        self.assertTrue(applies_to_vehicle(chunk(""), CC))

    def test_profile_without_vehicle_admits_everything(self):
        self.assertTrue(applies_to_vehicle(chunk("2014 Audi A4"), {"engine": "CBFA"}))

    # -- the car itself ------------------------------------------------------
    def test_exact_match_applies(self):
        self.assertTrue(applies_to_vehicle(chunk("2014 VW CC 2.0T TSI", "CBFA"), CC))

    def test_match_is_insensitive_to_case_and_punctuation(self):
        self.assertTrue(applies_to_vehicle(chunk("2014 vw cc 2.0t tsi"), CC))
        self.assertTrue(applies_to_vehicle(chunk("2014  VW  CC  2.0T  TSI"), CC))

    # -- generic references stay retrievable ---------------------------------
    def test_marque_only_reference_applies(self):
        """ingest_all.ps1 stamps the 1998-2012 DTC list as vehicle='VW'."""
        self.assertTrue(applies_to_vehicle(chunk("VW", "multi"), CC))

    def test_multi_model_reference_applies(self):
        """ingest_unprocessed.ps1 stamps two DTC docs 'VW (multi-model)'."""
        self.assertTrue(applies_to_vehicle(chunk("VW (multi-model)", "multi"), CC))

    def test_volkswagen_spelled_out_is_the_same_marque(self):
        self.assertTrue(applies_to_vehicle(chunk("Volkswagen"), CC))

    # -- other cars are excluded --------------------------------------------
    def test_other_marque_specific_is_excluded(self):
        self.assertFalse(applies_to_vehicle(chunk("2014 Audi A4 2.0T", "CAEB"), CC))

    def test_other_marque_generic_is_excluded(self):
        self.assertFalse(applies_to_vehicle(chunk("Audi", "multi"), CC))

    def test_same_marque_different_model_is_excluded(self):
        self.assertFalse(applies_to_vehicle(chunk("2012 VW Golf 1.4 TSI"), CC))

    def test_same_model_different_engine_is_excluded(self):
        self.assertFalse(applies_to_vehicle(chunk("2014 VW CC 3.6 VR6", "BHK"), CC))

    # -- engine is only decisive when both sides are specific ----------------
    def test_generic_engine_on_matching_vehicle_applies(self):
        self.assertTrue(applies_to_vehicle(chunk("2014 VW CC 2.0T TSI", "multi"), CC))

    def test_unstamped_engine_on_matching_vehicle_applies(self):
        self.assertTrue(applies_to_vehicle(chunk("2014 VW CC 2.0T TSI", None), CC))

    def test_conflicting_specific_engine_is_excluded(self):
        self.assertFalse(applies_to_vehicle(chunk("2014 VW CC 2.0T TSI", "CCTA"), CC))


class PassesFilterIntegrationTests(unittest.TestCase):
    """The filter must be reachable through Library._passes_filter, which is what
    retrieve() actually calls."""

    def test_profile_is_applied_by_passes_filter(self):
        from retrieve import Library

        lib = Library.__new__(Library)  # no index needed for filter logic
        audi = chunk("2014 Audi A4 2.0T", "CAEB")
        cc = chunk("2014 VW CC 2.0T TSI", "CBFA")

        self.assertFalse(lib._passes_filter(audi, None, None, None, CC))
        self.assertTrue(lib._passes_filter(cc, None, None, None, CC))
        # no profile -> unchanged legacy behaviour
        self.assertTrue(lib._passes_filter(audi, None, None, None, None))


if __name__ == "__main__":
    unittest.main()
