"""Progress-driven stage deadlines still preserve owned process controls."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from itertools import chain, repeat
from unittest.mock import Mock, patch

import psutil

from backend.process_control import ProcessControl


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Expected state was not reached.')


class ProcessProgressTests(unittest.TestCase):
    def test_new_progress_resets_stage_deadline_and_final_update_is_delivered(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            progress = root / 'stage'
            stages = []
            control = ProcessControl(lambda _status: None)

            def observe():
                value = progress.read_text() if progress.exists() else ''
                if value and (not stages or stages[-1] != value):
                    stages.append(value)
                    return True
                return False

            command = "from pathlib import Path; import time\nfor i in range(6):\n Path('stage').write_text(str(i)); time.sleep(.18)\nPath('stage').write_text('final')"
            with (root / 'process.log').open('wb') as output:
                control.command([sys.executable, '-u', '-c', command], cwd=root, stdout=output,
                    timeout=.45, on_progress=observe)
            self.assertGreaterEqual(len(stages), 3)
            self.assertEqual(stages[-1], 'final')
            self.assertIsNone(control.process)

    def test_polling_without_new_progress_does_not_extend_timeout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control = ProcessControl(lambda _status: None)
            observed_pids = []

            def observe():
                observed_pids.append(control.process.pid)
                return False

            with (root / 'process.log').open('wb') as output:
                with self.assertRaises(subprocess.TimeoutExpired):
                    control.command([sys.executable, '-c', 'import time; time.sleep(10)'], cwd=root,
                        stdout=output, timeout=.25, on_progress=observe)
            self.assertGreaterEqual(len(observed_pids), 2)
            self.assertIsNone(control.process)
            self.assertFalse(psutil.pid_exists(observed_pids[0]))

    def test_progress_is_read_even_when_first_poll_already_reports_completion(self):
        process = Mock()
        process.poll.return_value = 0
        process.wait.return_value = 0
        observe = Mock(return_value=True)
        control = ProcessControl(lambda _status: None)
        with patch('backend.process_control.subprocess.Popen', return_value=process):
            control.command(['already-finished'], cwd=Path.cwd(), stdout=None, timeout=1, on_progress=observe)
        observe.assert_called()
        self.assertIsNone(control.process)

    def test_final_wait_progress_is_drained_before_old_stage_timeout(self):
        process = Mock()
        completed = False
        delivered = []

        def wait(timeout):
            nonlocal completed
            completed = True
            return 0

        def observe():
            if completed and not delivered:
                delivered.append('statistics')
                return True
            return False

        process.poll.side_effect = lambda: 0 if completed else None
        process.wait.side_effect = wait
        ticks = chain([0., .3], repeat(.3))
        control = ProcessControl(lambda _status: None)
        with patch('backend.process_control.subprocess.Popen', return_value=process), \
             patch('backend.process_control.time.monotonic', side_effect=lambda: next(ticks)):
            control.command(['finished-during-wait'], cwd=Path.cwd(), stdout=None, timeout=.2, on_progress=observe)
        self.assertEqual(delivered, ['statistics'])
        self.assertIsNone(control.process)

    def test_progress_failure_terminates_owned_process_and_preserves_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            control = ProcessControl(lambda _status: None)
            observed_pids = []

            def observe():
                observed_pids.append(control.process.pid)
                raise ValueError('Invalid worker progress')

            with (root / 'process.log').open('wb') as output:
                with self.assertRaisesRegex(ValueError, 'Invalid worker progress'):
                    control.command([sys.executable, '-c', 'import time; time.sleep(10)'], cwd=root,
                        stdout=output, timeout=5, on_progress=observe)
            self.assertIsNone(control.process)
            self.assertFalse(psutil.pid_exists(observed_pids[0]))

    def test_progress_callback_preserves_paused_time_exclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            states, failures = [], []
            control = ProcessControl(states.append)
            control.started = True
            callbacks = []

            def observe():
                callbacks.append(time.monotonic())
                return False

            def run():
                try:
                    with (root / 'process.log').open('wb') as output:
                        command = "from pathlib import Path; import time; Path('ready').touch(); time.sleep(.4)"
                        control.command([sys.executable, '-c', command], cwd=root, stdout=output,
                            timeout=.8, on_progress=observe)
                except Exception as exc:
                    failures.append(exc)

            thread = threading.Thread(target=run)
            thread.start()
            try:
                until(lambda: (root / 'ready').exists())
                control.request('pause')
                until(lambda: states and states[-1] == 'paused')
                time.sleep(1)
                control.request('resume')
                thread.join(4)
                self.assertFalse(thread.is_alive())
                self.assertEqual(failures, [])
                self.assertTrue(callbacks)
            finally:
                if thread.is_alive():
                    control.request('cancel')
                    thread.join(5)
