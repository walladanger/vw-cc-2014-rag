import dataclasses
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import MappingProxyType

from cc_workshop.contracts import VehicleContext


VIN_A = "WVWZZZ3CZEE123456"
VIN_B = "WVWZZZ3CZEE654321"


class GarageIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _registry(self):
        from cc_workshop.garage import GarageRegistry

        return GarageRegistry(self.root)

    def test_two_garages_use_separate_sqlite_and_vector_roots_and_survive_restart(self):
        from cc_workshop.garage import GarageRepository

        registry = self._registry()
        first = registry.create(VIN_A, display_name="Blue CC", request_id="create-a")
        second = registry.create(VIN_B, display_name="Black CC", request_id="create-b")
        repository = GarageRepository(registry)
        repo_a = repository.open(registry.context(VIN_A, "write-a"))
        repo_b = repository.open(registry.context(VIN_B, "write-b"))
        repo_a.put_record("note", {"value": "garage-a"}, record_id="shared-name")
        repo_b.put_record("note", {"value": "garage-b"}, record_id="shared-name")

        self.assertNotEqual(first.database_path, second.database_path)
        self.assertTrue(first.database_path.is_file())
        self.assertTrue(second.database_path.is_file())
        self.assertNotEqual(first.vector_root, second.vector_root)
        self.assertTrue(first.vector_root.is_dir())
        self.assertTrue(second.vector_root.is_dir())

        restarted = GarageRepository(self._registry())
        self.assertEqual(
            restarted.open(self._registry().context(VIN_A, "read-a")).get_record("shared-name").payload["value"],
            "garage-a",
        )
        self.assertEqual(
            restarted.open(self._registry().context(VIN_B, "read-b")).get_record("shared-name").payload["value"],
            "garage-b",
        )

    def test_record_id_from_another_garage_is_scoped_not_found(self):
        from cc_workshop.garage import GarageNotFound, GarageRepository

        registry = self._registry()
        registry.create(VIN_A, display_name="A", request_id="create-a")
        registry.create(VIN_B, display_name="B", request_id="create-b")
        repository = GarageRepository(registry)
        record = repository.open(registry.context(VIN_A, "write-a")).put_record(
            "measurement", {"psi": 31}
        )

        with self.assertRaises(GarageNotFound):
            repository.open(registry.context(VIN_B, "read-b")).get_record(record.id)

    def test_public_record_store_round_trips_and_validates_kind(self):
        from cc_workshop.garage import GarageRepository

        registry = self._registry()
        registry.create(VIN_A, display_name="A", request_id="create")
        scoped = GarageRepository(registry).open(registry.context(VIN_A, "records"))
        created = scoped.put_record("diagnostic_session", {"codes": ["P0300"]})

        self.assertEqual(created.kind, "diagnostic_session")
        self.assertEqual(created.schema_version, 1)
        self.assertEqual(created.profile_revision, 1)
        self.assertEqual(created.library_revision, "0")
        self.assertEqual(scoped.get_record(created.id).payload["codes"], ("P0300",))
        self.assertIsInstance(created.payload, MappingProxyType)
        with self.assertRaises(TypeError):
            created.payload["codes"] = ()
        self.assertEqual([item.id for item in scoped.list_records("diagnostic_session")], [created.id])
        self.assertTrue(scoped.delete_record(created.id))
        self.assertFalse(scoped.delete_record(created.id))
        for invalid in ("", "records; DROP TABLE records", "../note", "UPPER CASE"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                scoped.put_record(invalid, {})

    def test_traversal_absolute_and_link_escapes_are_rejected(self):
        from cc_workshop.operations.paths import UnsafePathError, resolve_within

        safe_root = self.root / "safe"
        outside = self.root / "outside"
        safe_root.mkdir()
        outside.mkdir()
        for part in ("../outside", str(outside.resolve())):
            with self.subTest(part=part), self.assertRaises(UnsafePathError):
                resolve_within(safe_root, part)

        link = safe_root / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("creating directory links is unavailable on this Windows account")
        with self.assertRaises(UnsafePathError):
            resolve_within(safe_root, "escape", "private.sqlite")

    def test_context_is_immutable_and_concurrent_requests_do_not_cross(self):
        registry = self._registry()
        registry.create(VIN_A, display_name="A", request_id="create-a")
        registry.create(VIN_B, display_name="B", request_id="create-b")
        barrier = threading.Barrier(2)
        results = {}

        def capture(vin, request_id):
            context = registry.context(vin, request_id)
            barrier.wait()
            results[request_id] = context

        threads = [
            threading.Thread(target=capture, args=(VIN_A, "request-a")),
            threading.Thread(target=capture, args=(VIN_B, "request-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results["request-a"].vin, VIN_A)
        self.assertEqual(results["request-b"].vin, VIN_B)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            results["request-a"].request_id = "changed"

    def test_open_handle_validates_context_again_on_every_operation(self):
        from cc_workshop.garage import GarageRepository, StaleVehicleContext

        registry = self._registry()
        garage = registry.create(VIN_A, display_name="A", request_id="create")
        scoped = GarageRepository(registry).open(registry.context(VIN_A, "stale"))
        existing = scoped.put_record("note", {"before": True})
        with closing(sqlite3.connect(garage.database_path)) as connection:
            with connection:
                connection.execute("UPDATE garage_meta SET value = '2' WHERE key = 'profile_revision'")

        operations = (
            lambda: scoped.put_record("note", {"after": True}),
            lambda: scoped.get_record(existing.id),
            lambda: scoped.list_records("note"),
            lambda: scoped.delete_record(existing.id),
            lambda: scoped.connection().__enter__(),
        )
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(StaleVehicleContext):
                operation()

    def test_registry_rejects_tampered_absolute_storage_mapping(self):
        from cc_workshop.garage import GarageRegistry
        from cc_workshop.operations.paths import UnsafePathError

        registry = self._registry()
        registry.create(VIN_A, display_name="A", request_id="create")
        outside = self.root.parent / "outside.sqlite"
        with closing(sqlite3.connect(registry.paths.registry_db)) as connection:
            with connection:
                connection.execute(
                    "UPDATE garages SET database_path = ? WHERE vin = ?", (str(outside), VIN_A)
                )
        with self.assertRaises(UnsafePathError):
            registry.get(VIN_A)

    def test_registry_accepts_legacy_absolute_mapping_under_data_root(self):
        from cc_workshop.garage import GarageRegistry

        registry = self._registry()
        garage = registry.create(VIN_A, display_name="A", request_id="create")
        with closing(sqlite3.connect(registry.paths.registry_db)) as connection:
            with connection:
                connection.execute(
                    "UPDATE garages SET database_path = ?, vector_root = ? WHERE vin = ?",
                    (str(garage.database_path), str(garage.vector_root), VIN_A),
                )
        loaded = registry.get(VIN_A)
        self.assertEqual(loaded.database_path, garage.database_path)
        self.assertEqual(loaded.vector_root, garage.vector_root)


class InstanceLockTests(unittest.TestCase):
    def test_only_one_lock_owns_a_data_root(self):
        from cc_workshop.operations.instance_lock import InstanceAlreadyRunning, InstanceLock

        with tempfile.TemporaryDirectory() as tmp:
            first = InstanceLock(Path(tmp))
            second = InstanceLock(Path(tmp))
            first.acquire()
            try:
                with self.assertRaises(InstanceAlreadyRunning):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
