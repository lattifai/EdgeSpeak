import io
import struct
import unittest
import wave

import httpx

from edgespeak import EdgeSpeakError
from edgespeak._audio import validate_options, validate_response
import test_client


def wav_bytes(rate=24000):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as audio:
        audio.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0\0\0\0' * 100)
    return stream.getvalue()


class AudioDeliveryTests(unittest.TestCase):
    setUp = test_client.ClientTests.setUp
    attached = test_client.ClientTests.attached

    def test_options_are_sent_with_explicit_units(self):
        client = self.attached(httpx.Response(200, content=b'ID3' + b'\0' * 30, headers={'content-type': 'audio/mpeg'}))
        result = client.upsample(self.audio, response_format='mp3', bitrate=192000)
        self.assertTrue(result.startswith(b'ID3'))
        body = self.requests[-1].content
        self.assertIn(b'name="response_format"\r\n\r\nmp3', body)
        self.assertIn(b'name="bitrate"\r\n\r\n192000', body)
        self.assertNotIn(b'name="pcm_format"', body)

    def test_invalid_combinations_fail_before_upload(self):
        client = self.attached()
        for options in ({'bitrate': 192000}, {'response_format': 'flac', 'pcm_format': 'f32'},
                        {'response_format': 'opus', 'sample_rate': 24000},
                        {'response_format': 'mp3', 'sample_rate': 12345},
                        {'response_format': 'mp3', 'pcm_format': 's16'},
                        {'response_format': 'mp3', 'bitrate': True},
                        {'response_format': 'mp3', 'bitrate': '192k'},
                        {'response_format': 'mp3', 'bitrate': 192000.0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                client.upsample(self.audio, **options)
        self.assertFalse(self.requests)

    def test_wav_is_checked_for_rate_encoding_structure_and_payload(self):
        valid = wav_bytes()
        validate_response(valid, 'Audio/WAV; codec=pcm', 'wav', 24000, 's16')
        damaged = [valid[:-1], valid[:36], valid[:24] + struct.pack('<I', 48000) + valid[28:],
                   valid[:32] + struct.pack('<H', 2) + valid[34:]]
        for data in damaged:
            with self.subTest(length=len(data)), self.assertRaises(EdgeSpeakError):
                validate_response(data, 'audio/wav', 'wav', 24000, None)
        with self.assertRaises(EdgeSpeakError):
            validate_response(valid, 'audio/wav', 'wav', 24000, 'f32')

    def test_mime_and_container_must_both_match_requested_format(self):
        for format, mime, data in [('flac', 'audio/flac', b'fLaC' + b'\0' * 40),
                                   ('mp3', 'audio/mpeg', b'ID3' + b'\0' * 30),
                                   ('m4a', 'audio/mp4', b'\0\0\0\x20ftyp' + b'\0' * 24),
                                   ('aac', 'audio/aac', b'\xff\xf1' + b'\0' * 12),
                                   ('ogg', 'audio/ogg', b'OggS' + b'\0' * 24 + b'\x01vorbis'),
                                   ('opus', 'audio/ogg; codecs=opus', b'OggS' + b'\0' * 24 + b'OpusHead')]:
            with self.subTest(format=format):
                validate_response(data, mime, format, 48000, None)
                with self.assertRaises(EdgeSpeakError):
                    validate_response(b'<html>error</html>', mime, format, 48000, None)
                with self.assertRaises(EdgeSpeakError):
                    validate_response(data, 'application/json', format, 48000, None)


if __name__ == '__main__':
    unittest.main()
