"""Observed geometry and review candidates; never automatic catch/miss labels."""
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, asdict
import math


def finite(x):
    return isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x)


def center(b):
    return [(b[0]+b[2])/2, (b[1]+b[3])/2]


def diagonal(b):
    return math.hypot(b[2]-b[0], b[3]-b[1])


def box_gap(a, b):
    """Rectangle edge distance, NOT distance to the dog's mouth."""
    return math.hypot(max(a[0]-b[2], b[0]-a[2], 0), max(a[1]-b[3], b[1]-a[3], 0))


@dataclass(frozen=True)
class JointSettings:
    motion_window_sec: float = .25
    min_motion_span_sec: float = .12
    observation_gap_sec: float = .12
    motion_disc_diagonals: float = 1.5
    motion_frame_fraction: float = .008
    min_episode_sec: float = .18
    near_dog_diagonals: float = .08
    approach_dog_diagonals: float = .15
    min_contact_sec: float = .08
    stationary_before_sec: float = .2

    def __post_init__(self):
        if any(not finite(v) or v <= 0 for v in asdict(self).values()):
            raise ValueError('Joint thresholds must be positive and finite')
        if self.min_motion_span_sec > self.motion_window_sec or self.observation_gap_sec > self.motion_window_sec:
            raise ValueError('Motion span/gap must fit the motion window')
        if self.near_dog_diagonals > 1 or self.motion_frame_fraction >= 1:
            raise ValueError('Invalid normalized geometry threshold')


def validate_rows(dogs, discs, records, width, height):
    if not records or len(dogs) != len(records) or len(discs) != len(records):
        raise ValueError('Dog, disc and source-index coverage must match exactly')
    previous = None
    for dog, disc, record in zip(dogs, discs, records):
        if type(record.get('frame_id')) is not int or record['frame_id'] < 0 or not finite(record.get('t_sec')) or not finite(record.get('pts_sec')):
            raise ValueError('Invalid source identity/time')
        if previous and (record['frame_id'] != previous['frame_id']+1 or record['t_sec'] <= previous['t_sec'] or record['pts_sec'] <= previous['pts_sec']):
            raise ValueError('Require continuous frame IDs and strictly increasing source times')
        previous = record
        for row in (dog, disc):
            if any(row.get(k) != record[k] for k in ('frame_id','t_sec','pts_sec')):
                raise ValueError('Source frame/time mismatch between inputs')
        if not isinstance(disc.get('tracks'), list):
            raise ValueError('Invalid disc state row')
        ids = set()
        for target, kind in [(dog,'dog')]+[(t,'disc') for t in disc['tracks']]:
            identity = target.get('track_id')
            if kind == 'disc' and identity:
                if identity in ids: raise ValueError('Duplicate disc identity in source frame')
                ids.add(identity)
            state = target.get('state')
            if state not in ('detected','predicted','lost','acquiring','searching','retired'):
                raise ValueError('Unknown observation state')
            b = target.get('bbox')
            if (state == 'detected') != (b is not None) or b is not None and not identity:
                raise ValueError('Measurement/state/identity inconsistency')
            if b is not None:
                if not isinstance(b,list) or len(b)!=4 or not all(finite(x) for x in b) or not 0 <= b[0] < b[2] <= width or not 0 <= b[1] < b[3] <= height:
                    raise ValueError('Invalid display-oriented original-pixel box')
                confidence=target.get('confidence')
                if confidence is not None and (not finite(confidence) or not 0 <= confidence <= 1):
                    raise ValueError('Invalid confidence')
                if kind=='disc':
                    source=target.get('measurement_source')
                    if source not in ('saved_detector','local_yolo','local_visual'):
                        raise ValueError('Explicit recovered-disc measurement source required')
                    if source=='local_visual' and confidence is not None:
                        raise ValueError('Visual observations must have null model confidence')
            elif kind=='disc' and target.get('measurement_source') is not None:
                raise ValueError('Missing/predicted disc cannot have an observation source')


def analyze(dogs, discs, records, width, height, camera='tripod', settings=None):
    cfg = settings or JointSettings()
    if not finite(width) or not finite(height) or width <= 0 or height <= 0:
        raise ValueError('Positive display dimensions required')
    if camera not in ('tripod','handheld'): raise ValueError('Unknown camera mode')
    validate_rows(dogs,discs,records,width,height)
    histories = defaultdict(deque)
    frames, points, stationary = [], defaultdict(list), {}
    frame_diag = math.hypot(width,height)
    for dog,disc,record in zip(dogs,discs,records):
        now=record['t_sec']
        dog_box=dog['bbox'] if dog['state']=='detected' else None
        joint=[]
        for t in disc['tracks']:
            identity=t['track_id']
            if not identity: continue
            b=t['bbox'] if t['state']=='detected' else None
            p={'disc_id':identity,'state':t['state'],'bbox':b,'prediction_bbox':t.get('prediction_bbox'),
               'measurement_source':t.get('measurement_source'),'confidence':t.get('confidence'),
               'phase':'unobserved','moving':False,'gap_to_dog_px':None,'gap_to_dog_diagonals':None,
               'dog_id':dog['track_id'] if dog_box else None,'approaching':False,
               'observed_speed_px_sec':None,'motion_span_sec':None,'stationary_before':False}
            history=histories[identity]
            if b is None:
                stationary.pop(identity,None)
                joint.append(p)
                continue
            if history and now-history[-1]['time'] > cfg.observation_gap_sec+1e-9:
                history.clear()
                stationary.pop(identity,None)
            while history and now-history[0]['time'] > cfg.motion_window_sec+1e-9:
                history.popleft()
            gap=box_gap(b,dog_box) if dog_box else None
            p['gap_to_dog_px']=gap
            p['gap_to_dog_diagonals']=gap/diagonal(dog_box) if dog_box else None
            sample={'time':now,'center':center(b),'bbox':b,'dog_box':dog_box,'dog_id':p['dog_id'],'gap':gap}
            history.append(sample)
            if len(history)>=3 and now-history[0]['time'] >= cfg.min_motion_span_sec-1e-9:
                first=history[0]
                span=now-first['time']
                distance=math.dist(first['center'],sample['center'])
                threshold=max(cfg.motion_disc_diagonals*max(diagonal(first['bbox']),diagonal(b)),cfg.motion_frame_fraction*frame_diag)
                p['moving']=distance>=threshold
                p['motion_span_sec']=span
                p['observed_speed_px_sec']=distance/span
                p['phase']='moving_candidate' if p['moving'] else 'stationary_or_slow'
                if p['moving']:
                    p['stationary_before']=identity in stationary and now-stationary[identity]>=cfg.stationary_before_sec
                    stationary.pop(identity,None)
                else:
                    stationary.setdefault(identity,now)
                # Identity continuity and only measured dog positions on both ends.
                if dog_box and first['dog_box'] and first['dog_id']==p['dog_id']:
                    p['approaching']=p['moving'] and first['gap']-gap >= cfg.approach_dog_diagonals*diagonal(dog_box)
            else:
                p['phase']='insufficient_motion_history'
            if dog_box and p['gap_to_dog_diagonals']<=cfg.near_dog_diagonals:
                p['phase']='near_dog_candidate'
            elif p['approaching']:
                p['phase']='approaching_dog_candidate'
            point={**p,'frame_id':record['frame_id'],'t_sec':now,'dog_bbox':dog_box}
            points[identity].append(point)
            joint.append(p)
        frames.append({**record,'dog':{'track_id':dog['track_id'],'state':dog['state'],'bbox':dog_box,
                       'prediction_bbox':dog.get('prediction_bbox'),'confidence':dog.get('confidence'),
                       'measurement_source':'saved_detector' if dog_box else None},'discs':joint})

    events=[]
    def groups(sequence, predicate, same_dog=False):
        group=[]
        for p in sequence:
            valid=predicate(p)
            if group and (not valid or p['t_sec']-group[-1]['t_sec']>cfg.observation_gap_sec+1e-9 or same_dog and p['dog_id']!=group[-1]['dog_id']):
                yield group
                group=[]
            if valid: group.append(p)
        if group: yield group

    for identity,sequence in points.items():
        motions=[g for g in groups(sequence,lambda p:p['moving']) if len(g)>=3 and g[-1]['t_sec']-g[0]['t_sec']>=cfg.min_episode_sec-1e-9]
        for g in motions:
            events.append(_event(identity,'throw_candidate' if camera=='tripod' and any(p['stationary_before'] for p in g) else 'disc_motion_candidate',g,records,camera))
        for g in groups(sequence,lambda p:p['phase']=='near_dog_candidate',True):
            if len(g)<3 or g[-1]['t_sec']-g[0]['t_sec']<cfg.min_contact_sec-1e-9: continue
            # A held/ground plate next to the dog alone does not create contact event.
            associated=[m for m in motions if m[0]['t_sec']<=g[-1]['t_sec'] and m[-1]['t_sec']>=g[0]['t_sec']-.5]
            if not associated: continue
            event=_event(identity,'contact_candidate',g,records,camera)
            event['evidence']['dog_id']=g[0]['dog_id']
            event['evidence']['minimum_box_gap_px']=min(p['gap_to_dog_px'] for p in g)
            event['evidence']['mouth_localized']=False
            # A disappearance is an uncertainty reason, never a catch or miss.
            later=[p for p in sequence if g[-1]['t_sec']<p['t_sec']<=g[-1]['t_sec']+.3]
            event['evidence']['disc_observed_within_next_0_3_sec']=bool(later)
            paired=[p for p in later if p['dog_id']==g[0]['dog_id'] and p['dog_bbox']]
            co_motion=False
            if paired and paired[-1]['t_sec']-g[-1]['t_sec']>=.2:
                end=paired[-1]
                dv=[y-x for x,y in zip(center(g[-1]['bbox']),center(end['bbox']))]
                kv=[y-x for x,y in zip(center(g[-1]['dog_bbox']),center(end['dog_bbox']))]
                # This is geometry only. No claim the disc is held in the mouth.
                co_motion=min(math.hypot(*dv),math.hypot(*kv))>=.1*diagonal(end['dog_bbox']) and math.dist(dv,kv)<=.25*diagonal(end['dog_bbox'])
            event['evidence']['post_contact_co_motion_candidate']=co_motion
            event['uncertainty_reasons']+=['dog_box_is_not_mouth','2d_proximity_does_not_prove_contact']
            if not later: event['uncertainty_reasons'].append('disc_disappears_after_proximity')
            events.append(event)
    events.sort(key=lambda e:(e['start_sec'],e['disc_id'],e['type']))
    for i,e in enumerate(events): e['event_id']=f'candidate-{i+1:03d}'
    metrics={'processed_frames':len(records),'dog_observed_frames':sum(f['dog']['bbox'] is not None for f in frames),
             'joint_observed_frames':sum(f['dog']['bbox'] is not None and any(d['bbox'] is not None for d in f['discs']) for f in frames),
             'phase_observations':dict(Counter(d['phase'] for f in frames for d in f['discs'])),
             'candidate_types':dict(Counter(e['type'] for e in events)),
             'confirmed_throws':None,'confirmed_catches':None,'confirmed_misses':None,'catch_rate':None}
    return frames,events,metrics


def _event(identity,kind,g,records,camera):
    sources=Counter(p['measurement_source'] for p in g)
    return {'event_id':None,'type':kind,'disc_id':identity,'start_frame':g[0]['frame_id'],'end_frame':g[-1]['frame_id'],
            'start_sec':g[0]['t_sec'],'end_sec':g[-1]['t_sec'],
            'review_start_sec':max(records[0]['t_sec'],g[0]['t_sec']-1),
            'review_end_sec':min(records[-1]['t_sec'],g[-1]['t_sec']+1),
            'review_status':'unreviewed','outcome':'uncertain','model_probability':None,
            'evidence':{'observed_samples':len(g),'measurement_sources':dict(sources),
                        'approaching_samples':sum(p['approaching'] for p in g),'stationary_before':any(p['stationary_before'] for p in g)},
            'uncertainty_reasons':['heuristic_candidate_not_ground_truth','local_track_id_may_fragment_or_switch']+
                (['local_visual_box_can_cover_only_part_of_disc'] if sources['local_visual'] else [])+
                (['camera_motion_not_compensated'] if camera=='handheld' else [])}
