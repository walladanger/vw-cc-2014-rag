import importlib
import tempfile
import unittest
from pathlib import Path

VIN = "WVWZZZ3CZEE123456"


class VehicleProfileRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app_module = importlib.import_module("app")
        self.app_module.configure_garage_boundary(Path(self.temp.name))
        self.client = self.app_module.app.test_client()
        response = self.client.post(
            "/api/garages", json={"vin": VIN, "display_name": "Test CC"}
        )
        self.assertEqual(response.status_code, 201)
        self.headers = {"X-Vehicle-VIN": VIN}

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_routes_keep_drafts_unconfirmed_and_evaluate_applicability(self):
        draft = self.client.post(
            f"/api/garages/{VIN}/identification-drafts",
            headers=self.headers,
            json={
                "id": "historical-note",
                "description": "An old description says CCTA",
                "evidence": {"kind": "historical_note"},
            },
        )
        self.assertEqual(draft.status_code, 201)
        before = self.client.get(f"/api/garages/{VIN}/profile", headers=self.headers)
        self.assertEqual(before.status_code, 200)
        self.assertNotIn("engine_code", before.get_json()["fields"])

        confirmed = self.client.put(
            f"/api/garages/{VIN}/profile/engine_code",
            headers=self.headers,
            json={"value": "CBFA", "evidence": {"kind": "vehicle_label"}},
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(
            confirmed.get_json()["fields"]["engine_code"]["value"], "CBFA"
        )

        mismatch = self.client.post(
            f"/api/garages/{VIN}/applicability",
            headers=self.headers,
            json={"requirements": {"engine_code": "CCTA"}},
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertEqual(mismatch.get_json()["state"], "confirmed_mismatch")

    def test_route_vin_mismatch_and_missing_evidence_fail_closed(self):
        other = "WVWZZZ3CZEE654321"
        self.assertEqual(
            self.client.put(
                f"/api/garages/{other}/profile/engine_code",
                headers=self.headers,
                json={"value": "CBFA", "evidence": {"kind": "scan"}},
            ).status_code,
            404,
        )
        response = self.client.put(
            f"/api/garages/{VIN}/profile/engine_code",
            headers=self.headers,
            json={"value": "CBFA", "evidence": {}},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_profile")


if __name__ == "__main__":
    unittest.main()
