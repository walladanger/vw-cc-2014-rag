import tempfile
import unittest
from pathlib import Path


class OwnedHandle:
    def __init__(self): self.closed = False
    def close(self): self.closed = True


class InferenceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.launched = []
        self.probed = []

    def tearDown(self):
        self.temp.cleanup()

    def manager(self, *, launcher=None, probe=None, allow_quantized_tensor=False):
        from cc_workshop.inference_settings import InferenceSettingsManager, ProfileStore, RuntimePolicy

        return InferenceSettingsManager(
            ProfileStore(self.root),
            RuntimePolicy("llama.cpp-test", allow_quantized_kv_with_tensor_split=allow_quantized_tensor),
            sidecar_launcher=launcher or self._launcher,
            endpoint_probe=probe or self._probe,
        )

    def _launcher(self, role, profile):
        self.launched.append((role, profile.name))
        return OwnedHandle()

    def _probe(self, role, endpoint):
        from cc_workshop.inference_settings import EndpointProbeResult

        self.probed.append((role, endpoint.base_url))
        return EndpointProbeResult(True, endpoint.base_url)

    def profile(self, **overrides):
        raw = {
            "name": "balanced-local",
            "revision": "r1",
            "generation": {"mode": "sidecar", "model_id": "local-qwen"},
            "embeddings": {"mode": "sidecar", "model_id": "embedding-gemma"},
            "hardware": {
                "context_size": 4096,
                "gpu_layers": 35,
                "split_mode": "layer",
                "tensor_split": [],
                "kv_cache_precision": "f16",
                "flash_attention": True,
                "cpu_threads": 8,
                "generation_limit": 512,
            },
        }
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(raw.get(key), dict):
                raw[key] = {**raw[key], **value}
            else:
                raw[key] = value
        return raw

    def test_invalid_hardware_change_does_not_replace_last_working_profile(self):
        from cc_workshop.inference_settings import InferenceSettingsError

        manager = self.manager()
        good = manager.apply_profile(self.profile())

        with self.assertRaises(InferenceSettingsError) as caught:
            manager.apply_profile(self.profile(name="bad", hardware={"context_size": 0}))

        self.assertEqual(caught.exception.code, "INVALID_HARDWARE_SETTING")
        self.assertEqual(manager.store.active_profile().name, good.name)
        self.assertEqual(manager.store.active_profile().hardware.context_size, 4096)

    def test_pinned_build_rejects_quantized_kv_cache_with_tensor_split(self):
        from cc_workshop.inference_settings import InferenceSettingsError

        manager = self.manager()
        manager.apply_profile(self.profile())
        bad = self.profile(
            name="bad-tensor-cache",
            hardware={
                "split_mode": "tensor",
                "tensor_split": [0.5, 0.5],
                "kv_cache_precision": "q8_0",
            },
        )

        with self.assertRaises(InferenceSettingsError) as caught:
            manager.apply_profile(bad)

        self.assertEqual(caught.exception.code, "INVALID_RUNTIME_COMBINATION")
        self.assertEqual(manager.store.active_profile().name, "balanced-local")

        allowed = self.manager(allow_quantized_tensor=True)
        accepted = allowed.apply_profile(bad)
        self.assertEqual(accepted.hardware.split_mode, "tensor")

    def test_external_generation_uses_private_endpoint_and_skips_generation_sidecar(self):
        manager = self.manager()
        applied = manager.apply_profile(
            self.profile(
                name="external-generation",
                generation={
                    "mode": "external",
                    "endpoint": "http://127.0.0.1:9090/v1",
                    "model_id": "remote-local-qwen",
                },
            )
        )
        plan = manager.runtime_plan(applied)

        self.assertEqual(plan.generation.kind, "external")
        self.assertEqual(plan.generation.endpoint.base_url, "http://127.0.0.1:9090/v1/")
        self.assertNotIn(("generation", "external-generation"), self.launched)
        self.assertIn(("embeddings", "external-generation"), self.launched)
        self.assertEqual(self.probed, [("generation", "http://127.0.0.1:9090/v1/")])

    def test_public_or_redirected_external_endpoints_are_rejected_without_overwriting(self):
        from cc_workshop.inference_settings import EndpointProbeResult, InferenceSettingsError

        manager = self.manager()
        manager.apply_profile(self.profile())

        with self.assertRaises(InferenceSettingsError) as caught_public:
            manager.apply_profile(
                self.profile(
                    name="cloud-generation",
                    generation={"mode": "external", "endpoint": "https://api.openai.com/v1"},
                )
            )
        self.assertEqual(caught_public.exception.code, "INVALID_ENDPOINT")
        self.assertEqual(manager.store.active_profile().name, "balanced-local")

        def redirected(role, endpoint):
            return EndpointProbeResult(True, endpoint.base_url, redirect_target="http://127.0.0.1:9999/v1/")

        redirected_manager = self.manager(probe=redirected)
        redirected_manager.apply_profile(self.profile())
        with self.assertRaises(InferenceSettingsError) as caught_redirect:
            redirected_manager.apply_profile(
                self.profile(
                    name="redirected-generation",
                    generation={"mode": "external", "endpoint": "http://127.0.0.1:9090/v1"},
                )
            )
        self.assertEqual(caught_redirect.exception.code, "REDIRECT_FORBIDDEN")
        self.assertEqual(redirected_manager.store.active_profile().name, "balanced-local")

    def test_generation_activation_failure_rolls_back_to_previous_profile(self):
        from cc_workshop.inference_settings import InferenceSettingsError

        manager = self.manager()
        manager.apply_profile(self.profile())

        def failing_launcher(role, profile):
            if role == "generation":
                raise InferenceSettingsError("READINESS_TIMEOUT", "generation sidecar did not become ready", retryable=True)
            return OwnedHandle()

        failing = self.manager(launcher=failing_launcher)
        with self.assertRaises(InferenceSettingsError) as caught:
            failing.apply_profile(self.profile(name="bad-sidecar", hardware={"gpu_layers": 12}))

        self.assertEqual(caught.exception.code, "READINESS_TIMEOUT")
        self.assertEqual(failing.store.active_profile().name, "balanced-local")
        self.assertEqual(failing.store.active_profile().hardware.gpu_layers, 35)

    def test_external_generation_preserves_local_embedding_sidecar(self):
        manager = self.manager()
        profile = manager.apply_profile(
            self.profile(
                name="external-text-local-embeddings",
                generation={"mode": "external", "endpoint": "http://10.0.0.20:8080/v1"},
            )
        )
        plan = manager.runtime_plan(profile)

        self.assertEqual(plan.generation.kind, "external")
        self.assertEqual(plan.embeddings.kind, "sidecar")
        self.assertEqual(plan.embeddings.model_id, "embedding-gemma")
        self.assertIn(("embeddings", "external-text-local-embeddings"), self.launched)

    def test_missing_adapters_fail_closed(self):
        from cc_workshop.inference_settings import InferenceSettingsManager, ProfileStore, RuntimePolicy, InferenceSettingsError
        manager = InferenceSettingsManager(ProfileStore(self.root), RuntimePolicy("test"))
        with self.assertRaises(InferenceSettingsError): manager.apply_profile(self.profile())
        self.assertFalse(manager.store.path.exists())

    def test_transaction_disposes_staged_and_retires_old(self):
        from unittest.mock import patch
        handles = []
        def launch(role, profile):
            if profile.name == "fail-second" and role == "embeddings": raise RuntimeError("fixture")
            h = OwnedHandle(); handles.append(h); return h
        manager = self.manager(launcher=launch)
        manager.apply_profile(self.profile())
        with self.assertRaises(Exception): manager.apply_profile(self.profile(name="fail-second"))
        self.assertTrue(handles[2].closed)
        self.assertFalse(handles[0].closed)
        with patch.object(manager.store, "save_active", side_effect=OSError("fixture")):
            with self.assertRaises(Exception): manager.apply_profile(self.profile(name="fail-save"))
        self.assertTrue(all(h.closed for h in handles[2:]))
        manager.apply_profile(self.profile(name="external", generation={"mode":"external", "endpoint":"http://127.0.0.1:9090/v1"}))
        self.assertTrue(handles[0].closed)
        self.assertTrue(handles[1].closed)

    def test_nonfinite_and_nonboolean_rejected(self):
        from cc_workshop.inference_settings import InferenceSettingsError
        for value in (float("nan"), float("inf"), True, "oops"):
            with self.subTest(value=value), self.assertRaises(InferenceSettingsError):
                self.manager().apply_profile(self.profile(hardware={"split_mode":"tensor", "tensor_split":[value, 0.5]}))
        with self.assertRaises(InferenceSettingsError): self.manager().apply_profile(self.profile(hardware={"flash_attention":"false"}))

    def test_policy_roundtrip_and_atomic_failure(self):
        from unittest.mock import patch
        manager = self.manager(allow_quantized_tensor=True)
        manager.apply_profile(self.profile(hardware={"split_mode":"tensor", "tensor_split":[0.5,0.5], "kv_cache_precision":"q8_0"}))
        self.assertEqual(manager.store.active_profile().hardware.kv_cache_precision, "q8_0")
        before = manager.store.path.read_bytes()
        with patch("cc_workshop.inference_settings.os.replace", side_effect=OSError("fixture")):
            with self.assertRaises(Exception): manager.apply_profile(self.profile(name="replacement"))
        self.assertEqual(manager.store.path.read_bytes(), before)

    def test_legacy_profile_without_runtime_policy_migrates_to_current_policy(self):
        import json
        from cc_workshop.inference_settings import ProfileStore, RuntimePolicy

        store = ProfileStore(self.root)
        manager = self.manager()
        applied = manager.apply_profile(self.profile())
        raw = applied.to_dict()
        raw.pop("runtime_policy")
        store.path.write_text(json.dumps(raw, allow_nan=False), encoding="utf-8")

        migrated = store.active_profile(RuntimePolicy("llama.cpp-test"))

        self.assertEqual(migrated.name, "balanced-local")
        self.assertEqual(migrated.runtime_policy.runtime_version, "llama.cpp-test")
        saved = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertIn("runtime_policy", saved)


if __name__ == "__main__":
    unittest.main()
