"""Compare path, bytes and multichannel ndarray through a real gateway/decoder."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np

from edgespeak import EdgeSpeak
from runtime_cli import resolve_cli


class RealMemoryAudioTests(unittest.TestCase):
    def test_transcribe_and_align_match_path_for_bytes_and_array(self):
        source = Path(__file__).resolve().parents[4] / 'code/desktop/tests/data/example.wav'
        with wave.open(str(source), 'rb') as wav:
            self.assertEqual((wav.getsampwidth(), wav.getnchannels()), (2, 1))
            rate = wav.getframerate()
            raw = wav.readframes(4 * rate)
        mono = np.frombuffer(raw, dtype='<i2').copy()
        multichannel = np.repeat(mono[:, None], 3, axis=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'speech.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                wav.writeframes(raw)
            encoded = path.read_bytes()
            with patch('edgespeak._bootstrap.ensure_cli', return_value=resolve_cli()), EdgeSpeak(device='cpu', timeout=180) as client:
                baseline = client.transcribe(path)
                self.assertTrue(baseline['text'].strip())
                for value, options in ((encoded, {}), (mono, {'sample_rate': rate}),
                                       (multichannel, {'sample_rate': rate})):
                    with self.subTest(operation='transcribe', array=isinstance(value, np.ndarray), shape=getattr(value, 'shape', None)):
                        result = client.transcribe(value, **options)
                        self.assertEqual(result['text'], baseline['text'])
                reference = baseline['text']
                aligned = client.align(path, text=reference)
                self.assertTrue(aligned['segments'])
                for value, options in ((encoded, {}), (mono, {'sample_rate': rate}),
                                       (multichannel, {'sample_rate': rate, 'audio_channel': 1})):
                    with self.subTest(operation='align', array=isinstance(value, np.ndarray)):
                        result = client.align(value, text=reference, **options)
                        self.assertEqual(len(result['segments']), len(aligned['segments']))
                        for actual, expected in zip(result['segments'], aligned['segments']):
                            self.assertEqual(actual['text'], expected['text'])
                            for key in ('start', 'end'):
                                self.assertAlmostEqual(actual[key], expected[key], delta=.03)
