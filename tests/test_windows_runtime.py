import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsRuntimeTests(unittest.TestCase):
    def test_first_launch_creates_writable_logs_and_data(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, LOCALAPPDATA=directory,
                       VW_RAG_OUT=str(Path(directory) / "out"),
                       ENABLE_MANUAL_REVIEW="0")
            result = subprocess.run(
                [sys.executable, "-c", "import desktop"], cwd=ROOT,
                env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(directory) / "CC Workshop/logs/boot.log").is_file())
            self.assertTrue((Path(directory) / "out").is_dir())

    def test_manual_bundle_has_no_scan_analytics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus = root / "corpus" / "manual"
            corpus.mkdir(parents=True)
            (corpus / "manifest.json").write_text('{"manual_id":"sample"}')
            output = root / "bundle"
            result = subprocess.run(
                [sys.executable, "build_vag_database.py", "--corpus", str(corpus.parent),
                 "--output", str(output), "--no-embeddings"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest["source_count"], 1)
            self.assertNotIn("analytics", manifest)
            self.assertFalse((output / "analytics").exists())

    def test_bundle_rejects_removed_report_argument(self):
        result = subprocess.run(
            [sys.executable, "build_vag_database.py", "--corpus", ".",
             "--output", ".", "--diagnostics", "."],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)
