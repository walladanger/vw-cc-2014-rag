import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

VIN_A = "WVWZZZ3CZEE123456"
VIN_B = "WVWZZZ3CZEE654321"


class GarageRequestScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CC_WORKSHOP_DATA_ROOT": self.temp.name})
        self.env.start()
        import app
        app.configure_garage_boundary(self.temp.name)
        self.client = app.app.test_client()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_garage_crud_records_are_vin_scoped(self):
        for vin, name in ((VIN_A, "Blue"), (VIN_B, "Black")):
            self.assertEqual(self.client.post("/api/garages", json={"vin": vin, "display_name": name}).status_code, 201)
        created = self.client.post(f"/api/garages/{VIN_A}/records", json={"kind": "note", "payload": {"private": "A", "nested": {"codes": ["P0300"]}}})
        self.assertEqual(created.status_code, 201)
        record_id = created.get_json()["id"]
        found = self.client.get(f"/api/garages/{VIN_A}/records/{record_id}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.get_json()["payload"]["nested"]["codes"], ["P0300"])
        self.assertEqual(self.client.get(f"/api/garages/{VIN_B}/records/{record_id}").status_code, 404)

    def test_garage_routes_reject_non_object_json(self):
        response = self.client.post("/api/garages", json=["not", "an", "object"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_garage")
        self.client.post("/api/garages", json={"vin": VIN_A, "display_name": "Blue"})
        response = self.client.post(f"/api/garages/{VIN_A}/records", json=["not", "an", "object"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_record")

    def test_private_content_entry_points_require_confirmed_vin(self):
        calls = (
            lambda: self.client.post("/query", json={"q": "starter"}),
            lambda: self.client.get("/library"),
            lambda: self.client.get("/pdf/manual"),
            lambda: self.client.get("/viewer?manual=manual"),
            lambda: self.client.get("/video-frame/videos/a/frame.jpg"),
        )
        for call in calls:
            response = call()
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.get_json()["error"], "needs_identification")

    def test_confirmed_garage_without_approved_evidence_cannot_use_global_corpus(self):
        self.client.post("/api/garages", json={"vin": VIN_A, "display_name": "Blue"})
        response = self.client.post("/query", headers={"X-Vehicle-VIN": VIN_A}, json={"q": "starter"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "library_unavailable")

    def test_approved_source_association_still_does_not_use_global_corpus_before_scoped_indexes(self):
        self.client.post("/api/garages", json={"vin": VIN_A, "display_name": "Blue"})
        registry = __import__("app").app.extensions["garage_registry"]
        garage = registry.get(VIN_A)
        with closing(sqlite3.connect(garage.database_path)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO source_associations(vin, source_id) VALUES (?, ?)",
                    (VIN_A, "manual-a"),
                )
        for response in (
            self.client.get("/library", headers={"X-Vehicle-VIN": VIN_A}),
            self.client.post("/query", headers={"X-Vehicle-VIN": VIN_A}, json={"q": "starter"}),
        ):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error"], "library_unavailable")


if __name__ == "__main__":
    unittest.main()
