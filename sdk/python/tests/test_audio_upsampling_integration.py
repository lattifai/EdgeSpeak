"""Opt-in real model tests. Uses the machine's existing activation and AudioVAE.

Set EDGESPEAK_TEST_CLI and EDGESPEAK_TEST_AUDIO_UPSAMPLING=1. This test does
not install/activate a license or use a saved account API KEY.
"""
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from edgespeak import EdgeSpeak, EdgeSpeakError


def read_wav(data):
    offset, fmt, pcm, mask = 12, None, None, None
    while offset + 8 <= len(data):
        name, size = struct.unpack_from('<4sI', data, offset)
        body = data[offset + 8:offset + 8 + size]
        if name == b'fmt ':
            fmt = struct.unpack_from('<HHIIHH', body)
            if fmt[0] == 0xfffe:
                mask = struct.unpack_from('<I', body, 20)[0]
                fmt = (struct.unpack_from('<H', body, 24)[0], *fmt[1:])
        if name == b'data':
            pcm = body
        offset += 8 + size + size % 2
    if fmt is None or pcm is None:
        raise AssertionError('missing WAV chunks')
    encoding, channels, rate, _, _, bits = fmt
    if not 1 <= channels <= 8 or (encoding, bits) not in ((1, 16), (3, 32)):
        raise AssertionError('unsupported output format')
    count = len(pcm) // (bits // 8)
    values = struct.unpack('<' + ('f' if encoding == 3 else 'h') * count, pcm)
    values = [v / 32768 for v in values] if encoding == 1 else values
    return rate, [values[c::channels] for c in range(channels)], mask


def make_wav(channels, *, impulses=False, impulse_offset=800):
    floating = channels >= 6
    bits, encoding = (32, 3) if floating else (16, 1)
    block = channels * bits // 8
    mask = {6: 0x3f, 8: 0x63f}.get(channels)
    fmt = struct.pack('<HHIIHH', 0xfffe if mask else encoding, channels, 16000, 16000 * block, block, bits)
    if mask:
        fmt += struct.pack('<HHII', 22, bits, mask, encoding) + bytes.fromhex('00001000800000aa00389b71')
    samples = []
    for frame in range(4800):
        for channel in range(channels):
            silent = channels > 1 and channel == channels - 1
            value = 0 if silent else (0.25 if impulses and frame == impulse_offset + channel * 400 else 0)
            if not silent and not impulses:
                value = .12 * math.sin(2 * math.pi * (440 + channel * 160) * frame / 16000)
            samples.append(value)
    pcm = (struct.pack('<' + 'f' * len(samples), *samples) if floating else
           struct.pack('<' + 'h' * len(samples), *(round(v * 32768) for v in samples)))
    body = b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', len(pcm)) + pcm
    return b'RIFF' + struct.pack('<I', len(body)) + body


@unittest.skipUnless(os.environ.get('EDGESPEAK_TEST_CLI') and os.environ.get('EDGESPEAK_TEST_AUDIO_UPSAMPLING') == '1', 'requires a candidate CLI and explicit real AudioVAE opt-in')
class RealAudioUpsamplingTests(unittest.TestCase):
    def test_sdk_gateway_cli_standalone_usage_and_cleanup(self):
        cli = Path(os.environ['EDGESPEAK_TEST_CLI']).resolve()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            sources = {}
            for channels in (1, 2, 6, 8):
                source = directory / f'input-{channels}.wav'
                source.write_bytes(make_wav(channels))
                sources[channels] = source
            # Account authentication uses the machine's existing activation.
            with patch.dict(os.environ):
                os.environ.pop('EDGESPEAK_API_KEY', None)
                os.environ.pop('EDGESPEAK_ACCESS_TOKEN', None)
                with patch('edgespeak._bootstrap.ensure_cli', return_value=cli):
                    with EdgeSpeak(startup_timeout=60) as client:
                        before = client._request('GET', 'usage')['used']
                        url = str(client._http.base_url).rstrip('/')
                        for channels, source in sources.items():
                            for rate in (8000, 16000, 24000, 44100, 48000):
                                with self.subTest(channels=channels, rate=rate):
                                    data = client.upsample(source, sample_rate=rate)
                                    self.check_audio(data, rate, channels)
                                    if rate == 16000:
                                        self.assertEqual(data, source.read_bytes())
                            for rate in (8000, 24000):
                                output = directory / f'cli-{channels}-{rate}.wav'
                                # The CLI uses this variable for its gateway bearer token.
                                # SDK account API KEY handling is a separate credential path.
                                env = dict(os.environ, EDGESPEAK_API_KEY=client._http.headers['authorization'].removeprefix('Bearer '))
                                result = subprocess.run([str(cli), 'upsample', str(source), '--output', str(output), '--sample-rate', str(rate), '--base-url', url], env=env, capture_output=True, timeout=180)
                                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                                self.check_audio(output.read_bytes(), rate, channels)
                        impulse = directory / 'impulses.wav'
                        impulse.write_bytes(make_wav(8, impulses=True))
                        rate, planes, _ = read_wav(client.upsample(impulse, sample_rate=8000))
                        for channel, plane in enumerate(planes[:-1]):
                            peak = max(range(len(plane)), key=lambda i: abs(plane[i]))
                            self.assertLessEqual(abs(peak - (800 + channel * 400) // 2), 1)
                        self.assertEqual(max(map(abs, planes[-1])), 0)
                        # AudioVAE may reshape a transient. Compare against real mono
                        # inference, rather than claiming waveform peaks never move.
                        rate, planes, _ = read_wav(client.upsample(impulse, sample_rate=48000))
                        for channel in (0, 2, 3):
                            mono = directory / f'mono-impulse-{channel}.wav'
                            mono.write_bytes(make_wav(1, impulses=True, impulse_offset=800 + channel * 400))
                            _, reference, _ = read_wav(client.upsample(mono, sample_rate=48000))
                            self.assertEqual(len(planes[channel]), len(reference[0]))
                            self.assertLess(max(abs(a - b) for a, b in zip(planes[channel], reference[0])), 1e-6,
                                            f'multichannel processing shifted or mixed channel {channel}')
                        unsupported = bytearray(make_wav(1))
                        unsupported[20:22] = struct.pack('<H', 6)
                        for code, content in [('audio_format_unsupported', b'invalid'), ('audio_channels_unsupported', make_wav(9)), ('audio_format_unsupported', unsupported)]:
                            bad = directory / 'bad.wav'
                            bad.write_bytes(content)
                            with self.assertRaises(EdgeSpeakError) as error:
                                client.upsample(bad)
                            self.assertEqual(error.exception.code, code)
                        # The CLI renders localized guidance while retaining a stable code.
                        result = subprocess.run([str(cli), 'upsample', str(bad), '--output', str(directory / 'bad-output.wav'), '--base-url', url], env=dict(env, EDGESPEAK_CLI_LOCALE='zh-CN'), capture_output=True, timeout=30)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('audio_format_unsupported', result.stderr.decode())
                        self.assertIn('PCM16', result.stderr.decode())
                        self.assertFalse((directory / 'bad-output.wav').exists())
                        # Non-16k source rates must also produce a common output length.
                        for source_rate in (8000, 24000, 44100):
                            source_bytes = bytearray(make_wav(2))
                            struct.pack_into('<I', source_bytes, 24, source_rate)
                            struct.pack_into('<I', source_bytes, 28, source_rate * 4)
                            alternate = directory / f'source-{source_rate}.wav'
                            alternate.write_bytes(source_bytes)
                            output_rate, planes, _ = read_wav(client.upsample(alternate, sample_rate=48000))
                            self.assertEqual(output_rate, 48000)
                            self.assertEqual(len(planes), 2)
                            self.assertEqual(len(planes[0]), round(4800 * 48000 / source_rate))
                            self.assertEqual(len(planes[0]), len(planes[1]))
                            self.assertTrue(all(math.isfinite(v) for plane in planes for v in plane))
                        self.assertEqual(before, client._request('GET', 'usage')['used'])
                    # Verify the owned listener is really gone.
                    from urllib.parse import urlsplit
                    parsed = urlsplit(url)
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            with socket.create_connection((parsed.hostname, parsed.port), timeout=.2):
                                pass
                        except OSError:
                            break
                        self.assertLess(time.monotonic(), deadline, 'owned gateway stayed open')
                        time.sleep(.1)
            # Exercise the independent one-shot backend, without a gateway.
            host = cli.with_name('edgespeak-mcp' + ('.exe' if os.name == 'nt' else ''))
            for channels, source in sources.items():
                for rate in (8000, 48000):
                    output = directory / f'standalone-{channels}-{rate}.wav'
                    result = subprocess.run([str(host), 'upsample', str(source), '--output', str(output), '--sample-rate', str(rate), '--dev-standalone'], capture_output=True, timeout=180)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                    self.check_audio(output.read_bytes(), rate, channels)

            # Exercise the public CLI fallback, not just the private one-shot binary.
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))  # Reserved but not listening: connect must fail.
                base_url = f'http://127.0.0.1:{reserved.getsockname()[1]}/v1'
                output = directory / 'cli-standalone.wav'
                env = dict(os.environ, EDGESPEAK_CLI_LOCALE='zh-CN')
                result = subprocess.run([str(cli), 'upsample', str(sources[8]), '-o', str(output), '--sample-rate', '24000', '--base-url', base_url], env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                self.check_audio(output.read_bytes(), 24000, 8)
                bad_output = directory / 'cli-standalone-bad.wav'
                result = subprocess.run([str(cli), 'upsample', str(bad), '-o', str(bad_output), '--base-url', base_url], env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('audio_format_unsupported', result.stderr.decode())
                self.assertIn('PCM16', result.stderr.decode())
                self.assertFalse(bad_output.exists())

            # Include all standalone calls in the no-usage assertion as well.
            with patch.dict(os.environ), patch('edgespeak._bootstrap.ensure_cli', return_value=cli):
                os.environ.pop('EDGESPEAK_API_KEY', None)
                os.environ.pop('EDGESPEAK_ACCESS_TOKEN', None)
                with EdgeSpeak(startup_timeout=60) as client:
                    self.assertEqual(before, client._request('GET', 'usage')['used'])

    def check_audio(self, data, requested_rate, channels):
        rate, planes, mask = read_wav(data)
        self.assertEqual(rate, requested_rate)
        self.assertEqual(len(planes), channels)
        if channels in (6, 8):
            self.assertEqual(mask, {6: 0x3f, 8: 0x63f}[channels])
        for channel, values in enumerate(planes):
            self.assertLessEqual(abs(len(values) - round(rate * .3)), 1)
            self.assertTrue(all(math.isfinite(v) for v in values))
            rms = math.sqrt(sum(v * v for v in values) / len(values))
            if channels > 1 and channel == channels - 1:
                self.assertLess(rms, .002, 'silent channel acquired audio')
                continue
            self.assertGreater(rms, .001)
            self.assertLess(rms, 1)
            expected = 440 + channel * 160
            def power(frequency):
                real = sum(v * math.cos(2 * math.pi * frequency * i / rate) for i, v in enumerate(values))
                imag = sum(v * math.sin(2 * math.pi * frequency * i / rate) for i, v in enumerate(values))
                return real * real + imag * imag
            self.assertEqual(max((expected - 40, expected - 20, expected, expected + 20, expected + 40), key=power), expected, f'channel {channel} changed pitch or order')

@unittest.skipUnless(os.environ.get('EDGESPEAK_TEST_CLI') and os.environ.get('EDGESPEAK_TEST_AUDIO_FORMATS') == '1',
                     'requires candidate CLI, ffmpeg and explicit delivery-codec opt-in')
class RealAudioFormatTests(unittest.TestCase):
    def test_formats_through_sdk_gateway_cli_and_standalone(self):
        from unittest.mock import patch
        import json
        cli = Path(os.environ['EDGESPEAK_TEST_CLI']).resolve()
        ffmpeg = os.environ.get('EDGESPEAK_FFMPEG', 'ffmpeg')
        frequencies = (220, 330, 440, 60, 550, 660, 770, 880)
        with tempfile.TemporaryDirectory() as directory, patch('edgespeak._bootstrap.ensure_cli', return_value=cli):
            directory = Path(directory)
            with EdgeSpeak(startup_timeout=60) as client:
                before = client._request('GET', 'usage')['used']
                url = str(client._http.base_url).rstrip('/')
                env = dict(os.environ, EDGESPEAK_API_KEY=client._http.headers['authorization'][7:])
                for channels in (1, 2, 6, 8):
                    source = directory / f'source-{channels}.wav'
                    data = bytearray(make_wav(channels))
                    # Rewrite samples and rate: 0.1 s at 48 kHz, no model needed.
                    offset = data.index(b'data') + 8
                    floating = channels >= 6
                    samples = [.15 * math.sin(2 * math.pi * frequencies[c] * i / 48000)
                               for i in range(4800) for c in range(channels)]
                    data[offset:] = struct.pack('<' + ('f' if floating else 'h') * len(samples),
                                                *(samples if floating else [round(v * 32768) for v in samples]))
                    struct.pack_into('<I', data, 24, 48000)
                    struct.pack_into('<I', data, 28, 48000 * channels * (4 if floating else 2))
                    source.write_bytes(data)
                    for format in ('wav', 'flac', 'mp3', 'm4a', 'aac', 'ogg', 'opus'):
                        if format == 'mp3' and channels > 2:
                            continue
                        with self.subTest(format=format, channels=channels):
                            encoded = client.upsample(source, sample_rate=48000, response_format=format)
                            output = directory / f'sdk-{channels}.{format}'
                            output.write_bytes(encoded)
                            self.check_delivery(output, channels, ffmpeg, frequencies)
                            restored = client.upsample(output, sample_rate=8000)
                            rate, planes, _ = read_wav(restored)
                            self.assertEqual((rate, len(planes)), (8000, channels))
                            command = [str(cli), 'upsample', str(source), '-o', str(output),
                                       '--sample-rate', '48000', '--response-format', format, '--base-url', url]
                            if format not in ('wav', 'flac'):
                                command += ['--bitrate', '128k']
                            result = subprocess.run(command, env=env, capture_output=True, timeout=60)
                            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                            self.check_delivery(output, channels, ffmpeg, frequencies)
                            host = cli.with_name('edgespeak-mcp' + ('.exe' if os.name == 'nt' else ''))
                            result = subprocess.run([str(host), 'upsample', str(source), '--output', str(output),
                                                     '--sample-rate', '48000', '--response-format', format, '--dev-standalone'],
                                                    capture_output=True, timeout=60)
                            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                            self.check_delivery(output, channels, ffmpeg, frequencies)
                self.assertEqual(before, client._request('GET', 'usage')['used'])

    def check_delivery(self, path, channels, ffmpeg, frequencies):
        decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path),
                                  '-f', 'wav', '-c:a', 'pcm_f32le', '-'],
                                 capture_output=True, timeout=30, check=True).stdout
        rate, planes, _ = read_wav(decoded)
        self.assertEqual((rate, len(planes)), (48000, channels))
        self.assertLessEqual(abs(len(planes[0]) - 4800), 3072)
        for channel in range(channels):
            plane = planes[channel]
            self.assertTrue(all(math.isfinite(v) for v in plane))
            def power(frequency):
                re = sum(v * math.cos(2 * math.pi * frequency * i / 48000) for i, v in enumerate(plane))
                im = sum(v * math.sin(2 * math.pi * frequency * i / 48000) for i, v in enumerate(plane))
                return re * re + im * im
            expected = power(frequencies[channel])
            self.assertGreater(expected, .01)
            for other in range(channels):
                if other != channel:
                    self.assertGreater(expected, power(frequencies[other]) * 10,
                                       f'{path.name}: channel {channel} swapped with {other}')
