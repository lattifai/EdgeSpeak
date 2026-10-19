"""Real CLI lifecycle tests; missing runtime prerequisites are errors."""
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

from runtime_cli import resolve_cli


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


class RealCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = resolve_cli()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        from unittest.mock import patch
        self.env = patch.dict(os.environ, {"EDGESPEAK_DATA_DIR": self.directory.name})
        resolver = patch("edgespeak._bootstrap.ensure_cli", return_value=self.cli)
        resolver.start()
        self.addCleanup(resolver.stop)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_real_cli_rejects_invalid_total_concurrency(self):
        help_result=subprocess.run([self.cli,'serve','--help'],capture_output=True,timeout=10)
        self.assertEqual(help_result.returncode,0)
        self.assertIn(b'--max-concurrency',help_result.stdout+help_result.stderr)
        for value in ('0','-1','65','true','1.5'):
            result=subprocess.run([self.cli,'serve','--max-concurrency',value],capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn(b'--max-concurrency',result.stdout+result.stderr)

    def test_account_key_denials_survive_cli_and_http_to_sdk(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from unittest.mock import patch
        from edgespeak import EdgeSpeakError
        for code in ('api_key_expired', 'api_key_revoked'):
            with self.subTest(code=code):
                class Handler(BaseHTTPRequestHandler):
                    def do_POST(self):
                        self.rfile.read(int(self.headers.get('Content-Length', 0)))
                        body = json.dumps({'error': {'code': code, 'message': 'private server detail'}}).encode()
                        self.send_response(401)
                        self.send_header('Content-Type', 'application/json')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    def log_message(self, *_):
                        pass
                server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with patch.dict(os.environ, {'EDGESPEAK_LICENSE_BASE_URL': f'http://127.0.0.1:{server.server_port}'}), EdgeSpeak(api_key='esak_' + 'a' * 43) as client:
                        with self.assertRaises(EdgeSpeakError) as error:
                            client.segment('Hello world.')
                        self.assertEqual(error.exception.code, code)
                        self.assertEqual(error.exception.reason, code)
                        self.assertEqual(error.exception.status_code, 401)
                        self.assertNotIn('private', str(error.exception))
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_owned_compute_devices_reach_real_cli_and_close(self):
        from unittest.mock import patch
        devices = ["cpu"] + (["metal"] if sys.platform == "darwin" else [])
        for device in devices:
            with self.subTest(device=device), patch.dict(os.environ, {"EDGESPEAK_ALIGNMENT_BACKEND": "invalid-inherited-backend"}):
                with EdgeSpeak(device=device) as client:
                    url = str(client._http.base_url)
                    self.assertEqual(client._http.get("health").status_code, 200)
                wait_closed(url)

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
    try:
        print('ready', flush=True)
        time.sleep(60)
    except KeyboardInterrupt:
        print(client._request('GET', 'health')['status'], flush=True)
"""
        parent = subprocess.Popen([sys.executable, "-c", program, self.cli], stdout=subprocess.PIPE,
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

    def test_killed_python_parent_closes_service(self):
        program = '''import sys, time
from edgespeak import EdgeSpeak
from unittest.mock import patch
with patch("edgespeak._bootstrap.ensure_cli", return_value=sys.argv[1]):
    client = EdgeSpeak()
print(str(client._http.base_url), flush=True)
time.sleep(60)
'''
        parent = subprocess.Popen([sys.executable, "-c", program, self.cli], stdout=subprocess.PIPE, text=True)
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
