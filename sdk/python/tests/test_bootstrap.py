import os
import re
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import httpx

from edgespeak import EdgeSpeak, MIN_CLI_VERSION, RuntimeStartError
from edgespeak import _bootstrap as boot


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        home = patch.object(boot.Path, "home", return_value=Path(self.home.name))
        home.start()
        self.addCleanup(home.stop)

    # Fixed comparison fixtures are independent of the current release floor.
    @patch.object(boot, "MIN_CLI_VERSION", "0.6.4")
    def test_version_floor_and_protocol_both_required(self):
        cases = [(b"0.6.3", b"--sdk edgespeak-sdk-v2", False), (b"0.6.2", b"--sdk edgespeak-sdk-v2", False), (b"0.6.4", b"[--sdk] edgespeak-sdk-v2 owned", True),
                 (b"0.6.4", b"--sdk edgespeak-sdk-v20", False),
                 (b"0.6.4", b"--sdk edgespeak-sdk-v2-preview", False),
                 (b"0.6.4", b"--host", False), (b"0.6.30", b"--sdk edgespeak-sdk-v2\n", True),
                 (b"0.6.4-preview", b"--sdk edgespeak-sdk-v2", False), (b"broken", b"--sdk edgespeak-sdk-v2", False)]
        for version, help_text, expected in cases:
            with self.subTest(version=version, help_text=help_text), patch.object(boot.subprocess, "run", side_effect=[
                subprocess.CompletedProcess([], 0, b"edgespeak-cli " + version),
                subprocess.CompletedProcess([], 0, help_text),
            ]):
                self.assertEqual(boot._compatible(Path("cli")), expected)


    def test_probe_timeout_is_not_compatible(self):
        with patch.object(boot.subprocess, "run", side_effect=subprocess.TimeoutExpired("cli", 10)):
            self.assertFalse(boot._compatible(Path("cli")))

    def test_new_sdk_floor_triggers_latest_install_only_for_older_cli(self):
        # Simulate a later SDK release without changing this release's floor.
        # Discovery/version comparison are real; only OS execution and the
        # network installer are replaced. Existing protocol support alone is
        # insufficient once the SDK's minimum CLI version increases.
        installed = Path("installed-cli")
        latest = Path("latest-stable-cli")
        for version, needs_install in [("0.6.9", True), ("0.7.0", False), ("0.8.0", False)]:
            def run(args, **kwargs):
                output = f"edgespeak-cli {version}" if args[1] == "--version" else "[--sdk] edgespeak-sdk-v2 owned service"
                return subprocess.CompletedProcess(args, 0, output.encode())
            with self.subTest(version=version), patch.object(boot, "MIN_CLI_VERSION", "0.7.0"), \
                    patch.object(boot, "_candidates", return_value=[installed]), \
                    patch.object(boot.subprocess, "run", side_effect=run), \
                    patch.object(boot, "_install", return_value=latest) as install:
                self.assertEqual(boot.ensure_cli(), latest if needs_install else installed)
                if needs_install:
                    install.assert_called_once_with()
                else:
                    install.assert_not_called()

    def test_current_floor_upgrades_older_but_reuses_equal_and_newer(self):
        installed = Path("installed-cli")
        latest = Path("latest-stable-cli")
        major, minor, patch_version = map(int, MIN_CLI_VERSION.split("."))
        older = f"{major}.{minor}.{patch_version - 1}"
        newer = f"{major}.{minor}.{patch_version + 1}"
        for version, needs_install in [(older, True), (MIN_CLI_VERSION, False), (newer, False)]:
            def run(args, **kwargs):
                output = f"edgespeak-cli {version}" if args[1] == "--version" else "[--sdk] edgespeak-sdk-v2"
                return subprocess.CompletedProcess(args, 0, output.encode())
            with self.subTest(version=version), patch.object(boot, "_candidates", return_value=[installed]), \
                    patch.object(boot.subprocess, "run", side_effect=run), \
                    patch.object(boot, "_installation_lock"), \
                    patch.object(boot, "_install", return_value=latest) as install:
                self.assertEqual(boot.ensure_cli(), latest if needs_install else installed)
                self.assertEqual(install.call_count, int(needs_install))

    def test_compatible_installation_never_uses_network_or_lock(self):
        with patch.object(boot, "_find", return_value=Path("cli")), \
                patch.object(boot, "_install") as install, patch.object(boot, "_installation_lock") as lock:
            self.assertEqual(boot.ensure_cli(), Path("cli"))
            install.assert_not_called()
            lock.assert_not_called()

    def test_install_and_recheck_and_other_process_completion(self):
        for results, calls in [([None, None], 1), ([None, Path("other-cli")], 0)]:
            with self.subTest(results=results), patch.object(boot, "_find", side_effect=results), \
                    patch.object(boot, "_installation_lock"), patch.object(boot, "_install", return_value=Path("new-cli")) as install:
                self.assertEqual(boot.ensure_cli(), Path("new-cli") if calls else results[-1])
                self.assertEqual(install.call_count, calls)

    def test_official_release_still_incompatible_stops_after_one_attempt(self):
        with patch.object(boot, "_find", return_value=None), patch.object(boot, "_installation_lock"), \
                patch.object(boot, "_install", side_effect=RuntimeStartError(f"CLI >= {MIN_CLI_VERSION}")) as install:
            with self.assertRaisesRegex(RuntimeStartError, re.escape(f"CLI >= {MIN_CLI_VERSION}")):
                boot.ensure_cli()
            install.assert_called_once()

    def test_no_public_path_override_and_attached_mode_does_not_bootstrap(self):
        with self.assertRaises(TypeError):
            EdgeSpeak(cli_path="custom")
        with patch.object(boot, "ensure_cli") as resolve:
            with EdgeSpeak(base_url="http://127.0.0.1:1118/v1"):
                pass
            resolve.assert_not_called()

    def test_rosetta_installer_credentials_stripped_and_account_data_isolated(self):
        response = httpx.Response(200, content=b"# EDGESPEAK_SDK_INSTALL_V1 fixture", request=httpx.Request("GET", "https://edgespeak.com/install.sh"))
        process = MagicMock()
        process.__enter__.return_value = process
        process.wait.return_value = 0
        with patch.dict(os.environ, {"EDGESPEAK_ACCESS_TOKEN": "secret", "EDGESPEAK_DOWNLOAD_BASE": "untrusted"}), \
                patch.object(boot.platform, "system", return_value="Darwin"), \
                patch.object(boot.platform, "machine", return_value="x86_64"), \
                patch.object(boot.shutil, "which", return_value="/bin/sh"), \
                patch.object(boot.httpx.Client, "get", return_value=response), \
                patch.object(boot.subprocess, "Popen", return_value=process) as spawn, \
                patch.object(boot, "_compatible", return_value=True):
            boot._install()
            env = spawn.call_args.kwargs["env"]
            self.assertNotIn("EDGESPEAK_ACCESS_TOKEN", env)
            self.assertNotIn("EDGESPEAK_DOWNLOAD_BASE", env)
            self.assertIn("runtime-", env["EDGESPEAK_DATA_DIR"])
            self.assertEqual(env["EDGESPEAK_INSTALL_CONTEXT"], "sdk")
            self.assertTrue((Path(self.home.name) / ".edgespeak/sdk/current.json").is_file())
            self.assertNotIn("secret", repr(spawn.call_args.args))

    def test_windows_file_installer_preserves_unicode_with_one_bom(self):
        source = '# EDGESPEAK_SDK_INSTALL_V1\nWrite-Output "安装完成"\n'
        for payload in (source.encode("utf-8"), source.encode("utf-8-sig")):
            response = httpx.Response(200, content=payload, request=httpx.Request("GET", "https://edgespeak.com/install.ps1"))
            process = MagicMock()
            process.wait.return_value = 0
            with self.subTest(bom=payload.startswith(b"\xef\xbb\xbf")), \
                    patch.object(boot.platform, "system", return_value="Windows"), \
                    patch.object(boot.platform, "machine", return_value="amd64"), \
                    patch.object(boot.shutil, "which", return_value="powershell.exe"), \
                    patch.object(boot.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
                    patch.object(boot.subprocess, "CREATE_NO_WINDOW", 134217728, create=True), \
                    patch.object(boot.httpx.Client, "get", return_value=response), \
                    patch.object(boot.subprocess, "Popen", return_value=process) as spawn, \
                    patch.object(boot, "_compatible", return_value=True):
                boot._install()
                command = spawn.call_args.args[0]
                self.assertEqual(command[-2], "-File")
                saved = Path(command[-1]).read_bytes()
                self.assertEqual(saved, source.encode("utf-8-sig"))
                self.assertEqual(saved.decode("utf-8-sig"), source)

    def test_download_failure_is_sanitized(self):
        with patch.object(boot.platform, "system", return_value="Linux"), \
                patch.object(boot.platform, "machine", return_value="x86_64"), \
                patch.object(boot.shutil, "which", return_value="/bin/sh"), \
                patch.object(boot.httpx.Client, "get", side_effect=httpx.ConnectError("secret")), \
                patch.object(boot.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeStartError, "Check your network") as error:
                boot._install()
            self.assertNotIn("secret", str(error.exception))
            spawn.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Cross-process flock regression; Windows requires platform acceptance")
    def test_install_lock_excludes_another_process_and_recovers_after_kill(self):
        with patch.dict(os.environ, {"HOME": self.home.name}):
            program = 'from edgespeak._bootstrap import _installation_lock\nimport os, time\nwith _installation_lock():\n if os.fork() == 0:\n  time.sleep(30)\n  os._exit(0)\n print("locked", flush=True)\n time.sleep(30)\n'
            owner = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True, start_new_session=True)
            try:
                self.assertEqual(owner.stdout.readline().strip(), "locked")
                with patch.object(boot.time, "monotonic", side_effect=[0, 1801]):
                    with self.assertRaisesRegex(RuntimeStartError, "waiting"):
                        with boot._installation_lock():
                            self.fail("Second process acquired the held lock")
                owner.kill()
                owner.wait(timeout=3)
                with boot._installation_lock():
                    pass
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=3)
                try:
                    os.killpg(owner.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                owner.stdout.close()

    def test_old_installer_never_executes(self):
        response = httpx.Response(200, content=b"old", request=httpx.Request("GET", "https://edgespeak.com/install.sh"))
        with patch.object(boot.httpx.Client, "get", return_value=response), patch.object(boot.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(RuntimeStartError, "matching installer"):
                boot._install()
            spawn.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX installer subprocess fixture")
    def test_failed_install_preserves_pointer_and_retry_uses_new_directory(self):
        root = Path(self.home.name) / ".edgespeak/sdk"
        root.mkdir(parents=True)
        pointer = root / "current.json"
        previous = '{"generation":"runtime-previous"}'
        pointer.write_text(previous)
        script = b'# EDGESPEAK_SDK_INSTALL_V1\nmkdir -p "$EDGESPEAK_RUNTIME_DIR.install-lock"\nexit 1\n'
        response = httpx.Response(200, content=script, request=httpx.Request("GET", "https://edgespeak.com/install.sh"))
        with patch.object(boot.httpx.Client, "get", return_value=response):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeStartError, "installation failed"):
                    boot._install()
                self.assertEqual(pointer.read_text(), previous)
        self.assertEqual(len(list(root.glob('runtime-*/runtime.install-lock'))), 2)

    def test_new_runtime_must_pass_before_publishing(self):
        response = httpx.Response(200, content=b"# EDGESPEAK_SDK_INSTALL_V1", request=httpx.Request("GET", "https://edgespeak.com/install.sh"))
        process = MagicMock()
        process.wait.return_value = 0
        with patch.object(boot.httpx.Client, "get", return_value=response), \
                patch.object(boot.subprocess, "Popen", return_value=process), \
                patch.object(boot, "_compatible", return_value=False):
            with self.assertRaisesRegex(RuntimeStartError, re.escape(f"CLI >= {MIN_CLI_VERSION}")):
                boot._install()
        self.assertFalse((Path(self.home.name) / ".edgespeak/sdk/current.json").exists())

    def test_kill_failure_does_not_wait_indefinitely(self):
        response = httpx.Response(200, content=b"# EDGESPEAK_SDK_INSTALL_V1", request=httpx.Request("GET", "https://edgespeak.com/install.ps1"))
        process = MagicMock()
        process.wait.side_effect = subprocess.TimeoutExpired("installer", 1200)
        process.poll.return_value = None
        with patch.object(boot.platform, "system", return_value="Windows"), \
                patch.object(boot.platform, "machine", return_value="amd64"), \
                patch.object(boot.shutil, "which", return_value="powershell.exe"), \
                patch.object(boot.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
                patch.object(boot.subprocess, "CREATE_NO_WINDOW", 134217728, create=True), \
                patch.object(boot.httpx.Client, "get", return_value=response), \
                patch.object(boot.subprocess, "Popen", return_value=process), \
                patch.object(boot.subprocess, "run", side_effect=subprocess.TimeoutExpired("taskkill", 15)):
            with self.assertRaises(subprocess.TimeoutExpired):
                boot._install()
        self.assertEqual([call.kwargs["timeout"] for call in process.wait.call_args_list], [1200, 5])
        process.kill.assert_called_once()
