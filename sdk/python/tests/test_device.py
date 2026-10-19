"""Owned-runtime device selection and attached-gateway rejection."""
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from edgespeak import EdgeSpeak, MIN_CLI_VERSION, RuntimeStartError
from edgespeak._device import normalize_device


class DeviceTests(unittest.TestCase):
    def test_supported_devices_and_normalization(self):
        for system in ("Linux", "Windows", "Darwin"):
            with patch("edgespeak._device.platform.system", return_value=system):
                for value, expected in ((None, None), ("auto", "auto"), ("CPU", "cpu")):
                    self.assertEqual(normalize_device(value), expected)
                if system == "Darwin":
                    for value in ("metal", "Metal", "mps", "MPS"):
                        self.assertEqual(normalize_device(value), "metal")
                else:
                    for value, expected in (("CUDA", "cuda"), ("cuda:0", "cuda:0"), ("CUDA:01", "cuda:1"), ("cuda:4294967295", "cuda:4294967295")):
                        self.assertEqual(normalize_device(value), expected)

    def test_invalid_devices_fail_before_any_install_spawn_or_http(self):
        with patch("edgespeak._bootstrap.ensure_cli") as install, patch("edgespeak._process.subprocess.Popen") as spawn, patch("edgespeak._client.httpx.Client") as http:
            for value in ("", " ", "cpu ", "cuda:-1", "cuda:+1", "cuda:1.0", "cuda:1;echo", "cuda:١", "cuda:", "cuda:4294967296", "cuda:" + "9" * 100, "vulkan", "gpu", True, 0, [], {}):
                with self.subTest(device=value), self.assertRaisesRegex(ValueError, "device"):
                    EdgeSpeak(device=value)
            install.assert_not_called()
            spawn.assert_not_called()
            http.assert_not_called()

    def test_platform_mismatches_fail_before_start(self):
        with patch("edgespeak._client.start_process") as start:
            for system, values, message in (("Darwin", ("cuda", "cuda:1"), "CUDA is unavailable on macOS"), ("Linux", ("metal", "mps"), "only available on macOS"), ("Windows", ("metal", "mps"), "only available on macOS")):
                with patch("edgespeak._device.platform.system", return_value=system):
                    for value in values:
                        with self.subTest(system=system, device=value), self.assertRaisesRegex(ValueError, message):
                            EdgeSpeak(device=value)
            start.assert_not_called()

    def test_any_explicit_device_rejected_for_local_or_remote_gateway(self):
        with patch("edgespeak._bootstrap.ensure_cli") as install, patch("edgespeak._client.start_process") as start, patch("edgespeak._client.httpx.Client") as http:
            for url in ("http://127.0.0.1:1118/v1", "https://gateway.example/v1"):
                for device in ("auto", "cpu", "cuda:0", "metal", "invalid"):
                    with self.subTest(url=url, device=device), self.assertRaisesRegex(ValueError, "existing gateway controls"):
                        EdgeSpeak(base_url=url, device=device)
            install.assert_not_called()
            start.assert_not_called()
            http.assert_not_called()

    def test_cli_argv_is_explicit_and_parent_environment_is_unchanged(self):
        for system, device, expected in (("Linux", "CUDA:01", "cuda:1"), ("Windows", "cuda:2", "cuda:2"), ("Darwin", "MPS", "metal"), ("Linux", "CPU", "cpu"), ("Linux", "auto", "auto"), ("Linux", None, None)):
            process = MagicMock()
            process.poll.return_value = None
            process.wait.return_value = 0
            process.stdout = io.BytesIO((json.dumps({"version": MIN_CLI_VERSION, "protocol": "edgespeak-sdk-v2", "event": "ready", "base_url": "http://127.0.0.1:43210/v1"}) + "\n").encode())
            with self.subTest(system=system, device=device), patch("edgespeak._device.platform.system", return_value=system), patch("edgespeak._bootstrap.ensure_cli", return_value=Path("candidate-cli")), patch("edgespeak._process.subprocess.Popen", return_value=process) as spawn:
                before = dict(os.environ)
                with EdgeSpeak(device=device):
                    pass
                self.assertEqual(dict(os.environ), before)
                command = spawn.call_args.args[0]
                self.assertEqual(command[1:], ["serve", "--sdk"] + ([] if expected is None else ["--device", expected]))
                self.assertFalse(spawn.call_args.kwargs["shell"])
                process.stdin.close.assert_called_once()
                process.wait.assert_called_once()

    def test_cli_start_failure_reports_selected_device_and_cleans_up(self):
        process = MagicMock()
        process.stdout = io.BytesIO()
        process.poll.return_value = 1
        process.returncode = 1
        with patch("edgespeak._bootstrap.ensure_cli", return_value=Path("candidate-cli")), patch("edgespeak._process.subprocess.Popen", return_value=process), self.assertRaisesRegex(RuntimeStartError, "device.*cpu"):
            EdgeSpeak(device="cpu")
        process.stdin.close.assert_called_once()
