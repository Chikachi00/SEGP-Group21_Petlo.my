"""Preview encoders preserve source timing and provide a deterministic CPU path."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.preview import PREVIEW_FILTER, encode_preview
from cv.video_tools.media import Toolchain


class PreviewCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.target = self.root / 'source.mp4', self.root / 'previews' / 'preview.mp4'
        self.source.write_bytes(b'unchanged source')
        self.tools = SimpleNamespace(ffmpeg='ffmpeg.exe')

    def tearDown(self):
        self.temp.cleanup()

    def check_timing_arguments(self, command):
        self.assertEqual(command[command.index('-vf') + 1], PREVIEW_FILTER)
        self.assertEqual(command[command.index('-fps_mode') + 1], 'passthrough')
        self.assertEqual(command[command.index('-map') + 1], '0:v:0')
        self.assertEqual(command[command.index('-pix_fmt') + 1], 'yuv420p')
        self.assertEqual(command[command.index('-movflags') + 1], '+faststart')
        self.assertIn('-an', command)
        self.assertIn('-nostdin', command)
        self.assertIn('-y', command)
        self.assertNotIn('-r', command)
        self.assertEqual(command[-1], str(self.target))

    def test_explicit_cpu_uses_software_settings_without_hardware_attempt(self):
        with patch('backend.preview.subprocess.run') as run:
            encoder = encode_preview(self.source, self.target, self.tools, 15, device='cpu')
        self.assertEqual(encoder, 'libx264')
        run.assert_called_once()
        command = run.call_args.args[0]
        self.check_timing_arguments(command)
        self.assertEqual(command[command.index('-c:v') + 1], 'libx264')
        self.assertEqual(command[command.index('-threads') + 1], '2')
        self.assertEqual(command[command.index('-preset') + 1], 'veryfast')
        self.assertEqual(command[command.index('-crf') + 1], '24')
        self.assertEqual(command[command.index('-bf') + 1], '0')
        self.assertEqual(run.call_args.kwargs, {'check': True, 'timeout': 15})

    def test_auto_uses_nvenc_quality_settings_without_a_frame_rate_override(self):
        with patch('backend.preview.subprocess.run') as run:
            self.assertEqual(encode_preview(self.source, self.target, self.tools, 15), 'h264_nvenc')
        run.assert_called_once()
        command = run.call_args.args[0]
        self.check_timing_arguments(command)
        for flag, value in (('-c:v', 'h264_nvenc'), ('-preset', 'p4'), ('-rc', 'vbr'), ('-cq', '24'), ('-b:v', '0')):
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_nvenc_failure_retries_with_cpu_and_replaces_partial_output(self):
        attempted = []

        def encode(command, **kwargs):
            self.check_timing_arguments(command)
            encoder = command[command.index('-c:v') + 1]
            attempted.append(encoder)
            self.target.write_bytes(encoder.encode())
            if encoder == 'h264_nvenc':
                raise subprocess.CalledProcessError(1, command)

        with patch('backend.preview.subprocess.run', side_effect=encode):
            self.assertEqual(encode_preview(self.source, self.target, self.tools, 15), 'libx264')
        self.assertEqual(attempted, ['h264_nvenc', 'libx264'])
        self.assertEqual(self.target.read_bytes(), b'libx264')
        self.assertEqual(self.source.read_bytes(), b'unchanged source')

    def test_numeric_device_selects_matching_nvenc_adapter(self):
        with patch('backend.preview.subprocess.run') as run:
            encode_preview(self.source, self.target, self.tools, 15, device='1')
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-gpu') + 1], '1')

    def test_cpu_failure_and_timeout_propagate_without_repeated_attempts(self):
        for device, error in (('cpu', subprocess.CalledProcessError(3, ['ffmpeg'])),
                              ('auto', subprocess.TimeoutExpired(['ffmpeg'], 15))):
            with self.subTest(device=device, error=type(error).__name__), \
                 patch('backend.preview.subprocess.run', side_effect=error) as run:
                with self.assertRaises(type(error)):
                    encode_preview(self.source, self.target, self.tools, 15, device=device)
                run.assert_called_once()

    def test_source_cannot_be_overwritten(self):
        with patch('backend.preview.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'must differ'):
                encode_preview(self.source, self.source, self.tools, 15)
        run.assert_not_called()
        self.assertEqual(self.source.read_bytes(), b'unchanged source')


class PreviewMediaTests(unittest.TestCase):
    def test_real_hardware_or_fallback_and_cpu_keep_every_vfr_source_timestamp(self):
        tools = Toolchain.discover()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.mkv'
            subprocess.run([tools.ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                'testsrc2=size=96x64:rate=10:duration=1', '-vf',
                r'select=eq(n\,0)+eq(n\,1)+eq(n\,4)+eq(n\,9),setpts=PTS+2/TB',
                '-fps_mode', 'vfr', '-c:v', 'ffv1', str(source)], check=True, capture_output=True, timeout=15)
            original = source.read_bytes()
            cpu, automatic = root / 'cpu.mp4', root / 'automatic.mp4'
            self.assertEqual(encode_preview(source, cpu, tools, 15, device='cpu'), 'libx264')
            encoder = encode_preview(source, automatic, tools, 15)
            self.assertIn(encoder, ('h264_nvenc', 'libx264'))

            def probe(path):
                result = subprocess.run([tools.ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height,nb_read_frames,pix_fmt,codec_name,duration:frame=best_effort_timestamp_time',
                    '-show_frames', '-of', 'json', str(path)], check=True, capture_output=True, timeout=15)
                return json.loads(result.stdout)

            expected = [0., .1, .4, .9]
            reports = [probe(cpu), probe(automatic)]
            for report in reports:
                stream = report['streams'][0]
                self.assertEqual(int(stream['nb_read_frames']), 4)
                self.assertEqual(stream['codec_name'], 'h264')
                self.assertEqual(stream['pix_fmt'], 'yuv420p')
                self.assertEqual([stream['width'], stream['height']], [1080, 720])
                self.assertAlmostEqual(float(stream['duration']), 1., places=5)
                self.assertEqual(len(report['frames']), len(expected))
                for frame, second in zip(report['frames'], expected):
                    self.assertAlmostEqual(float(frame['best_effort_timestamp_time']), second, places=5)
            self.assertAlmostEqual(float(reports[0]['streams'][0]['duration']), float(reports[1]['streams'][0]['duration']), places=5)
            self.assertEqual(source.read_bytes(), original)
