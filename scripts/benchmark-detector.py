"""Compare crop-batch inference time and detections on actual source frames."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=PROJECT / 'yolo11n.pt')
    parser.add_argument('--device', default='0')
    parser.add_argument('--cpu-threads', type=int, default=8)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.cpu_threads < 1 or not args.video.is_file() or not args.model.is_file():
        parser.error('Existing video/model and positive repeats/threads are required')
    import numpy as np
    import torch
    from cv.detect_video import load_detection_model, model_class_names
    from cv.detect_disc_video import detect_frame
    from cv.video_tools.media import Toolchain, scan_video, iter_source_frames
    tools = Toolchain.discover()
    metadata, index, _ = scan_video(args.video, tools)
    selected = [index[i] for i in sorted({0, len(index) // 2, len(index) - 1})]
    frames = list(iter_source_frames(args.video, selected, metadata, tools, mutable=False))
    torch.set_num_threads(args.cpu_threads)
    model = load_detection_model(str(args.model))

    def restore_threads(_predictor):
        if torch.get_num_threads() != args.cpu_threads:
            torch.set_num_threads(args.cpu_threads)

    model.add_callback('on_predict_start', restore_threads)
    names = model_class_names(model)

    def synchronize():
        if args.device != 'cpu':
            torch.cuda.synchronize()

    expected, samples = {}, {1: [], 4: []}
    max_box_delta = max_confidence_delta = 0.
    for _record, frame in frames:
        for batch in (1, 4):
            detect_frame(model, frame, names, device=args.device, tile_batch_size=batch)
    for repeat in range(args.repeats):
        for record, frame in frames:
            for batch in ((1, 4) if repeat % 2 == 0 else (4, 1)):
                synchronize()
                started = time.perf_counter()
                result = detect_frame(model, frame, names, device=args.device, tile_batch_size=batch)
                synchronize()
                samples[batch].append(time.perf_counter() - started)
                if batch == 1:
                    expected[record['frame_id']] = result
                else:
                    reference = expected[record['frame_id']]
                    if [(d.label, d.origin) for d in result] != [(d.label, d.origin) for d in reference]:
                        raise AssertionError('Batching changed detection labels, origins or order')
                    for before, after in zip(reference, result):
                        box_delta = float(np.max(np.abs(np.array(before.bbox) - after.bbox)))
                        confidence_delta = abs(before.confidence - after.confidence)
                        max_box_delta = max(max_box_delta, box_delta)
                        max_confidence_delta = max(max_confidence_delta, confidence_delta)
                        if box_delta > .05 or confidence_delta > .0001:
                            raise AssertionError(f'Detection mismatch: {asdict(before)} vs {asdict(after)}')
    medians = {batch: statistics.median(values) for batch, values in samples.items()}
    report = {'device': args.device, 'torch': torch.__version__, 'cpu_threads': args.cpu_threads,
              'frame_ids': [record['frame_id'] for record, _ in frames], 'repeats': args.repeats,
              'seconds_per_frame': medians, 'speedup': medians[1] / medians[4],
              'max_box_delta_px': max_box_delta, 'max_confidence_delta': max_confidence_delta,
              'limitation': 'Three source frames only; not a recognition accuracy evaluation.'}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
