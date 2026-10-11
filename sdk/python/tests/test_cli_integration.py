"""Opt-in real CLI tests; no model download or inference required."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from edgespeak import EdgeSpeak

CLI = os.environ.get("EDGESPEAK_TEST_CLI")


def wait_closed(url, timeout=15):
    from urllib.parse import urlsplit
    address = urlsplit(url)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((address.hostname, address.port), timeout=.2):
                pass
        except OSError:
            return
        time.sleep(.1)
    raise AssertionError("SDK service port remained open")


@unittest.skipUnless(CLI, "set EDGESPEAK_TEST_CLI to a freshly built CLI")
class RealCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        from unittest.mock import patch
        self.env = patch.dict(os.environ, {"EDGESPEAK_DATA_DIR": self.directory.name})
        resolver = patch("edgespeak._bootstrap.ensure_cli", return_value=CLI)
        resolver.start()
        self.addCleanup(resolver.stop)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_ready_health_auth_and_independent_lifetimes(self):
        with EdgeSpeak() as first, EdgeSpeak() as second:
            a, b = str(first._http.base_url), str(second._http.base_url)
            self.assertNotEqual(a, b)
            self.assertEqual(first._request("GET", "health")["status"], "ok")
            with httpx.Client(trust_env=False) as outsider:
                self.assertEqual(outsider.get(a + "models").status_code, 401)
            with EdgeSpeak(base_url=a, gateway_key=first._http.headers["authorization"][7:]) as attached:
                self.assertEqual(attached._request("GET", "health")["status"], "ok")
            self.assertEqual(first._request("GET", "health")["status"], "ok")
            first.close()
            wait_closed(a)
            self.assertEqual(second._request("GET", "health")["status"], "ok")
        wait_closed(b)

    @unittest.skipIf(os.name == "nt", "POSIX process-group interrupt test")
    def test_keyboard_interrupt_does_not_kill_service(self):
        program = """import sys, time
from edgespeak import EdgeSpeak
from unittest.mock import patch
with patch("edgespeak._bootstrap.ensure_cli", return_value=sys.argv[1]), EdgeSpeak() as client:
    print('ready', flush=True)
    try:
        time.sleep(60)
    except KeyboardInterrupt:
        print(client._request('GET', 'health')['status'], flush=True)
"""
        parent = subprocess.Popen([sys.executable, "-c", program, CLI], stdout=subprocess.PIPE,
                                  text=True, start_new_session=True)
        try:
            self.assertEqual(parent.stdout.readline().strip(), "ready")
            os.killpg(parent.pid, signal.SIGINT)
            output, _ = parent.communicate(timeout=20)
            self.assertEqual(parent.returncode, 0)
            self.assertIn("ok", output)
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            parent.stdout.close()

    @unittest.skipIf(os.name == "nt", "Windows hard termination uses a separate platform smoke")
    def test_killed_python_parent_closes_service(self):
        program = '''import sys, time
from edgespeak import EdgeSpeak
from unittest.mock import patch
with patch("edgespeak._bootstrap.ensure_cli", return_value=sys.argv[1]):
    client = EdgeSpeak()
print(str(client._http.base_url), flush=True)
time.sleep(60)
'''
        parent = subprocess.Popen([sys.executable, "-c", program, CLI], stdout=subprocess.PIPE, text=True)
        try:
            address = parent.stdout.readline().strip()
            self.assertTrue(address.startswith("http://127.0.0.1:"))
            parent.kill()
            parent.wait(timeout=3)
            wait_closed(address)
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            parent.stdout.close()
