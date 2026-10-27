"""Version probes are reused only while both local executables are unchanged."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cv.video_tools.media import MediaError, Toolchain, _tool_versions


class ToolchainCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        suffix = '.exe' if os.name == 'nt' else ''
        self.binary = self.root / f'ffmpeg{suffix}'
        self.probe = self.root / f'ffprobe{suffix}'
        self.binary.write_bytes(b'ffmpeg executable fixture')
        self.probe.write_bytes(b'ffprobe executable fixture')
        self.revision = 1
        _tool_versions.cache_clear()

    def tearDown(self):
        _tool_versions.cache_clear()
        self.temp.cleanup()

    def version_result(self, args, **_kwargs):
        name = Path(args[0]).stem
        return subprocess.CompletedProcess(args, 0, f'{name} version fixture-{self.revision}\nAdditional version details\n'.encode(), b'')

    def test_repeated_discovery_reuses_version_subprocesses_and_returns_fresh_dict(self):
        with patch('cv.video_tools.media.subprocess.run', side_effect=self.version_result) as run:
            first = Toolchain.discover(self.root)
            self.assertEqual(run.call_count, 2)
            self.assertEqual([Path(call.args[0][0]) for call in run.call_args_list], [self.binary, self.probe])
            self.assertTrue(all(call.args[0][1:] == ['-version'] for call in run.call_args_list))
            first.version['ffmpeg'] = 'caller mutation'
            first.version['extra'] = 'must not leak'
            second = Toolchain.discover(str(self.root))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(second.version, {'ffmpeg': 'ffmpeg version fixture-1', 'ffprobe': 'ffprobe version fixture-1'})
            self.assertIsNot(first.version, second.version)

    def test_changing_either_executable_size_invalidates_both_version_probes(self):
        with patch('cv.video_tools.media.subprocess.run', side_effect=self.version_result) as run:
            Toolchain.discover(self.root)
            for revision, executable in enumerate((self.binary, self.probe), 2):
                with self.subTest(executable=executable.name):
                    self.revision = revision
                    with executable.open('ab') as stream:
                        stream.write(b' changed')
                    result = Toolchain.discover(self.root)
                    self.assertEqual(run.call_count, revision * 2)
                    self.assertEqual(result.version['ffmpeg'], f'ffmpeg version fixture-{revision}')
                    Toolchain.discover(self.root)
                    self.assertEqual(run.call_count, revision * 2)

    def test_timestamp_change_invalidates_cache_even_when_size_stays_equal(self):
        with patch('cv.video_tools.media.subprocess.run', side_effect=self.version_result) as run:
            Toolchain.discover(self.root)
            previous = self.binary.stat()
            self.revision = 2
            os.utime(self.binary, ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000))
            result = Toolchain.discover(self.root)
            self.assertEqual(self.binary.stat().st_size, previous.st_size)
            self.assertEqual(run.call_count, 4)
            self.assertEqual(result.version['ffmpeg'], 'ffmpeg version fixture-2')

    def test_failed_version_probes_are_not_cached_and_can_be_retried(self):
        for failing in (self.binary, self.probe):
            with self.subTest(failing=failing.name):
                _tool_versions.cache_clear()
                failed = False

                def version(args, **kwargs):
                    nonlocal failed
                    if Path(args[0]) == failing and not failed:
                        failed = True
                        return subprocess.CompletedProcess(args, 1, b'', b'Temporary version probe failure')
                    return self.version_result(args, **kwargs)

                with patch('cv.video_tools.media.subprocess.run', side_effect=version) as run:
                    with self.assertRaisesRegex(MediaError, 'Temporary version probe failure'):
                        Toolchain.discover(self.root)
                    failed_calls = run.call_count
                    result = Toolchain.discover(self.root)
                    self.assertEqual(run.call_count, failed_calls + 2)
                    self.assertEqual(set(result.version), {'ffmpeg', 'ffprobe'})
                    Toolchain.discover(self.root)
                    self.assertEqual(run.call_count, failed_calls + 2)
