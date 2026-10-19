"""Compare path, bytes and multichannel ndarray through a real gateway/decoder."""
from pathlib import Path
import subprocess
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
        channel_fixtures = []
        for count, selected in ((3, 1), (6, 3), (8, 7)):
            audio = np.zeros((len(mono), count), dtype=np.int16)
            audio[:, selected] = mono
            channel_fixtures.append((audio, selected))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'speech.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                wav.writeframes(raw)
            encoded = path.read_bytes()
            with patch('edgespeak._bootstrap.ensure_cli', return_value=resolve_cli()), EdgeSpeak(device='cpu', timeout=180) as client:
                baseline = client.transcribe(path)
                self.assertTrue(baseline['text'].strip())
                compressed = []
                for extension, codec in (("mp3", "libmp3lame"), ("ogg", "libvorbis")):
                    output = path.with_suffix('.' + extension)
                    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(path), '-c:a', codec, str(output)], check=True, capture_output=True)
                    compressed.append(output)
                variants = [(encoded, {}), (mono, {'sample_rate': rate})] + [(audio, {'sample_rate': rate}) for audio, _ in channel_fixtures]
                for value, options in variants:
                    with self.subTest(operation='transcribe', array=isinstance(value, np.ndarray), shape=getattr(value, 'shape', None)):
                        result = client.transcribe(value, **options)
                        self.assertEqual(result['text'], baseline['text'])
                reference = baseline['text']
                aligned = client.align(path, text=reference)
                self.assertTrue(aligned['segments'])
                variants = [(encoded, {}), (mono, {'sample_rate': rate})] + [(audio, {'sample_rate': rate, 'audio_channel': selected}) for audio, selected in channel_fixtures]
                for value, options in variants:
                    with self.subTest(operation='align', array=isinstance(value, np.ndarray)):
                        result = client.align(value, text=reference, **options)
                        self.assertEqual(len(result['segments']), len(aligned['segments']))
                        for actual, expected in zip(result['segments'], aligned['segments']):
                            self.assertEqual(actual['text'], expected['text'])
                            for key in ('start', 'end'):
                                self.assertAlmostEqual(actual[key], expected[key], delta=.03)
                # Lossy codecs may shift alignment relative to the original WAV.
                # Compare each encoded bytes upload with the exact same compressed file.
                for compressed_path in compressed:
                    with self.subTest(format=compressed_path.suffix):
                        payload = compressed_path.read_bytes()
                        expected = client.transcribe(compressed_path)
                        self.assertEqual(client.transcribe(payload)['text'], expected['text'])
                        expected = client.align(compressed_path, text=reference)
                        actual = client.align(payload, text=reference)
                        self.assertEqual(actual['segments'], expected['segments'])
