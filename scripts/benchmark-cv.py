"""Synthetic CV hot-loop comparisons; these do not measure model throughput."""
from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import timeit
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cv.disc_tracker import DiscTracker
from cv.throw_events import EventSettings, carry_evidence
from cv.throw_events_v3 import _relative_carry


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def git_output(*arguments):
    return subprocess.check_output(['git', '-C', str(ROOT), *arguments], text=True)


def load_baseline(commit, filename):
    """Execute local historical Python source; no checkout or working-tree edits."""
    path = f'cv/{filename}.py'
    source = git_output('show', f'{commit}:{path}')
    name = f'cv._benchmark_baseline_{filename}'
    module = types.ModuleType(name)
    module.__package__ = 'cv'
    # Dataclass annotation resolution requires a registered module during exec.
    sys.modules[name] = module
    exec(compile(source, f'{commit}:{path}', 'exec'), module.__dict__)
    return module


def stationary_observations():
    return [{'frame_id': i, 't_sec': i / 240, 'bbox': [110., 140., 122., 148.],
             'dog_bbox': [100., 100., 180., 200.], 'dog_id': 'dog-1', 'dog_gap': .02,
             'measurement_source': 'saved_detector'} for i in range(180)]


def association_cost(track, candidate, now):
    return ((track * 17 + candidate * 3) % 100) / 100


def compare(name, original, current, iterations, repeats):
    if original() != current():
        raise AssertionError(f'{name}: baseline and current outputs differ')
    before = statistics.median(timeit.repeat(original, number=iterations, repeat=repeats)) / iterations
    after = statistics.median(timeit.repeat(current, number=iterations, repeat=repeats)) / iterations
    print(f'{name}: {before * 1000:.3f} -> {after * 1000:.3f} ms ({before / after:.2f}x faster)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='442b432', help='trusted local Git commit/ref to compare (default: %(default)s)')
    parser.add_argument('--repeats', type=positive_integer, default=5,
                        help='number of timing samples; reports the median (default: %(default)s)')
    args = parser.parse_args()
    commit = git_output('rev-parse', '--verify', '--end-of-options', f'{args.baseline}^{{commit}}').strip()
    print(f'Baseline: {commit}; repeats: {args.repeats}')
    print('Synthetic hot loops only; excludes video decoding and model inference. Exact outputs checked.')
    points = stationary_observations()
    contact = points[:1]
    cfg = EventSettings()
    for filename, name, current in (
        ('throw_events', 'carry_evidence', carry_evidence),
        ('throw_events_v3', '_relative_carry', _relative_carry),
    ):
        original = getattr(load_baseline(commit, filename), name)
        compare(f'{name} (180 observations at 240 fps)',
                lambda: original(points, contact, cfg), lambda: current(points, contact, cfg), 3, args.repeats)

    original_class = load_baseline(commit, 'disc_tracker').DiscTracker
    old, new = original_class(1000, 600), DiscTracker(1000, 600)
    for tracker in (old, new):
        tracker.tracks = list(range(16))
        tracker._cost = association_cost
    candidates = list(range(160))
    compare('_associate (16 tracks x 160 candidates)',
            lambda: old._associate(1., candidates), lambda: new._associate(1., candidates), 20, args.repeats)


if __name__ == '__main__':
    main()
