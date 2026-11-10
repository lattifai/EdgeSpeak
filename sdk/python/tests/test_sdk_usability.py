"""Regressions for SDK usability defects found while running public benchmarks."""
import os
import unittest
from unittest.mock import patch

from edgespeak import AsyncEdgeSpeak, EdgeSpeak
from edgespeak import _process


ACCOUNT_KEY = "esak_" + "k" * 43
OWNED = (None, None, "http://127.0.0.1:1118/v1", "gateway-token")


class AccountKeyEnvironmentTests(unittest.TestCase):
    """EDGESPEAK_API_KEY is also the CLI gateway token; that must not crash EdgeSpeak()."""

    def test_gateway_token_in_environment_is_ignored_with_warning(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "my-gateway-secret"}), \
                patch("edgespeak._client.start_process", return_value=OWNED) as start:
            with self.assertLogs("edgespeak", "WARNING") as logs:
                with EdgeSpeak():
                    pass
            start.assert_called_once_with(30, None, None)
        self.assertIn("EDGESPEAK_API_KEY", logs.output[0])
        self.assertNotIn("my-gateway-secret", "\n".join(logs.output))

    def test_empty_environment_value_is_ignored_silently(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": ""}), \
                patch("edgespeak._client.start_process", return_value=OWNED) as start, \
                patch("edgespeak._errors._LOG.warning") as warning:
            with EdgeSpeak():
                pass
            start.assert_called_once_with(30, None, None)
            warning.assert_not_called()

    def test_malformed_account_key_in_environment_names_the_variable(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "esak_short"}), \
                patch("edgespeak._client.start_process") as start:
            with self.assertRaisesRegex(ValueError, "EDGESPEAK_API_KEY environment variable") as error:
                EdgeSpeak()
            start.assert_not_called()
        self.assertNotIn("api_key parameter", str(error.exception))
        self.assertNotIn("esak_short", str(error.exception))

    def test_invalid_parameter_names_the_parameter(self):
        with patch.dict(os.environ, {}, clear=False), patch("edgespeak._client.start_process") as start:
            os.environ.pop("EDGESPEAK_API_KEY", None)
            with self.assertRaisesRegex(ValueError, "api_key parameter"):
                EdgeSpeak(api_key="gateway-token")
            start.assert_not_called()

    def test_valid_environment_account_key_is_still_used(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": ACCOUNT_KEY}), \
                patch("edgespeak._client.start_process", return_value=OWNED) as start:
            with EdgeSpeak():
                pass
            start.assert_called_once_with(30, ACCOUNT_KEY, None)

    def test_inherited_cli_account_variable_error_names_that_variable(self):
        with patch.dict(os.environ, {"EDGESPEAK_ACCESS_TOKEN": "not-an-account-key"}), \
                patch("edgespeak._bootstrap.ensure_cli") as ensure:
            with self.assertRaisesRegex(ValueError, "EDGESPEAK_ACCESS_TOKEN") as error:
                _process.start_process(30)
            ensure.assert_not_called()
        self.assertNotIn("set EDGESPEAK_API_KEY", str(error.exception))


class AsyncAccountKeyEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_token_in_environment_is_ignored_with_warning(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "my-gateway-secret"}):
            with self.assertLogs("edgespeak", "WARNING") as logs:
                client = AsyncEdgeSpeak()
        self.assertIsNone(client._api_key)
        self.assertNotIn("my-gateway-secret", "\n".join(logs.output))
        await client.aclose()

    async def test_malformed_account_key_in_environment_names_the_variable(self):
        with patch.dict(os.environ, {"EDGESPEAK_API_KEY": "esak_short"}):
            with self.assertRaisesRegex(ValueError, "EDGESPEAK_API_KEY environment variable"):
                AsyncEdgeSpeak()


if __name__ == "__main__":
    unittest.main()
