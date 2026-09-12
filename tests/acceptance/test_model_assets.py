import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def write_asset(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "filename": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


class ModelAssetTests(unittest.TestCase):
    def manifest(self, **overrides):
        data = {
            "model_id": "qwen3-vl-4b-instruct-q4",
            "revision": "rev-1",
            "family": "qwen3-vl",
            "modality": "vision",
            "license": "fixture-license",
            "runtime": "llama.cpp",
            "assets": [],
        }
        data.update(overrides)
        return data

    def test_offline_import_records_hashes_revision_license_and_rejects_network(self):
        from cc_workshop.model_assets import ModelAssetStore, ModelManifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "offline-kit"
            source.mkdir()
            model_asset = write_asset(source, "model.gguf", b"model-bytes")
            projector_asset = write_asset(source, "mmproj.gguf", b"projector-bytes")
            manifest = ModelManifest.from_dict(self.manifest(assets=[
                {**model_asset, "role": "weights", "required_for": ["text"]},
                {**projector_asset, "role": "projector", "required_for": ["vision"]},
            ]))

            with patch.object(socket, "create_connection", side_effect=AssertionError("network was used")):
                installed = ModelAssetStore(root / "store").import_offline(manifest, source)

            self.assertEqual(installed.model_id, "qwen3-vl-4b-instruct-q4")
            self.assertEqual(installed.revision, "rev-1")
            self.assertEqual(installed.license, "fixture-license")
            self.assertTrue((installed.install_root / "manifest.json").is_file())
            saved = json.loads((installed.install_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["revision"], "rev-1")
            self.assertEqual(saved["assets"][0]["sha256"], model_asset["sha256"])
            self.assertEqual(saved["assets"][1]["role"], "projector")

    def test_missing_or_mismatched_projector_prevents_vision_activation(self):
        from cc_workshop.model_assets import ModelAssetError, ModelAssetStore, ModelManifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "kit"
            source.mkdir()
            model_asset = write_asset(source, "model.gguf", b"model")
            missing_projector = ModelManifest.from_dict(self.manifest(assets=[
                {**model_asset, "role": "weights", "required_for": ["text"]},
            ]))

            with self.assertRaises(ModelAssetError) as caught:
                ModelAssetStore(root / "store").import_offline(missing_projector, source)
            self.assertEqual(caught.exception.code, "VISION_PROJECTOR_MISSING")

            projector = write_asset(source, "mmproj.gguf", b"projector")
            bad_hash = dict(projector)
            bad_hash["sha256"] = "0" * 64
            mismatched = ModelManifest.from_dict(self.manifest(assets=[
                {**model_asset, "role": "weights", "required_for": ["text"]},
                {**bad_hash, "role": "projector", "required_for": ["vision"]},
            ]))
            with self.assertRaises(ModelAssetError) as caught:
                ModelAssetStore(root / "store2").import_offline(mismatched, source)
            self.assertEqual(caught.exception.code, "ASSET_HASH_MISMATCH")

    def test_corrupt_partial_and_unsafe_files_are_rejected(self):
        from cc_workshop.model_assets import ModelAssetError, ModelAssetStore, ModelManifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "kit"
            source.mkdir()
            model_asset = write_asset(source, "model.gguf", b"complete")
            projector = write_asset(source, "mmproj.gguf", b"projector")
            partial = dict(model_asset)
            partial["size_bytes"] = model_asset["size_bytes"] + 10

            for bad_asset, expected in (
                (partial, "ASSET_SIZE_MISMATCH"),
                ({**model_asset, "filename": "../model.gguf"}, "UNSAFE_ASSET_PATH"),
            ):
                with self.subTest(expected=expected), self.assertRaises(ModelAssetError) as caught:
                    manifest = ModelManifest.from_dict(self.manifest(assets=[
                        {**bad_asset, "role": "weights", "required_for": ["text"]},
                        {**projector, "role": "projector", "required_for": ["vision"]},
                    ]))
                    ModelAssetStore(root / expected).import_offline(manifest, source)
                self.assertEqual(caught.exception.code, expected)

    def test_hardware_profiles_use_actual_detected_devices_not_model_name_guessing(self):
        from cc_workshop.model_assets import (
            HardwareDevice,
            HardwareInventory,
            ModelManifest,
            recommended_profiles,
        )

        manifest = ModelManifest.from_dict(self.manifest(
            model_id="giant-32b-dual-gpu-name",
            modality="text",
            assets=[{
                "filename": "model.gguf",
                "sha256": "a" * 64,
                "size_bytes": 10,
                "role": "weights",
                "required_for": ["text"],
            }],
        ))

        cpu_only = HardwareInventory(devices=(HardwareDevice("cpu", "Ryzen", None),))
        cpu_profiles = recommended_profiles(manifest, cpu_only)
        self.assertEqual([profile.name for profile in cpu_profiles], ["compact_cpu"])
        self.assertEqual(cpu_profiles[0].device_ids, ("cpu:0",))

        dual_gpu = HardwareInventory(devices=(
            HardwareDevice("cpu", "Ryzen", None),
            HardwareDevice("gpu", "RTX 3090 A", 24 * 1024**3),
            HardwareDevice("gpu", "RTX 3090 B", 24 * 1024**3),
        ))
        gpu_profiles = recommended_profiles(manifest, dual_gpu)
        self.assertEqual([profile.name for profile in gpu_profiles],
                         ["compact_cpu", "single_gpu", "multiple_gpu"])
        self.assertEqual(gpu_profiles[-1].device_ids, ("gpu:0", "gpu:1"))

    def test_identifiers_cannot_escape_store_and_sentinel_survives(self):
        from cc_workshop.model_assets import ModelManifest, ModelAssetStore
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"kit"; source.mkdir(); sentinel=root/"sentinel"; sentinel.write_text("untouched")
            asset=write_asset(source,"model.gguf",b"model")
            # Resolve each potentially traversing identifier against both baseline bases before import.
            for base in (root/"store", root/"store"/"qwen3-vl-4b-instruct-q4"):
                for value in ("a/../../outside", (root/"drive-outside").as_posix(), "../sentinel"):
                    (base/value).resolve().relative_to(root.resolve())
            for field in ("model_id", "revision"):
                for value in ("a/../../outside", (root/"drive-outside").as_posix(), "../sentinel"):
                    with self.subTest(field=field,value=value), self.assertRaises((ValueError,RuntimeError)):
                        ModelAssetStore(root/"store").import_offline(ModelManifest.from_dict(self.manifest(modality="text",assets=[asset],**{field:value})),source)
            self.assertEqual(sentinel.read_text(),"untouched")
            self.assertFalse((root/"outside").exists())

    def test_staged_bytes_and_duplicate_paths_verified(self):
        import shutil
        from cc_workshop.model_assets import ModelManifest, ModelAssetStore, ModelAssetError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"kit"; source.mkdir(); asset=write_asset(source,"model.gguf",b"model")
            with self.assertRaises((ValueError, ModelAssetError)):
                ModelManifest.from_dict(self.manifest(modality="text",assets=[asset,asset]))
            manifest=ModelManifest.from_dict(self.manifest(modality="text",assets=[asset]))
            original=shutil.copy2
            def corrupt(src,dst):
                result=original(src,dst); Path(dst).write_bytes(b"wrong"); return result
            with patch("cc_workshop.model_assets.shutil.copy2",side_effect=corrupt), self.assertRaises(ModelAssetError):
                ModelAssetStore(root/"store").import_offline(manifest,source)

    def test_installed_vision_projector_reverified(self):
        from cc_workshop.model_assets import ModelManifest, ModelAssetStore, ModelAssetError
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"kit"; source.mkdir()
            weights=write_asset(source,"model.gguf",b"model")
            projector=write_asset(source,"projector.gguf",b"projection")
            manifest=ModelManifest.from_dict(self.manifest(assets=[{**weights,"role":"weights"},{**projector,"role":"projector","required_for":["vision"]}]))
            installed=ModelAssetStore(root/"store").import_offline(manifest,source)
            installed.verify()[1].unlink()
            with self.assertRaises(ModelAssetError): installed.verify()


if __name__ == "__main__":
    unittest.main()
