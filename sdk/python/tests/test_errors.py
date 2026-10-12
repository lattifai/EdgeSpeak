import json
import unittest
from edgespeak._errors import API_KEYS_URL, payload_error
from edgespeak import EdgeSpeak


class ErrorTests(unittest.TestCase):
    def test_key_failures_are_distinct_and_do_not_echo_server_text(self):
        for code, guidance in [('api_key_expired', 'expired'), ('api_key_revoked', 'revoked')]:
            error = payload_error({'error': {'code': code, 'message': 'secret'}}, 401)
            self.assertEqual(error.code, code)
            self.assertEqual(error.reason, code)
            self.assertIn(guidance, str(error))
            self.assertIn(API_KEYS_URL, str(error))
            self.assertNotIn('secret', str(error))

    def test_invalid_key_points_to_creation_page_without_echoing_key(self):
        for kwargs in ({"api_key": "private-invalid-key"},):
            with self.assertRaises(ValueError) as error:
                EdgeSpeak(**kwargs)
            self.assertIn(API_KEYS_URL, str(error.exception))
            self.assertIn("EDGESPEAK_API_KEY", str(error.exception))
            self.assertNotIn("private-invalid-key", str(error.exception))
        self.assertIn(API_KEYS_URL, EdgeSpeak.__doc__)

    def test_quota_reason_and_reset_preserve_gateway_code(self):
        message = json.dumps({'code': 'errors.usage.exhausted', 'params': {'resetsAt': '2026-11-01T00:00:00Z'}})
        error = payload_error({'error': {'code': 'license_required', 'message': message + ': private detail'}}, 403)
        self.assertEqual(error.code, 'license_required')
        self.assertEqual(error.reason, 'usage_exhausted')
        self.assertEqual(error.resets_at, '2026-11-01T00:00:00+00:00')
        self.assertIn('billing period', str(error))
        self.assertNotIn('private', str(error))
        direct = payload_error({'error': {'code': 'usage_exhausted', 'resets_at': '2026-11-01T00:00:00Z'}}, 402)
        self.assertEqual(direct.reason, error.reason)
        self.assertEqual(direct.resets_at, error.resets_at)

    def test_unrecognized_or_invalid_reset_is_not_exposed(self):
        for message in ['secret', '{"code":"something","params":{"resetsAt":"secret"}}', '{"code":"errors.usage.exhausted","params":{"resetsAt":"secret"}}']:
            error = payload_error({'error': {'code': 'license_required', 'message': message}}, 403)
            self.assertIsNone(error.resets_at)
            self.assertNotIn('secret', str(error))
