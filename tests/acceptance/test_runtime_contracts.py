import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import closing
from pathlib import Path


class VehicleContextContractTests(unittest.TestCase):
    def test_context_is_immutable_and_copies_source_ids(self):
        from cc_workshop.contracts import VehicleContext

        source_ids = ["manual-b", "manual-a", "manual-b"]
        context = VehicleContext(
            vin=" wvwZZZ3cZEE123456 ",
            profile_revision=3,
            library_revision="lib-7",
            approved_source_ids=source_ids,
            request_id="request-1",
        )
        source_ids.append("manual-c")

        self.assertEqual(context.vin, "WVWZZZ3CZEE123456")
        self.assertEqual(context.approved_source_ids, ("manual-b", "manual-a"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            context.vin = "WVWZZZ3CZEE999999"

    def test_context_rejects_incomplete_identity(self):
        from cc_workshop.contracts import VehicleContext

        valid = dict(
            vin="WVWZZZ3CZEE123456",
            profile_revision=1,
            library_revision="lib-1",
            approved_source_ids=(),
            request_id="request-1",
        )
        for field, bad in (
            ("vin", "draft"),
            ("profile_revision", 0),
            ("profile_revision", 1.5),
            ("profile_revision", True),
            ("library_revision", ""),
            ("request_id", "  "),
        ):
            values = dict(valid)
            values[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                VehicleContext(**values)

    def test_context_rejects_string_or_non_string_source_ids(self):
        from cc_workshop.contracts import VehicleContext

        values = dict(
            vin="WVWZZZ3CZEE123456",
            profile_revision=1,
            library_revision="lib-1",
            request_id="request-1",
        )
        for source_ids in ("manual-1", b"manual-1", ("manual-1", 2), ("",)):
            with self.subTest(source_ids=source_ids), self.assertRaises((TypeError, ValueError)):
                VehicleContext(approved_source_ids=source_ids, **values)


class RuntimePathTests(unittest.TestCase):
    def test_default_root_uses_local_app_data_and_initializes_writable_tree(self):
        from cc_workshop.operations.config import load_runtime_config
        from cc_workshop.operations.paths import initialize_data_root

        with tempfile.TemporaryDirectory() as tmp:
            config = load_runtime_config({"LOCALAPPDATA": tmp})
            paths = initialize_data_root(config.data_root)

            self.assertEqual(config.bind_host, "127.0.0.1")
            self.assertEqual(paths.root, Path(tmp) / "CC Workshop")
            for directory in (
                paths.configuration,
                paths.models,
                paths.shared_sources,
                paths.staging,
                paths.jobs,
                paths.logs,
                paths.backups,
                paths.garages,
            ):
                self.assertTrue(directory.is_dir(), directory)

    def test_explicit_data_root_and_bind_override_are_honored(self):
        from cc_workshop.operations.config import load_runtime_config

        with tempfile.TemporaryDirectory() as tmp:
            config = load_runtime_config({
                "CC_WORKSHOP_DATA_ROOT": tmp,
                "CC_WORKSHOP_BIND_HOST": "192.168.1.20",
                "PORT": "5099",
            })

            self.assertEqual(config.data_root, Path(tmp).resolve())
            self.assertEqual(config.bind_host, "192.168.1.20")
            self.assertEqual(config.port, 5099)

    def test_invalid_port_is_rejected(self):
        from cc_workshop.operations.config import load_runtime_config

        for value in ("zero", "0", "65536"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_runtime_config({"LOCALAPPDATA": os.getcwd(), "PORT": value})

    def test_desktop_startup_writes_boot_log_under_explicit_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / "private-data"
            environment = dict(os.environ)
            environment["CC_WORKSHOP_DATA_ROOT"] = str(data_root)
            proc = subprocess.run(
                [sys.executable, "-c", "import desktop, json; print(json.dumps(str(desktop.DATA_DIR)))"],
                cwd=Path(__file__).resolve().parents[2],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout.splitlines()[-1]), str(data_root.resolve()))
            self.assertTrue((data_root / "logs" / "boot.log").is_file())

    def test_web_server_options_default_to_loopback(self):
        from web_server import server_options

        self.assertEqual(server_options({})["host"], "127.0.0.1")
        self.assertEqual(server_options({"CC_WORKSHOP_BIND_HOST": "10.0.0.8"})["host"], "10.0.0.8")

    def test_browser_app_defaults_legacy_library_to_explicit_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            environment = dict(os.environ)
            environment["CC_WORKSHOP_DATA_ROOT"] = tmp
            environment.pop("VW_RAG_OUT", None)
            proc = subprocess.run(
                [sys.executable, "-c", "import app; print(app.OUT_DIR)"],
                cwd=Path(__file__).resolve().parents[2],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.splitlines()[-1]), Path(tmp).resolve() / "out")


class RetrievalCompatibilityTests(unittest.TestCase):
    class _Embedder:
        def encode_query(self, query):
            return [1.0]

    class _Collection:
        def count(self):
            return 2

        def query(self, **kwargs):
            return {"ids": [["audi", "cc"]], "distances": [[0.1, 0.2]]}

    class _Bm25:
        def get_scores(self, tokens):
            return [2.0, 1.0]

    def test_local_embedder_opens_only_preprovisioned_model_assets(self):
        import types
        from unittest.mock import patch
        from retrieve import LocalEmbedder

        calls = []

        class FakeSentenceTransformer:
            def __init__(self, model, **kwargs):
                calls.append((model, kwargs))

        fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            LocalEmbedder()

        self.assertEqual(calls, [("all-MiniLM-L6-v2", {"local_files_only": True})])

    def test_chroma_retrieve_accepts_profile_and_filters_wrong_vehicle(self):
        from retrieve import ChromaLibrary

        library = ChromaLibrary.__new__(ChromaLibrary)
        library.embedder = self._Embedder()
        library._col = self._Collection()
        library._bm25 = self._Bm25()
        library.chunks = [
            {"chunk_id": "audi", "text": "starter", "vehicle": "2014 Audi A4", "engine": "CAEB"},
            {"chunk_id": "cc", "text": "starter", "vehicle": "2014 VW CC 2.0T TSI", "engine": "CBFA"},
        ]
        library._ids = ["audi", "cc"]
        library._by_id = {item["chunk_id"]: item for item in library.chunks}

        results = library.retrieve(
            "starter",
            profile={"vehicle": "2014 VW CC 2.0T TSI", "engine": "CBFA"},
        )

        self.assertEqual([item["chunk_id"] for item in results], ["cc"])

    def test_real_chroma_store_obeys_profile_filter(self):
        import chromadb
        from chromadb.api.client import SharedSystemClient
        from retrieve import ChromaLibrary

        class TwoDimensionalEmbedder:
            def encode_query(self, query):
                return [0.0, 1.0]

        chunks = [
            {"chunk_id": "audi", "text": "starter Audi", "vehicle": "2014 Audi A4", "engine": "CAEB"},
            {"chunk_id": "cc", "text": "starter CC", "vehicle": "2014 VW CC 2.0T TSI", "engine": "CBFA"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual = root / "manual"
            manual.mkdir()
            (manual / "chunks.jsonl").write_text(
                "\n".join(json.dumps(item) for item in chunks), encoding="utf-8"
            )
            client = chromadb.PersistentClient(path=str(root / "chroma_db"))
            collection = client.get_or_create_collection(
                "vw_rag", metadata={"hnsw:space": "cosine"}
            )
            collection.add(
                ids=["audi", "cc"],
                embeddings=[[1.0, 0.0], [0.0, 1.0]],
                documents=["starter Audi", "starter CC"],
            )
            library = ChromaLibrary(str(root), TwoDimensionalEmbedder())

            results = library.retrieve(
                "starter",
                profile={"vehicle": "2014 VW CC 2.0T TSI", "engine": "CBFA"},
            )

            client._system.stop()
            SharedSystemClient.clear_system_cache()

        self.assertEqual([item["chunk_id"] for item in results], ["cc"])

    def test_application_rejects_cloud_embedding_mode_before_backend_activation(self):
        import importlib
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as app_data:
            with patch.dict(os.environ, {"CC_WORKSHOP_DATA_ROOT": app_data}):
                app_module = importlib.import_module("app")

        previous = (app_module.EMBEDDER, app_module.OUT_DIR, app_module._library)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app_module.EMBEDDER = "dual"
                app_module.OUT_DIR = tmp
                app_module._library = None
                with self.assertRaisesRegex(RuntimeError, "offline runtime"):
                    app_module.get_library()
        finally:
            app_module.EMBEDDER, app_module.OUT_DIR, app_module._library = previous

    def test_query_returns_structured_unavailable_when_retrieval_backend_fails(self):
        import importlib
        import sqlite3
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as app_data:
            with patch.dict(os.environ, {"CC_WORKSHOP_DATA_ROOT": app_data}):
                app_module = importlib.import_module("app")

        class UnreachableLibrary:
            def retrieve(self, *args, **kwargs):
                raise urllib.error.URLError("local embedder unavailable")

        previous = (app_module.OUT_DIR, app_module._library)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manual = root / "manual"
                manual.mkdir()
                (manual / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
                app_module.OUT_DIR = str(root)
                app_module._library = UnreachableLibrary()
                app_module.configure_garage_boundary(root / "private")
                registry = app_module.app.extensions["garage_registry"]
                garage = registry.create(
                    "WVWZZZ3CZEE123456", display_name="Test CC", request_id="create"
                )
                with closing(sqlite3.connect(garage.database_path)) as connection:
                    with connection:
                        connection.execute(
                            "INSERT INTO source_associations(vin, source_id) VALUES (?, ?)",
                            (garage.vin, "manual"),
                        )

                response = app_module.app.test_client().post(
                    "/query",
                    headers={"X-Vehicle-VIN": garage.vin},
                    json={"q": "starter"},
                )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()["error"], "library_unavailable")
        finally:
            app_module.OUT_DIR, app_module._library = previous


class DependencyBoundaryTests(unittest.TestCase):
    def _requirements(self, filename):
        path = Path(__file__).resolve().parents[2] / filename
        names = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-r"):
                continue
            names.add(line.split("=", 1)[0].split("<", 1)[0].split(">", 1)[0].lower())
        return names

    def test_required_runtime_excludes_optional_ml_and_video_packages(self):
        runtime = self._requirements("requirements.txt")

        self.assertTrue({
            "flask", "waitress", "chromadb", "httpx", "pymupdf", "pillow", "reportlab", "pypdf"
        } <= runtime)
        self.assertTrue({
            "torch", "transformers", "sentence-transformers", "openai-whisper", "yt-dlp"
        }.isdisjoint(runtime))

    def test_development_and_packaging_dependencies_are_separate(self):
        development = self._requirements("requirements-dev.txt")
        packaging = self._requirements("requirements-packaging.txt")

        self.assertIn("pytest", development)
        self.assertIn("pyinstaller", packaging)
        self.assertIn("pywebview", packaging)

    def test_resolved_python312_windows_lock_is_exact_and_excludes_optional_ml(self):
        lock_path = Path(__file__).resolve().parents[2] / "requirements-py312-win.lock"
        lines = [
            line.strip() for line in lock_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]

        self.assertTrue(lines)
        self.assertTrue(all("==" in line for line in lines))
        names = {line.split("==", 1)[0].lower() for line in lines}
        self.assertIn("chromadb", names)
        self.assertIn("pytest", names)
        self.assertTrue({"torch", "transformers", "sentence-transformers", "openai-whisper"}.isdisjoint(names))


if __name__ == "__main__":
    unittest.main()
