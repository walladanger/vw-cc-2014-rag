import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vag_pipeline.common import redact_vins, safe_vehicle_id, stable_id
from vag_pipeline.corpus import classify_chunk, normalize_chunk
from vag_pipeline.diagnostics import parse_icarsoft_report
from vag_pipeline.uploader import upload_bundle
from vag_pipeline.analytics import export_analytics
from vag_pipeline.diagnostics import TABLE_COLUMNS


class PipelineTests(unittest.TestCase):
    def test_stable_ids_are_repeatable(self):
        self.assertEqual(stable_id("a", 1), stable_id("a", 1))
        self.assertNotEqual(stable_id("a", 1), stable_id("a", 2))

    def test_source_tiers_are_isolated(self):
        self.assertEqual(
            classify_chunk({"manual_id": "vw_cc_brakes", "source_type": "manual"})[0],
            "vag_manual_chunks",
        )
        self.assertEqual(
            classify_chunk({"manual_id": "autodoc_brakes", "source_type": "manual"})[0],
            "vag_community_guides",
        )

    def test_engine_codes_are_payload_filters(self):
        record = normalize_chunk(
            {
                "chunk_id": "x",
                "chunk_hash": "abc",
                "text": "Threshold applies to CCTA only.",
                "engine": "2.0 TSI CCTA",
                "manual_id": "dtc",
            },
            Path("chunks.jsonl"),
        )
        self.assertEqual(record.payload["engine_codes"], ["CCTA"])

    def test_identical_text_on_different_pages_has_unique_ids(self):
        base = {
            "chunk_hash": "same",
            "text": "Repeated safety notice",
            "manual_id": "manual",
        }
        first = normalize_chunk({**base, "chunk_id": "p1", "page_physical": 1}, Path("a"))
        second = normalize_chunk({**base, "chunk_id": "p2", "page_physical": 2}, Path("a"))
        self.assertNotEqual(first.point_id, second.point_id)

    def test_vin_is_hashed_in_diagnostic_export(self):
        report = """[APP_PARAM]
Version=V34.30
[DIAG_PARAM]
VIN=WVWBP7AN0EE528963
[VEH_INFO]
01_Value=WVWBP7AN0EE528963
02_Value=VW
03_Value=2014
[DTC_REPORT]
SysNum=1
DtcCount=1
[01_SYSTEM]
Name=01 Engine Electronics
Status=Fault
DtcNum=1
01_Code=P0299
01_Status=Static
01_Content=Underboost
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "20260420002202_test_decoded.txt"
            path.write_text(report, encoding="utf-8")
            tables, catalog = parse_icarsoft_report(path, "salt")
        vehicle_id = tables["vehicle_profiles"][0]["vehicle_id"]
        self.assertTrue(vehicle_id.startswith("veh_"))
        self.assertNotIn("WVWBP7AN0EE528963", json.dumps(tables))
        self.assertEqual(catalog[0].payload["write_capability"], "disabled")
        self.assertNotIn(
            "WVWBP7AN0EE528963",
            redact_vins("prefix_WVWBP7AN0EE528963_suffix"),
        )

    def test_empty_analytics_tables_keep_csv_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            export_analytics(
                Path(directory), {name: [] for name in TABLE_COLUMNS}
            )
            header = (
                Path(directory) / "analytics" / "measurement_samples.csv"
            ).read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("measurement_name", header)

    def test_qdrant_upload_is_resumable(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(("GET", self.path, None))
                self.send_response(404)
                self.end_headers()

            def do_PUT(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                calls.append(("PUT", self.path, body))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "qdrant").mkdir()
                points = root / "qdrant" / "test.points.jsonl"
                points.write_text(
                    "\n".join(
                        json.dumps({"id": str(i), "vector": [1.0, 0.0], "payload": {}})
                        for i in range(3)
                    )
                    + "\n",
                    encoding="utf-8",
                )
                (root / "qdrant_manifest.json").write_text(
                    json.dumps(
                        {
                            "vector_size": 2,
                            "distance": "Cosine",
                            "collections": {
                                "test": {"file": points.name, "points": 3}
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                url = f"http://127.0.0.1:{server.server_port}"
                upload_bundle(root, url, batch_size=2)
                first_puts = len([call for call in calls if "/points" in call[1]])
                upload_bundle(root, url, batch_size=2)
                second_puts = len([call for call in calls if "/points" in call[1]])
                self.assertEqual(first_puts, 2)
                self.assertEqual(second_puts, first_puts)
                state = json.loads((root / "upload_state.json").read_text())
                self.assertEqual(state["test"], 3)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
