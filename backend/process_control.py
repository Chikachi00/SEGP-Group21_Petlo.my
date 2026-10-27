"""Control only subprocesses created by this job; never suspend the API process."""
import subprocess
import os
import threading
import time

import psutil

ACTIVE = ('queued', 'running', 'pausing', 'paused', 'cancelling')
TERMINAL = ('completed', 'failed', 'cancelled')


class JobCancelled(Exception):
    pass


class ProcessControl:
    def __init__(self, publish):
        self.condition = threading.Condition(threading.RLock())
        self.publish = publish
        self.pause_requested = False
        self.cancel_requested = False
        self.started = False
        self.finished = False
        self.process = None
        self.suspended = []

    def request(self, action):
        with self.condition:
            if self.finished or self.cancel_requested:
                raise ValueError('This task can no longer be controlled.')
            if action == 'pause':
                if self.pause_requested:
                    return
                self.pause_requested = True
                self.publish('pausing' if self.started else 'paused')
            elif action == 'resume':
                if not self.pause_requested:
                    return
                self.pause_requested = False
                self.publish('running' if self.started else 'queued')
            elif action == 'cancel':
                self.cancel_requested = True
                self.pause_requested = False
                self.publish('cancelling')
            else:
                raise ValueError('Unsupported task action.')
            self.condition.notify_all()

    def _suspend_tree(self):
        if not self.process or self.process.poll() is not None:
            return
        try:
            parent = psutil.Process(self.process.pid)
            # Freeze the parent first so it cannot create more descendants while enumerating.
            parent.suspend()
            self.suspended.append(parent)
            for child in parent.children(recursive=True):
                try:
                    child.suspend()
                    self.suspended.append(child)
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
        except Exception:
            self._resume_tree()
            raise

    def _resume_tree(self):
        for process in reversed(self.suspended):
            try:
                process.resume()
            except psutil.NoSuchProcess:
                pass
        self.suspended.clear()

    def checkpoint(self):
        with self.condition:
            if self.cancel_requested:
                raise JobCancelled()
            if self.pause_requested:
                self._suspend_tree()
                try:
                    self.publish('paused')
                    while self.pause_requested and not self.cancel_requested:
                        self.condition.wait()
                finally:
                    self._resume_tree()
                if self.cancel_requested:
                    raise JobCancelled()
                self.publish('running' if self.started else 'queued')

    @staticmethod
    def _terminate_tree(process):
        try:
            parent = psutil.Process(process.pid)
            # Stop spawning first, then terminate descendants before their parent.
            parent.suspend()
            children = parent.children(recursive=True)
            targets = list(reversed(children)) + [parent]
            for target in targets:
                try:
                    target.terminate()
                    if os.name != 'nt':
                        target.resume()  # POSIX stopped processes must run to handle SIGTERM.
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(targets, timeout=2)
            for target in alive:
                try:
                    target.kill()
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(alive, timeout=2)
        except psutil.NoSuchProcess:
            pass

    def command(self, args, *, cwd, stdout, timeout, on_progress=None):
        """Run an owned process; a new reported stage resets its active timeout."""
        self.checkpoint()
        process = subprocess.Popen([str(arg) for arg in args], cwd=cwd, shell=False,
                                   stdout=stdout, stderr=subprocess.STDOUT)
        with self.condition:
            self.process = process
        active_seconds = 0.0
        try:
            while True:
                self.checkpoint()
                tick = time.monotonic()
                if on_progress is not None and on_progress():
                    active_seconds = 0.0
                code = process.poll()
                if code is not None:
                    if code:
                        raise subprocess.CalledProcessError(code, args)
                    return
                try:
                    process.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    pass
                active_seconds += time.monotonic() - tick
                if active_seconds > timeout:
                    # A stage may finish/write progress during the last wait
                    # slice. Drain it before deciding that the old stage expired.
                    if on_progress is not None and on_progress():
                        active_seconds = 0.0
                    elif process.poll() is None:
                        raise subprocess.TimeoutExpired(args, timeout)
        finally:
            with self.condition:
                self._resume_tree()
                if process.poll() is None:
                    self._terminate_tree(process)
                self.process = None
            process.wait(timeout=5)
