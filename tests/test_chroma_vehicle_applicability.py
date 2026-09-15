"""Regression coverage for vehicle applicability in the Chroma retrieval path.

The app prefers ChromaLibrary when out/chroma_db exists, so Chroma must accept
and apply the same vehicle profile filter as Library/DualLibrary. These tests
avoid constructing a real ChromaDB instance by exercising the filter method and
method signature directly.
"""

import inspect
import unittest

from retrieve import ChromaLibrary


CC_PROFILE = {"vehicle": "2014 VW CC 2.0T TSI", "engine": "CBFA"}


def chunk(vehicle=None, engine=None):
    data = {
        "chunk_id": "test_p0001_01",
        "manual_id": "test_manual",
        "manual_title": "Test Manual",
        "page_physical": 1,
        "section_title": "Test Section",
        "system": "test",
        "text": "test text",
        "viewer_url": "test://manual#page=1",
    }
    if vehicle is not None:
        data["vehicle"] = vehicle
    if engine is not None:
        data["engine"] = engine
    return data


class ChromaVehicleApplicabilityTests(unittest.TestCase):
    def test_chroma_retrieve_accepts_profile_keyword(self):
        sig = inspect.signature(ChromaLibrary.retrieve)
        self.assertIn("profile", sig.parameters)

    def test_chroma_passes_filter_applies_vehicle_profile(self):
        lib = ChromaLibrary.__new__(ChromaLibrary)

        self.assertTrue(
            lib._passes_filter(
                chunk("2014 VW CC 2.0T TSI", "CBFA"),
                manual_id=None,
                system=None,
                vehicle_kw=None,
                profile=CC_PROFILE,
            )
        )
        self.assertFalse(
            lib._passes_filter(
                chunk("2014 Audi A4 2.0T", "CAEB"),
                manual_id=None,
                system=None,
                vehicle_kw=None,
                profile=CC_PROFILE,
            )
        )

    def test_chroma_filter_keeps_generic_and_unstamped_chunks(self):
        lib = ChromaLibrary.__new__(ChromaLibrary)

        self.assertTrue(
            lib._passes_filter(
                chunk("VW multi-model", None),
                manual_id=None,
                system=None,
                vehicle_kw=None,
                profile=CC_PROFILE,
            )
        )
        self.assertTrue(
            lib._passes_filter(
                chunk(None, None),
                manual_id=None,
                system=None,
                vehicle_kw=None,
                profile=CC_PROFILE,
            )
        )


if __name__ == "__main__":
    unittest.main()
