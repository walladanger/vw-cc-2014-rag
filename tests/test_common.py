import unittest
import tempfile
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timezone

from vag_pipeline.common import (
    now_iso, sha256_bytes, sha256_file, stable_id, json_dump, jsonl_rows,
    redact_vins, safe_vehicle_id, clean_text, normalized_engine_codes
)


class TestCommon(unittest.TestCase):
    def test_now_iso(self):
        iso = now_iso()
        self.assertTrue(iso.endswith("+00:00"))
        # Parse it to ensure valid datetime
        dt = datetime.fromisoformat(iso)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_sha256_bytes(self):
        data = b"hello world"
        self.assertEqual(sha256_bytes(data), hashlib.sha256(data).hexdigest())

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Empty file
            empty_file = tmpdir_path / "empty.txt"
            empty_file.write_bytes(b"")
            self.assertEqual(sha256_file(empty_file), hashlib.sha256(b"").hexdigest())

            # Non-empty file, small block size
            data = b"a" * 1000 + b"b" * 1000
            data_file = tmpdir_path / "data.txt"
            data_file.write_bytes(data)
            self.assertEqual(sha256_file(data_file, block_size=10), hashlib.sha256(data).hexdigest())

    def test_stable_id(self):
        id1 = stable_id("a", "b", "c")
        id2 = stable_id("a", "b", "c")
        self.assertEqual(id1, id2)  # Deterministic

        # None vs '' equivalence
        id3 = stable_id("a", None, "c")
        id4 = stable_id("a", "", "c")
        self.assertEqual(id3, id4)

        # Order sensitivity
        id5 = stable_id("c", "b", "a")
        self.assertNotEqual(id1, id5)

        # Valid UUID5
        parsed_uuid = uuid.UUID(id1)
        self.assertEqual(parsed_uuid.version, 5)

    def test_json_dump(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir) / "sub" / "dir"
            file_path = base_dir / "test.json"

            data = {"key": "value", "non_ascii": "こんにちは"}

            # Creates parent dirs, UTF-8 non-ASCII preserved
            json_dump(file_path, data)
            self.assertTrue(file_path.exists())

            # No leftover .tmp file
            tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
            self.assertFalse(tmp_path.exists())

            content = file_path.read_text(encoding="utf-8")
            self.assertIn("こんにちは", content)

            # Overwrite
            new_data = {"new": "data"}
            json_dump(file_path, new_data)
            content = file_path.read_text(encoding="utf-8")
            self.assertIn("new", content)
            self.assertNotIn("こんにちは", content)

    def test_jsonl_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.jsonl"

            # skips blank lines, handles UTF-8 BOM
            content = b'\xef\xbb\xbf{"a": 1}\n\n{"b": 2}\n  \n{"c": 3}\n'
            file_path.write_bytes(content)

            rows = list(jsonl_rows(file_path))
            self.assertEqual(rows, [{"a": 1}, {"b": 2}, {"c": 3}])

            # ValueError message includes path:line_no on bad JSON
            bad_content = '{"a": 1}\nbad json\n{"c": 3}'
            file_path.write_text(bad_content, encoding="utf-8")

            iterator = jsonl_rows(file_path)
            self.assertEqual(next(iterator), {"a": 1})
            with self.assertRaises(ValueError) as cm:
                next(iterator)

            self.assertIn(f"{file_path}:2: invalid JSON", str(cm.exception))

    def test_redact_vins(self):
        # 17-char VINs redacted
        valid_vin = "1VWBT7A30CC123456"  # 17 chars, no I, O, Q
        self.assertEqual(redact_vins(valid_vin), "[VIN REDACTED]")

        # Case insensitive
        self.assertEqual(redact_vins(valid_vin.lower()), "[VIN REDACTED]")

        # I/O/Q excluded (these shouldn't be redacted)
        invalid_vin_i = "1VWBT7A30IC123456"
        self.assertEqual(redact_vins(invalid_vin_i), invalid_vin_i)

        invalid_vin_o = "1VWBT7A30OC123456"
        self.assertEqual(redact_vins(invalid_vin_o), invalid_vin_o)

        invalid_vin_q = "1VWBT7A30QC123456"
        self.assertEqual(redact_vins(invalid_vin_q), invalid_vin_q)

        # Not when embedded in longer alphanumerics
        embedded_vin = "A1VWBT7A30CC123456B"
        self.assertEqual(redact_vins(embedded_vin), embedded_vin)

        embedded_vin2 = "1VWBT7A30CC12345689"
        self.assertEqual(redact_vins(embedded_vin2), embedded_vin2)

    def test_safe_vehicle_id(self):
        # Empty -> ''
        self.assertEqual(safe_vehicle_id("", "salt"), "")
        self.assertEqual(safe_vehicle_id(None, "salt"), "")

        # Case-insensitive VIN
        vin = "1VWBT7A30CC123456"
        id1 = safe_vehicle_id(vin, "salt")
        id2 = safe_vehicle_id(vin.lower(), "salt")
        self.assertEqual(id1, id2)

        # Salt changes output
        id3 = safe_vehicle_id(vin, "salt2")
        self.assertNotEqual(id1, id3)

        # 'veh_' + 20 hex
        self.assertTrue(id1.startswith("veh_"))
        self.assertEqual(len(id1), 24)  # 4 + 20
        # Check if the rest is hex
        int(id1[4:], 16)  # Should not raise ValueError

    def test_clean_text(self):
        # whitespace collapse
        self.assertEqual(clean_text("  a   b\tc\n d  "), "a b c d")

        # None -> ''
        self.assertEqual(clean_text(None), "")

    def test_normalized_engine_codes(self):
        # empty input
        self.assertEqual(normalized_engine_codes(None), [])
        self.assertEqual(normalized_engine_codes(""), [])

        # stop words removed, sorted unique
        # regex \b[A-Z][A-Z0-9]{2,4}\b matches 3-5 char tokens starting with a letter
        text = "Engine EA888 TDI CJSB TSI EA888 AND"
        codes = normalized_engine_codes(text)
        self.assertEqual(codes, ["AND", "CJSB", "EA888"])

        text2 = "VAG VW AUDI NONE"
        self.assertEqual(normalized_engine_codes(text2), [])
