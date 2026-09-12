import json
import tempfile
import unittest
from pathlib import Path


class FakeProcess:
    def __init__(self, pid=4101, exit_code=None, wait_raises=False):
        self.pid = pid
        self.exit_code = exit_code
        self.terminated = 0
        self.killed = 0
        self.wait_raises = wait_raises

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated += 1
        self.exit_code = 0

    def kill(self):
        self.killed += 1
        self.exit_code = -9

    def wait(self, timeout=None):
        if self.wait_raises:
            raise TimeoutError("still running")
        return self.exit_code if self.exit_code is not None else 0


class SidecarLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.exe = self.root / "runtime" / "llama-server.exe"
        self.model = self.root / "models" / "qwen.gguf"
        self.exe.parent.mkdir(parents=True)
        self.model.parent.mkdir(parents=True)
        self.exe.write_bytes(b"binary")
        self.model.write_bytes(b"model")
        import hashlib
        from cc_workshop.model_assets import ModelAssetStore, ModelManifest
        manifest = ModelManifest.from_dict(dict(model_id="local-qwen", revision="test", family="qwen", modality="text", license="fixture", runtime="llama.cpp", assets=[dict(filename="qwen.gguf", sha256=hashlib.sha256(b"model").hexdigest(), size_bytes=5, role="weights")]))
        self.installed = ModelAssetStore(self.root/"store").import_offline(manifest, self.model.parent)
        self.model = self.installed.verify()[0]
        self.commands = []
        self.processes = []
        self.port_status = None
        self.probe_result = None

    def tearDown(self):
        self.temp.cleanup()

    def manager(self, **overrides):
        from cc_workshop.llama_sidecar import (
            LlamaServerConfig,
            LlamaSidecarManager,
            PortStatus,
            ProbeResult,
            RuntimeSpec,
        )

        config_values = dict(
            runtime=RuntimeSpec(self.exe, self.exe.parent, "llama.cpp-test"),
            model_path=self.model,
            installed_model=self.installed,
            model_id="local-qwen",
            role="generation",
            host="127.0.0.1",
            port=18080,
            context_size=4096,
            gpu_layers=0,
        )
        config_values.update(overrides)
        config = LlamaServerConfig(**config_values)

        def factory(command, cwd, env):
            self.commands.append((tuple(command), cwd, dict(env)))
            proc = FakeProcess(pid=4101)
            self.processes.append(proc)
            return proc

        def port_probe(host, port):
            return self.port_status or PortStatus(False, None)

        def readiness_probe(base_url):
            return self.probe_result or ProbeResult(True, ("local-qwen",), "ready")

        return LlamaSidecarManager(
            config,
            state_path=self.root / "state" / "sidecars.json",
            process_factory=factory,
            port_probe=port_probe,
            readiness_probe=readiness_probe,
            sleep=lambda seconds: None,
        )

    def test_start_uses_bundled_llama_server_and_records_owned_child(self):
        manager = self.manager(extra_args=("--flash-attn", "on"))
        state = manager.start()

        command = self.commands[0][0]
        self.assertEqual(command[0], str(self.exe))
        self.assertIn("--model", command)
        self.assertIn(str(self.model), command)
        self.assertNotIn("python", " ".join(command).lower())
        self.assertNotIn("ollama", " ".join(command).lower())
        self.assertEqual(state.pid, 4101)
        self.assertEqual(state.base_url, "http://127.0.0.1:18080/v1")

        recorded = json.loads((self.root / "state" / "sidecars.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded["generation"]["pid"], 4101)
        self.assertEqual(recorded["generation"]["model_id"], "local-qwen")

    def test_port_owned_by_other_process_is_reported_without_killing_anything(self):
        from cc_workshop.llama_sidecar import PortStatus, SidecarError

        self.port_status = PortStatus(True, 9999)
        manager = self.manager()

        with self.assertRaises(SidecarError) as caught:
            manager.start()

        self.assertEqual(caught.exception.code, "PORT_IN_USE")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.processes, [])

    def test_child_crash_during_readiness_is_recoverable_and_clears_state(self):
        from cc_workshop.llama_sidecar import SidecarError

        def factory(command, cwd, env):
            proc = FakeProcess(pid=4102, exit_code=77)
            self.processes.append(proc)
            return proc

        manager = self.manager()
        manager.process_factory = factory

        with self.assertRaises(SidecarError) as caught:
            manager.start()

        self.assertEqual(caught.exception.code, "CHILD_EXITED")
        self.assertTrue(caught.exception.retryable)
        self.assertFalse((self.root / "state" / "sidecars.json").exists())

    def test_wrong_model_identity_stops_only_the_owned_child(self):
        from cc_workshop.llama_sidecar import ProbeResult, SidecarError

        self.probe_result = ProbeResult(True, ("other-model",), "wrong")
        manager = self.manager()

        with self.assertRaises(SidecarError) as caught:
            manager.start()

        self.assertEqual(caught.exception.code, "MODEL_IDENTITY_MISMATCH")
        self.assertEqual(self.processes[0].terminated, 1)
        self.assertFalse((self.root / "state" / "sidecars.json").exists())

    def test_repeated_start_reuses_owned_process_and_close_is_idempotent(self):
        manager = self.manager()
        first = manager.start()
        second = manager.start()

        self.assertEqual(first.pid, second.pid)
        self.assertEqual(len(self.processes), 1)

        manager.close()
        manager.close()

        self.assertEqual(self.processes[0].terminated, 1)
        self.assertFalse((self.root / "state" / "sidecars.json").exists())


    def test_leave_running_is_explicitly_unsupported(self):
        with self.assertRaises(ValueError): self.manager(shutdown_policy="leave_running")

    def test_post_spawn_failures_clean_owned_child(self):
        from unittest.mock import patch
        for target in ("_write_state", "readiness_probe"):
            manager = self.manager()
            with patch.object(manager, target, side_effect=RuntimeError("fixture")):
                with self.assertRaises(Exception): manager.start()
            self.assertEqual(self.processes[-1].terminated, 1)

    def test_protected_and_secret_arguments_rejected(self):
        for args in (("--host","0.0.0.0"), ("--api-key","fixture-secret"), ("--model","other")):
            with self.assertRaises(ValueError): self.manager(extra_args=args)

    def test_verbose_child_does_not_block_on_output(self):
        import sys, os
        from cc_workshop.llama_sidecar import _default_process_factory
        child = _default_process_factory((sys.executable, "-c", "import sys; sys.stdout.write('x'*2000000); sys.stderr.write('y'*2000000)"), self.root, os.environ)
        try: self.assertEqual(child.wait(timeout=10), 0)
        finally:
            if child.poll() is None: child.kill(); child.wait()

    def test_activation_rejects_corrupted_weights_and_missing_manifest(self):
        from cc_workshop.llama_sidecar import SidecarError
        self.model.write_bytes(b"wrong")
        with self.assertRaises(SidecarError): self.manager().start()
        self.assertEqual(self.processes, [])

    def test_registry_failure_preserves_unrelated_record(self):
        from cc_workshop.llama_sidecar import SidecarError
        manager = self.manager()
        manager.state_path.parent.mkdir()
        manager.state_path.write_text("{corrupt")
        with self.assertRaises(SidecarError): manager.start()
        self.assertEqual(self.processes[0].terminated, 1)
        self.assertEqual(manager.state_path.read_text(), "{corrupt")

    def test_close_does_not_remove_other_owner_record(self):
        manager = self.manager(); manager.start()
        data = json.loads(manager.state_path.read_text())
        data["generation"]["token"] = "another-owner"
        manager.state_path.write_text(json.dumps(data))
        manager.close()
        self.assertEqual(json.loads(manager.state_path.read_text())["generation"]["token"], "another-owner")


if __name__ == "__main__":
    unittest.main()
