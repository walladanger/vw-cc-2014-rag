import tempfile
import unittest
from pathlib import Path

from cc_workshop.contracts import ApplicabilityState

VIN = "WVWZZZ3CZEE123456"


class VehicleApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        from cc_workshop.garage import GarageRegistry
        from cc_workshop.vehicle_profiles import VehicleProfileStore

        self.registry = GarageRegistry(Path(self.temp.name))
        self.registry.create(VIN, display_name="CC", request_id="create")
        self.store = VehicleProfileStore(self.registry, self.registry.context(VIN, "profile"))

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_metadata_and_unconfirmed_profile_fields_are_unknown(self):
        empty = self.store.evaluate({})
        self.assertEqual(empty.state, ApplicabilityState.UNKNOWN)

        result = self.store.evaluate({"engine_code": "CBFA"})
        self.assertEqual(result.state, ApplicabilityState.UNKNOWN)
        self.assertIn("engine_code is not confirmed", result.reasons)

    def test_identification_drafts_do_not_become_confirmed_fields(self):
        revision = self.store.context.profile_revision
        self.store.add_identification_draft(
            "old-description", "Historical notes say this may be a CCTA",
            {"kind": "historical_note"},
        )
        profile = self.store.profile()
        self.assertEqual(profile.revision, revision)
        self.assertNotIn("engine_code", profile.fields)
        self.assertEqual(
            self.store.evaluate({"engine_code": "CCTA"}).state,
            ApplicabilityState.UNKNOWN,
        )

    def test_confirmed_engine_transmission_market_and_pr_code_mismatch_exclude_source(self):
        evidence = {"kind": "vehicle_label", "reference": "fixture"}
        for name, value in (
            ("engine_code", "CBFA"),
            ("transmission_code", "02E"),
            ("market", "USA"),
            ("brake_pr_codes", ["1LJ"]),
        ):
            self.store.confirm(name, value, evidence)

        matching = {
            "engine_code": "cbfa",
            "transmission_code": "02e",
            "market": "usa",
            "brake_pr_codes": ["1LJ", "1ZD"],
        }
        self.assertEqual(
            self.store.evaluate(matching).state, ApplicabilityState.CONFIRMED_MATCH
        )
        for name, wrong in (
            ("engine_code", "CCTA"),
            ("transmission_code", "09M"),
            ("market", "EU"),
            ("brake_pr_codes", ["1ZE"]),
        ):
            with self.subTest(field=name):
                requirements = dict(matching)
                requirements[name] = wrong
                result = self.store.evaluate(requirements)
                self.assertEqual(result.state, ApplicabilityState.CONFIRMED_MISMATCH)
                self.assertIn(f"{name} does not match", result.reasons)

    def test_profile_change_stales_existing_procedure_approval(self):
        from cc_workshop.garage import GarageRepository

        before = self.registry.context(VIN, "approval")
        approval = GarageRepository(self.registry).open(before).put_record(
            "procedure_approval", {"procedure_id": "brake-service"}
        )
        self.assertFalse(self.store.approval_is_stale(approval))

        self.store.confirm(
            "engine_code", "CBFA", {"kind": "scan", "reference": "fixture"}
        )
        self.assertTrue(self.store.approval_is_stale(approval))

    def test_confirmed_fields_require_evidence_and_revisions_are_recorded(self):
        with self.assertRaises(ValueError):
            self.store.confirm("engine_code", "CBFA", {})
        original = self.store.context.profile_revision
        self.store.confirm(
            "engine_code", "CBFA", {"kind": "scan", "reference": "fixture"}
        )
        self.assertEqual(self.store.context.profile_revision, original + 1)
        self.assertEqual(self.store.profile().fields["engine_code"].value, "CBFA")

        with self.store.repository.connection() as connection:
            history = connection.execute(
                "SELECT COUNT(*) FROM vehicle_profile_history WHERE vin = ?", (VIN,)
            ).fetchone()[0]
        self.assertEqual(history, 1)


if __name__ == "__main__":
    unittest.main()
