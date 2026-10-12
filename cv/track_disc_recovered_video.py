"""Disc tracking with bounded local recovery on real source frames; keeps v1 intact."""
import argparse
from collections import Counter, deque
from dataclasses import asdict
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import cv2

if __package__:
    from .disc_tracker import DiscSettings, center, contract_rows
    from .disc_recovery import RecoveryTracker, RecoverySettings
    from .detect_video import load_detection_model, model_class_names
    from .track_dog_video import load_detections, read_json, write_json, draw_box
    from .detect_disc_video import sha256
    from .video_tools.media import Toolchain, iter_source_frames
    from .video_tools.review import validate_results
else:
    from disc_tracker import DiscSettings, center, contract_rows
    from disc_recovery import RecoveryTracker, RecoverySettings
    from detect_video import load_detection_model, model_class_names
    from track_dog_video import load_detections, read_json, write_json, draw_box
    from detect_disc_video import sha256
    from video_tools.media import Toolchain, iter_source_frames
    from video_tools.review import validate_results

PROJECT = Path(__file__).resolve().parents[1]
VERSION = 2


def annotate(frame, record, state, trail):
    observed = {t['track_id']: center(t['bbox']) for t in state['tracks'] if t['bbox']}
    trail.append((record['t_sec'], observed))
    while trail and record['t_sec'] - trail[0][0] > 2:
        trail.popleft()
    for (_, a), (_, b) in zip(trail, list(trail)[1:]):
        for identity in a.keys() & b.keys():
            cv2.line(frame, tuple(map(round, a[identity])), tuple(map(round, b[identity])), (255, 180, 30), 2)
    scale = max(.65, frame.shape[1] / 1800)
    counts = Counter(t['state'] for t in state['tracks'])
    for t in state['tracks']:
        box = t['bbox'] or t['prediction_bbox'] or t['tentative_bbox']
        if box is None:
            continue
        color = (255, 180, 30) if t['state'] == 'detected' else (0, 220, 255) if t['state'] == 'predicted' else (160, 160, 160)
        draw_box(frame, box, color, t['state'] == 'predicted')
        caption = f"{t['track_id'] or 'candidate'} {t['state']}"
        cv2.putText(frame, caption, (round(box[0]), max(round(62*scale), round(box[1])-6)),
                    cv2.FONT_HERSHEY_SIMPLEX, .45*scale, color, max(1, round(scale)))
    caption = f"DISC | frame {record['frame_id']} | source {record['t_sec']:.3f}s | measured {counts['detected']} | predicted {counts['predicted']}"
    cv2.rectangle(frame, (0,0), (min(frame.shape[1], round(1180*scale)), round(46*scale)), (25,25,25), -1)
    cv2.putText(frame, caption, (round(8*scale), round(29*scale)), cv2.FONT_HERSHEY_SIMPLEX, .55*scale, (255,255,255), max(1,round(scale)))
    for t in state['tracks']:
        if t.get('measurement_source')=='local_visual' and t['bbox']:
            b=t['bbox']
            cv2.putText(frame,'VISUAL', (round(b[0]), min(frame.shape[0]-4, round(b[3])+round(16*scale))), cv2.FONT_HERSHEY_SIMPLEX,.4*scale,(255,100,220),max(1,round(scale)))
    return frame


def missing_windows(records, states):
    """Per-frame absence of *any* confirmed measurement, not airborne-disc recall."""
    windows, first = [], None
    for i, state in enumerate(states):
        detected = any(t['state'] == 'detected' for t in state['tracks'])
        if not detected and first is None:
            first = i
        if first is not None and (detected or i == len(states)-1):
            last = i-1 if detected else i
            windows.append({'start_frame': records[first]['frame_id'], 'end_frame': records[last]['frame_id'],
                            'start_sec': records[first]['t_sec'], 'end_sec': records[last]['t_sec'], 'frames': last-first+1})
            first = None
    return sorted(windows, key=lambda v: v['frames'], reverse=True)


def run(detections, pack, output_dir, settings=None, ffmpeg_dir=None, start=0., end=None, recovery=None, model_path=None):
    started = time.perf_counter()
    settings = settings or DiscSettings()
    recovery = recovery or RecoverySettings()
    model_path = Path(model_path).resolve() if model_path is not None else None
    if model_path is not None and not model_path.is_file():
        raise ValueError("Local weights required; no model download is performed")
    detections, pack, output = Path(detections).resolve(), Path(pack).resolve(), Path(output_dir).resolve()
    video, records, detector_rows, _ = load_detections(detections, pack)
    source = Path(video['source']).resolve()
    if output.is_relative_to(source.parent) or output.is_relative_to(PROJECT/'sources') or output.is_relative_to(PROJECT/'outputs'/'dog-tracking') or output.is_relative_to(pack):
        raise ValueError('Choose an independent disc output directory outside raw videos, packet and dog outputs')
    if any(p.is_relative_to(output) for p in (source, detections, pack)):
        raise ValueError('Output cannot contain input files')
    if isinstance(start, bool) or not isinstance(start, (int,float)) or not math.isfinite(start) or start < 0 or end is not None and (isinstance(end,bool) or not isinstance(end,(int,float)) or not math.isfinite(end) or end <= start):
        raise ValueError('Require finite 0 <= start < end')
    selected = [(r,d) for r,d in zip(records,detector_rows) if r['t_sec'] >= start and (end is None or r['t_sec'] < end)]
    if not selected:
        raise ValueError('No source frames in requested window')
    records, detector_rows = map(list,zip(*selected))
    tools = Toolchain.discover(ffmpeg_dir)
    code_names = ['disc_recovery.py','disc_tracker.py','track_disc_recovered_video.py','track_dog_video.py','dog_tracker.py','detect_disc_video.py','detect_video.py','video_tools/media.py','video_tools/review.py']
    signature = {'version': VERSION, 'source_sha256': video['source_sha256'], 'detections_sha256': sha256(detections),
                 'detector_report_sha256': sha256(detections.with_suffix('.json')), 'settings': asdict(settings), 'recovery_settings':asdict(recovery),
                 'model_sha256':sha256(model_path) if model_path else None,
                 'source_metadata': video['metadata'], 'display_size': [video['width'],video['height']],
                 'frame_index_sha256': sha256(pack/video['paths']['frame_index']),
                 'first_frame': records[0], 'last_frame': records[-1], 'toolchain': tools.version,
                 'code': {name:sha256(Path(__file__).parent/name) for name in code_names}, 'opencv': cv2.__version__}
    key = hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    if output.exists():
        summary = read_json(output/'summary.json')
        if summary.get('status') != 'complete' or summary.get('cache_key') != key:
            raise ValueError('Output already exists with different input/settings; choose a new directory')
        artifacts = summary.get('artifact_sha256')
        if not isinstance(artifacts,dict) or not {'tracks.jsonl','states.jsonl','trajectory.csv','tracked.mp4'}.issubset(artifacts):
            raise ValueError('Invalid cached output manifest')
        for name,digest in artifacts.items():
            target = (output/name).resolve()
            if not target.is_relative_to(output) or not target.is_file() or sha256(target) != digest:
                raise ValueError('Cached output changed; choose a new directory')
        print(f'Verified cache: {output}',flush=True)
        return summary
    output.parent.mkdir(parents=True,exist_ok=True)
    temp = output.parent/f'.disc-tracking-{uuid.uuid4().hex}'
    temp.mkdir()
    writer = None
    try:
        model = names = None
        if model_path:
            import torch
            torch.set_num_threads(4)
            model = load_detection_model(str(model_path))
            names = model_class_names(model)
            if not any(n.lower()=='frisbee' for n in names.values()):
                raise ValueError('Local model has no frisbee class')
        tracker = RecoveryTracker(video['width'],video['height'],settings,recovery,model,names)
        states, tracks = [], []
        compute_seconds = 0.
        fps = video['metadata']['avg_frame_rate']
        if not fps or not math.isfinite(fps) or fps <= 0:
            raise ValueError('Positive nominal replay FPS required')
        writer = cv2.VideoWriter(str(temp/'tracked.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),fps,(video['width'],video['height']))
        if not writer.isOpened():
            raise RuntimeError('Cannot open recovered disc replay writer')
        decoded,trail = 0,deque()
        still_ids = {0,len(records)//2,len(records)-1}
        seen_sources = set()
        for i,(record,frame) in enumerate(iter_source_frames(source,records,video['metadata'],tools)):
            if record != records[i]:
                raise ValueError('Recovery image/index identity mismatch')
            compute_started = time.perf_counter()
            state = tracker.update(record['t_sec'],detector_rows[i]['detections'],frame)
            compute_seconds += time.perf_counter()-compute_started
            states.append({**record,**state})
            tracks.extend(contract_rows(video['id'],record,state))
            new_sources = {t.get('measurement_source') for t in state['tracks']} - seen_sources
            seen_sources.update(new_sources)
            writer.write(annotate(frame,record,states[i],trail))
            if i in still_ids or 'local_visual' in new_sources or 'local_yolo' in new_sources:
                if not cv2.imwrite(str(temp/f"frame-{record['frame_id']:06d}.jpg"),frame):
                    raise RuntimeError('Cannot save recovery audit still')
            decoded += 1
            if decoded % 300 == 0:
                print(f"{video['id']}: recovered/rendered {decoded}/{len(records)} source frames",flush=True)
        writer.release()
        writer = None
        validate_results(tracks,read_json(pack/'manifest.json'),{video['id']:read_json(pack/video['paths']['frame_index'])})
        for name,rows in (('tracks.jsonl',tracks),('states.jsonl',states)):
            (temp/name).write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in rows),encoding='utf-8')
        with (temp/'trajectory.csv').open('w',newline='',encoding='utf-8') as handle:
            csv_writer = csv.writer(handle)
            csv_writer.writerow(['video_id','frame_id','t_sec','pts_sec','track_id','state','measured_x_px','measured_y_px','predicted_x_px','predicted_y_px','confidence','measurement_source'])
            for row in states:
                confirmed = [t for t in row['tracks'] if t['track_id']]
                for t in confirmed or [dict(track_id='',state='unassigned',bbox=None,prediction_bbox=None,confidence=None)]:
                    csv_writer.writerow([video['id'],row['frame_id'],row['t_sec'],row['pts_sec'],t['track_id'],t['state'],
                        *(center(t['bbox']) if t['bbox'] else ['','']), *(center(t['prediction_bbox']) if t['prediction_bbox'] else ['','']),
                        t['confidence'] if t['confidence'] is not None else '',t.get('measurement_source') or ''])
        probe = subprocess.run([tools.ffprobe,'-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,nb_read_frames','-of','json',str(temp/'tracked.mp4')],capture_output=True,check=True)
        stream = json.loads(probe.stdout)['streams'][0]
        if decoded != len(records) or int(stream['nb_read_frames']) != decoded or (stream['width'],stream['height']) != (video['width'],video['height']):
            raise RuntimeError('Replay frame count or dimensions mismatch')
        if sha256(source) != signature['source_sha256'] or sha256(detections) != signature['detections_sha256'] or sha256(detections.with_suffix('.json')) != signature['detector_report_sha256'] or sha256(pack/video['paths']['frame_index']) != signature['frame_index_sha256']:
            raise ValueError('Source or detector input changed during tracking')
        if model_path and sha256(model_path)!=signature['model_sha256']:
            raise ValueError('Local model changed during recovery')
        tracklets = {}
        for row in states:
            for t in row['tracks']:
                if not t['track_id']:
                    continue
                item = tracklets.setdefault(t['track_id'],{'first_frame':row['frame_id'],'start_sec':row['t_sec'],'measured_frames':0,'predicted_frames':0,'lost_frames':0,'reacquisitions':0})
                item['last_frame'],item['end_sec'] = row['frame_id'],row['t_sec']
                field = {'detected':'measured_frames','predicted':'predicted_frames','lost':'lost_frames'}.get(t['state'])
                if field:
                    item[field] += 1
                item['reacquisitions'] += bool(t['reacquired'])
        observation_counts = Counter(t['state'] for r in states for t in r['tracks'])
        frame_counts = {name:sum(any(t['state']==name for t in r['tracks']) for r in states) for name in ('detected','predicted','lost','acquiring')}
        summary = {'status':'complete','video_id':video['id'],'source':str(source),'cache_key':key,'provenance':signature,
                   'processed_frames':decoded,'recovery_counts':tracker.counts,
                   'measurement_sources':dict(Counter(t['measurement_source'] for r in states for t in r['tracks'] if t['bbox'])),
                   'raw_disc_frames':sum(any(d['label']=='disc' for d in r['detections']) for r in detector_rows),
                   'frames_with_state':frame_counts,'observation_states':dict(observation_counts),'track_count':tracker.track_count,
                   'retired_tracks':sum(len(r['retired_track_ids']) for r in states),'tracklets':tracklets,
                   'duplicate_candidates_suppressed':sum(r['duplicate_count'] for r in states),
                   'capacity_rejections':sum(r['capacity_rejections'] for r in states),
                   'rejection_reasons':dict(Counter(t['reason'] for r in states for t in r['tracks'] if t['reason'])),
                   'missing_windows':missing_windows(records,states),'tracking_compute_seconds':compute_seconds,'processing_seconds':time.perf_counter()-started,
                   'validated':{'source_content_unchanged':True,'source_timestamp_index':True,'review_contract':True,'output_frame_count':decoded},
                   'limitations':['VISUAL = local colour-component observation, with null confidence; not a YOLO detection or pure prediction.',
                                  'Visual recovery is bounded since the last model anchor and requires a unique local component, motion and contrast.',
                                  'Local geometric disc tracklets; no appearance re-identification or camera-motion compensation.',
                                  'Held and ground discs, and persistent detector false positives, can establish IDs; counts are not airborne-disc accuracy.',
                                  'Track IDs can fragment after occlusion and can switch at crossings; no throw/catch/miss or physical speed inference.',
                                  'Predictions never become measurements. Blue solid = observed; yellow dashed = predicted; grey = unconfirmed.',
                                  'Frame state counts overlap because several discs may be present.',
                                  'MP4 uses nominal FPS and no audio. Analysis uses true JSONL/CSV source timestamps.',
                                  'disc-unassigned is only a frame-coverage placeholder, not a physical track.']}
        summary['artifact_sha256'] = {p.name:sha256(p) for p in sorted(temp.iterdir()) if p.is_file()}
        write_json(temp/'summary.json',summary)
        temp.rename(output)
        print(json.dumps({'output':str(output),'frames':decoded,'tracks':tracker.track_count,'frames_with_state':frame_counts}),flush=True)
        return summary
    finally:
        if writer is not None:
            writer.release()
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != output.parent or not resolved.name.startswith('.disc-tracking-'):
                raise RuntimeError('Unexpected staging path; refusing cleanup')
            shutil.rmtree(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--detections',required=True,type=Path)
    parser.add_argument('--pack',type=Path,default=PROJECT/'outputs'/'video-analysis-pack')
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--start',type=float,default=0.)
    parser.add_argument('--end',type=float)
    parser.add_argument('--confidence',type=float,default=.25)
    parser.add_argument('--confirm-samples',type=int,default=2)
    parser.add_argument('--prediction-seconds',type=float,default=.12)
    parser.add_argument('--identity-gap-seconds',type=float,default=.35)
    parser.add_argument('--ffmpeg-dir',type=Path)
    parser.add_argument('--model',type=Path,default=PROJECT/'yolo11n.pt')
    parser.add_argument('--no-roi-model',action='store_true')
    parser.add_argument('--max-visual-seconds',type=float,default=.8)
    args = parser.parse_args()
    try:
        settings = DiscSettings(confidence=args.confidence,confirm_samples=args.confirm_samples,
                                prediction_sec=args.prediction_seconds,identity_gap_sec=args.identity_gap_seconds)
        run(args.detections,args.pack,args.output_dir,settings,args.ffmpeg_dir,args.start,args.end,
            RecoverySettings(max_visual_sec=args.max_visual_seconds),None if args.no_roi_model else args.model)
    except (ValueError,OSError,RuntimeError,KeyError,subprocess.SubprocessError) as exc:
        parser.exit(1,f'Disc tracking failed: {exc}\n')


if __name__ == '__main__':
    main()
