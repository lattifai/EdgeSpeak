"""Check the installed artifact, public API and real client headers agree."""
from importlib.metadata import version
import unittest

from edgespeak import EdgeSpeak, MIN_CLI_VERSION, __version__
from edgespeak import _bootstrap as boot


class VersionTests(unittest.TestCase):
    def test_distribution_public_version_and_user_agent_agree(self):
        self.assertEqual(version("edgespeak"), __version__)
        with EdgeSpeak(base_url="http://127.0.0.1:1118/v1") as client:
            self.assertEqual(client._http.headers["User-Agent"], f"edgespeak-python/{__version__}")

    def test_actual_cli_floor_is_accepted(self):
        self.assertEqual(MIN_CLI_VERSION, boot.MIN_CLI_VERSION)
        self.assertTrue(boot.compatible_version(MIN_CLI_VERSION))
