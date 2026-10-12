"""Conservative throw episodes from observations; all outcomes require review."""
from collections import Counter,defaultdict
from dataclasses import dataclass,asdict
import math

if __package__:
    from .joint_analysis import center,diagonal,box_gap,finite
else:
    from joint_analysis import center,diagonal,box_gap,finite


@dataclass(frozen=True)
class EventSettings:
    observation_gap_sec: float = .12
    identity_link_sec: float = .35
    link_frame_fraction: float = .012
    appearance_similarity: float = .9
    min_motion_sec: float = .18
    max_episode_sec: float = 8.
    release_lookback_sec: float = .6
    departure_sec: float = .12
    near_dog_diagonals: float = .08
    far_dog_diagonals: float = .2
    min_contact_sec: float = .08
    post_contact_sec: float = .8
    min_carry_sec: float = .3
    min_ground_still_sec: float = .3

    def __post_init__(self):
        if any(not finite(v) or v<=0 for v in asdict(self).values()):raise ValueError('Positive finite event settings required')
        if not 0<self.appearance_similarity<=1 or self.link_frame_fraction>=1:raise ValueError('Invalid association threshold')
        if self.observation_gap_sec>self.identity_link_sec or self.min_carry_sec>self.post_contact_sec or self.near_dog_diagonals>=self.far_dog_diagonals:
            raise ValueError('Inconsistent temporal/geometry gates')


def observed_points(frames,detections):
    if not frames or len(frames)!=len(detections):raise ValueError('Exact nonempty joint/detector coverage required')
    points=defaultdict(list)
    previous=None
    for row,det in zip(frames,detections):
        if any(row.get(k)!=det.get(k) for k in ('frame_id','t_sec','pts_sec')):raise ValueError('Joint/detector source-time mismatch')
        if previous is not None and (row['frame_id']!=previous['frame_id']+1 or row['t_sec']<=previous['t_sec']):raise ValueError('Invalid frame/time order')
        previous=row
        people=[d['bbox'] for d in det['detections'] if d['label']=='person' and d['confidence']>=.25]
        dog=row['dog']
        if (dog['state']=='detected')!=(dog['bbox'] is not None):raise ValueError('Dog observation/state mismatch')
        seen=set()
        for d in row['discs']:
            identity=d['disc_id']
            if identity in seen:raise ValueError('Duplicate disc identity')
            seen.add(identity)
            if (d['state']=='detected')!=(d['bbox'] is not None):raise ValueError('Disc observation/state mismatch')
            if d['bbox'] is None:continue
            if d['measurement_source'] not in ('saved_detector','local_yolo','local_visual'):raise ValueError('Unknown disc observation source')
            if d['measurement_source']=='local_visual' and d['confidence'] is not None:raise ValueError('Visual confidence must be null')
            dog_box=dog['bbox']
            points[identity].append({**d,'frame_id':row['frame_id'],'t_sec':row['t_sec'],'pts_sec':row['pts_sec'],
                'dog_bbox':dog_box,'dog_id':dog['track_id'] if dog_box else None,'people':people,
                'dog_gap':box_gap(d['bbox'],dog_box)/diagonal(dog_box) if dog_box else None})
    return dict(points)


def velocity(sequence,last=True):
    reference=sequence[-1] if last else sequence[0]
    local=[p for p in sequence if abs(p['t_sec']-reference['t_sec'])<=.15+1e-9]
    if len(local)<3 or local[-1]['t_sec']-local[0]['t_sec']<.03:return None
    if any(b['t_sec']-a['t_sec']>.12+1e-9 for a,b in zip(local,local[1:])):return None
    duration=local[-1]['t_sec']-local[0]['t_sec']
    return [(b-a)/duration for a,b in zip(center(local[0]['bbox']),center(local[-1]['bbox']))]


def link_proposals(points,width,height,camera,settings=None):
    cfg=settings or EventSettings()
    if camera not in ('tripod','handheld'):raise ValueError('Unknown camera mode')
    if not finite(width) or not finite(height) or min(width,height)<=0:raise ValueError('Invalid display dimensions')
    if camera=='handheld':return []
    frame_diag=math.hypot(width,height)
    proposals=[]
    for old,sequence in points.items():
        end=sequence[-1];v=velocity(sequence)
        if v is None or math.hypot(*v)<.01*frame_diag or not any(p['moving'] for p in sequence if end['t_sec']-p['t_sec']<=.2):continue
        for new,other in points.items():
            first=other[0];gap=first['t_sec']-end['t_sec']
            if old==new or not 0<gap<=cfg.identity_link_sec+1e-9:continue
            # Observation intervals cannot overlap; no sharing observations across IDs.
            a,b=end['bbox'],first['bbox'];area=lambda x:(x[2]-x[0])*(x[3]-x[1])
            if not .4<=area(b)/area(a)<=2.5:continue
            expected=[x+u*gap for x,u in zip(center(a),v)]
            residual=math.dist(expected,center(b))
            gate=cfg.link_frame_fraction*frame_diag+1.5*max(diagonal(a),diagonal(b))+.25*math.hypot(*v)*gap
            if residual>gate:continue
            new_v=velocity(other,False)
            if new_v and math.hypot(*new_v)>.01*frame_diag and sum(x*y for x,y in zip(v,new_v))/(math.hypot(*v)*math.hypot(*new_v))<.5:continue
            proposals.append({'from_disc_id':old,'to_disc_id':new,'from_frame':end['frame_id'],'to_frame':first['frame_id'],
                              'gap_sec':gap,'residual_px':residual,'gate_px':gate,'appearance_similarity':None,'accepted':False,'reason':'appearance_required'})
    return proposals


def resolve_links(proposals,appearances,settings=None):
    cfg=settings or EventSettings()
    results=[dict(p) for p in proposals]
    compatible=[]
    for p in results:
        a=appearances.get((p['from_frame'],p['from_disc_id']))
        b=appearances.get((p['to_frame'],p['to_disc_id']))
        if a is None or b is None:continue
        if len(a)!=len(b) or not a or any(not finite(v) or v<0 for v in a+b):raise ValueError('Invalid colour descriptor')
        den=math.sqrt(sum(v*v for v in a)*sum(v*v for v in b))
        similarity=sum(x*y for x,y in zip(a,b))/den if den else 0.
        p['appearance_similarity']=similarity
        p['reason']='appearance_mismatch'
        if similarity>=cfg.appearance_similarity:
            compatible.append(p);p['reason']='ambiguous_continuation'
    outgoing=Counter(p['from_disc_id'] for p in compatible);incoming=Counter(p['to_disc_id'] for p in compatible)
    for p in compatible:
        if outgoing[p['from_disc_id']]==incoming[p['to_disc_id']]==1:
            p['accepted']=True;p['reason']='unique_geometry_and_colour_candidate'
    return results


def groups(sequence,predicate,gap,same_dog=False):
    group=[]
    for p in sequence:
        valid=predicate(p)
        if group and (not valid or p['t_sec']-group[-1]['t_sec']>gap+1e-9 or same_dog and p['dog_id']!=group[-1]['dog_id']):
            yield group;group=[]
        if valid:group.append(p)
    if group:yield group


def person_gap(point):
    return min((box_gap(point['bbox'],b)/diagonal(b) for b in point['people']),default=None)


def release_evidence(sequence,seed,cfg,camera):
    if camera=='handheld':return None
    start=seed[0]['t_sec'];end=seed[-1]['t_sec']
    local=[p for p in sequence if start-cfg.release_lookback_sec<=p['t_sec']<=end]
    near=[g for g in groups(local,lambda p:person_gap(p) is not None and person_gap(p)<=.08,cfg.observation_gap_sec) if len(g)>=2 and g[-1]['t_sec']-g[0]['t_sec']>=.04]
    for anchor_group in reversed(near):
        anchor=anchor_group[-1]
        away=[p for p in local if p['t_sec']>anchor['t_sec']]
        for g in groups(away,lambda p:person_gap(p) is not None and person_gap(p)>=.2,cfg.observation_gap_sec):
            if len(g)<3 or g[-1]['t_sec']-g[0]['t_sec']<cfg.departure_sec-1e-9:continue
            if math.dist(center(anchor['bbox']),center(g[-1]['bbox']))<2*diagonal(anchor['bbox']):continue
            return {'person_near_frame':anchor['frame_id'],'person_near_sec':anchor['t_sec'],
                    'departure_frame':g[0]['frame_id'],'departure_sec':g[0]['t_sec'],
                    'departure_observed_samples':len(g),'person_is_box_reference_not_hand_localization':True}
    return None


def carry_evidence(sequence,contact,cfg):
    after=[p for p in sequence if contact[0]['t_sec']<=p['t_sec']<=contact[0]['t_sec']+cfg.post_contact_sec and p['dog_bbox'] is not None]
    for g in groups(after,lambda p:p['dog_id']==contact[0]['dog_id'] and p['dog_bbox'] is not None and p['dog_gap']<=cfg.near_dog_diagonals,cfg.observation_gap_sec,True):
        if len(g)<5 or g[-1]['t_sec']-g[0]['t_sec']<cfg.min_carry_sec-1e-9:continue
        for last_index in range(4,len(g)):
            for first_index in range(last_index-3):
                window=g[first_index:last_index+1]
                if window[-1]['t_sec']-window[0]['t_sec']<cfg.min_carry_sec-1e-9:continue
                anchors=[p for p in window if p['measurement_source'] in ('saved_detector','local_yolo')]
                if len(anchors)<2 or anchors[-1]['t_sec']-anchors[0]['t_sec']<cfg.min_carry_sec*.5:continue
                first,last=window[0],window[-1];scale=diagonal(last['dog_bbox'])
                disc_v=[b-a for a,b in zip(center(first['bbox']),center(last['bbox']))]
                dog_v=[b-a for a,b in zip(center(first['dog_bbox']),center(last['dog_bbox']))]
                if min(math.hypot(*disc_v),math.hypot(*dog_v))<.1*scale or math.dist(disc_v,dog_v)>.25*scale:continue
                return {'start_frame':first['frame_id'],'end_frame':last['frame_id'],'start_sec':first['t_sec'],'end_sec':last['t_sec'],
                        'dog_id':first['dog_id'],'observed_samples':len(window),'model_observed_samples':len(anchors),
                        'relative_displacement_px':math.dist(disc_v,dog_v),'mouth_localized':False}
    return None


def ground_evidence(sequence,labels,cfg):
    for label in labels:
        anchor=next((p for p in sequence if p['frame_id']==label['frame_id'] and p['disc_id']==label['disc_id']),None)
        if anchor is None:continue
        after=[p for p in sequence if anchor['t_sec']<=p['t_sec']<=anchor['t_sec']+.8]
        for g in groups(after,lambda p:p['dog_bbox'] is not None and p['dog_gap']>=cfg.far_dog_diagonals and math.dist(center(p['bbox']),center(anchor['bbox']))<=diagonal(anchor['bbox']),cfg.observation_gap_sec,True):
            if len(g)>=5 and g[-1]['t_sec']-g[0]['t_sec']>=cfg.min_ground_still_sec-1e-9:
                return {'ground_frame':anchor['frame_id'],'ground_sec':anchor['t_sec'],'reviewer':label['reviewer'],
                        'still_end_frame':g[-1]['frame_id'],'still_end_sec':g[-1]['t_sec'],'observed_samples':len(g)}
    return None


def analyze_events(frames,detections,width,height,camera='tripod',settings=None,appearances=None,ground_contacts=None):
    cfg=settings or EventSettings()
    points=observed_points(frames,detections)
    proposals=link_proposals(points,width,height,camera,cfg)
    links=resolve_links(proposals,appearances or {},cfg)
    parents={p['to_disc_id']:p['from_disc_id'] for p in links if p['accepted']}
    chains=defaultdict(list)
    for identity,sequence in points.items():
        root=identity;seen=set()
        while root in parents:
            if root in seen:raise ValueError('Identity-link cycle')
            seen.add(root);root=parents[root]
        chains[root].extend(sequence)
    labels=ground_contacts or []
    for label in labels:
        if label.get('verified') is not True or not isinstance(label.get('reviewer'),str) or not label['reviewer'].strip() or type(label.get('frame_id')) is not int:
            raise ValueError('Ground contacts require verified source-frame evidence and reviewer')
    events=[];excluded=[]
    for chain,sequence in chains.items():
        sequence.sort(key=lambda p:p['t_sec'])
        if any(a['frame_id']==b['frame_id'] for a,b in zip(sequence,sequence[1:])):raise ValueError('Overlapping joined observations')
        seeds=[g for g in groups(sequence,lambda p:p['moving'],cfg.observation_gap_sec) if len(g)>=3 and g[-1]['t_sec']-g[0]['t_sec']>=cfg.min_motion_sec-1e-9]
        completed=None;blocked_until=None
        releases=[release_evidence(sequence,seed,cfg,camera) for seed in seeds]
        for seed_index,seed in enumerate(seeds):
            start=seed[0]['t_sec']
            release=releases[seed_index]
            if completed and start<=completed['end_sec'] and (release is None or release['person_near_sec']<=completed['start_sec']):
                completed['motion_segments']+=1;continue
            before=[p for p in sequence if start-.3<=p['t_sec']<=start]
            near=lambda p:p['dog_gap'] is not None and p['dog_gap']<=cfg.near_dog_diagonals
            before_joint=[p for p in before if p['dog_gap'] is not None]
            seed_joint=[p for p in seed if p['dog_gap'] is not None]
            prior_near=len(before_joint)>=3 and all(near(p) for p in before_joint)
            seed_near=len(seed_joint)>=3 and sum(near(p) for p in seed_joint)/len(seed_joint)>=.8
            initial_joint=[p for p in seed_joint if p['t_sec']<=start+.25]
            carrying_at_start=len(initial_joint)>=3 and all(near(p) for p in initial_joint) and carry_evidence(sequence,initial_joint,cfg) is not None
            still_blocked=blocked_until is not None and start-blocked_until<=2 and seed_near
            held_near_person=all(person_gap(p) is not None and person_gap(p)<=.08 for p in seed)
            if release is None and (prior_near and seed_near or carrying_at_start or still_blocked or held_near_person):
                excluded.append({'disc_ids':sorted({p['disc_id'] for p in seed}),'start_sec':start,'end_sec':seed[-1]['t_sec'],
                                 'reason':'near_dog_motion_without_new_release' if not held_near_person else 'motion_stays_near_person'})
                continue
            first=release['person_near_sec'] if release else start
            next_releases=[r['person_near_sec'] for r in releases[seed_index+1:] if r and r['person_near_sec']>seed[-1]['t_sec']]
            next_ready=min(next_releases,default=math.inf)
            episode=[];termination='analysis_timeout'
            for p in sequence:
                if p['t_sec']<first:continue
                if p['t_sec']>first+cfg.max_episode_sec:break
                if p['t_sec']>=next_ready:
                    termination='next_person_departure';break
                if episode and p['t_sec']-episode[-1]['t_sec']>cfg.identity_link_sec+1e-9:
                    termination='long_observation_gap';break
                episode.append(p)
            if not episode:continue
            if episode[-1]['frame_id']==frames[-1]['frame_id']:termination='video_ended'
            elif termination=='analysis_timeout' and episode[-1] is sequence[-1] and episode[-1]['t_sec']<first+cfg.max_episode_sec:
                termination='track_observations_ended'
            contacts=[]
            for g in groups(episode,near,cfg.observation_gap_sec,True):
                if len(g)<3 or g[-1]['t_sec']-g[0]['t_sec']<cfg.min_contact_sec-1e-9:continue
                prior=[p for p in episode if p['t_sec']<g[0]['t_sec'] and p['dog_id']==g[0]['dog_id'] and p['dog_gap'] is not None]
                if any(p['dog_gap']>=cfg.far_dog_diagonals for p in prior):contacts.append(g)
            contact=contacts[0] if contacts else None
            carry=carry_evidence(episode,contact,cfg) if contact else None
            ground=ground_evidence(episode,labels,cfg)
            outcome='uncertain'
            if camera=='tripod':
                if ground and (carry is None or ground['ground_sec']<=carry['start_sec']):outcome='miss_candidate'
                elif carry and not ground:outcome='catch_candidate'
            end=episode[-1]['t_sec']
            if termination in ('long_observation_gap','track_observations_ended'):
                end=min(end+cfg.identity_link_sec,first+cfg.max_episode_sec,frames[-1]['t_sec'],next_ready)
            if outcome=='catch_candidate':end=carry['end_sec'];termination='sustained_co_motion_candidate'
            elif outcome=='miss_candidate':end=ground['still_end_sec'];termination='reviewed_ground_and_separation_candidate'
            elif contact:
                end=min(end,contact[0]['t_sec']+cfg.post_contact_sec);termination='contact_unresolved'
            # Keep the end on an actual source frame, including a missing terminal frame.
            end_record=max((r for r in frames if first<=r['t_sec']<=end+1e-9),key=lambda r:r['t_sec'])
            end=end_record['t_sec'];observations=[p for p in episode if p['t_sec']<=end+1e-9]
            start_record=min(observations,key=lambda p:p['t_sec'])
            members=sorted({p['disc_id'] for p in observations})
            relevant_links=[p for p in links if p['accepted'] and p['from_disc_id'] in members and p['to_disc_id'] in members]
            reasons=['heuristic_episode_requires_review','dog_box_is_not_mouth','track_ids_are_not_verified_physical_identity']
            if release is None:reasons.append('release_not_observed')
            if outcome=='uncertain':reasons.append(termination)
            if any(p['measurement_source']=='local_visual' for p in observations):reasons.append('local_visual_box_may_cover_only_disc_colour')
            if camera=='handheld':reasons.append('camera_motion_not_compensated')
            if not ground:reasons.append('no_verified_ground_contact')
            event={'throw_id':None,'start_frame':start_record['frame_id'],'start_sec':start_record['t_sec'],'end_frame':end_record['frame_id'],'end_sec':end,
                   'disc_ids':members,'episode_kind':'throw_candidate' if release else 'flight_motion_candidate',
                   'motion_segments':1,'predicted_outcome':outcome,'verified_outcome':None,'confirmed_throw':None,'review_status':'unreviewed',
                   'event_probability':None,'termination':termination,'release_evidence':release,
                   'contact_evidence':{'start_frame':contact[0]['frame_id'],'start_sec':contact[0]['t_sec'],'dog_id':contact[0]['dog_id'],
                                       'observed_samples':len([p for p in contact if p['t_sec']<=end]),'mouth_localized':False} if contact else None,
                   'carry_evidence':carry,'ground_evidence':ground,'identity_links':relevant_links,
                   'observation_sources':dict(Counter(p['measurement_source'] for p in observations)),
                   'review_start_sec':max(frames[0]['t_sec'],start_record['t_sec']-1),
                   'review_end_sec':min(frames[-1]['t_sec'],end+1),'uncertainty_reasons':reasons}
            events.append(event);completed=event
            if contact:blocked_until=end
    events.sort(key=lambda e:(e['start_sec'],e['disc_ids']))
    ledger=[{'frame_id':r['frame_id'],'t_sec':r['t_sec'],'pts_sec':r['pts_sec'],'events':[]} for r in frames]
    for i,e in enumerate(events):
        e['throw_id']=f'throw-{i+1:03d}'
        for row,source in zip(ledger,frames):
            if not e['start_frame']<=row['frame_id']<=e['end_frame']:continue
            obs=[d for d in source['discs'] if d['disc_id'] in e['disc_ids'] and d['bbox'] is not None]
            phase='flight_candidate'
            if not obs:phase='unobserved'
            elif e['release_evidence'] and row['t_sec']<e['release_evidence']['departure_sec']:phase='ready'
            elif e['ground_evidence'] and row['t_sec']>=e['ground_evidence']['ground_sec']:phase='ground_candidate'
            elif e['carry_evidence'] and row['t_sec']>=e['carry_evidence']['end_sec']:phase='carrying_candidate'
            elif e['contact_evidence'] and row['t_sec']>=e['contact_evidence']['start_sec']:phase='contact_pending'
            elif any(d['approaching'] for d in obs):phase='approaching_dog'
            row['events'].append({'throw_id':e['throw_id'],'phase':phase,'disc_observed':bool(obs),
                                  'dog_observed':source['dog']['bbox'] is not None,'predicted_outcome':e['predicted_outcome']})
    metrics={'processed_frames':len(frames),'episode_candidates':len(events),'outcome_candidates':dict(Counter(e['predicted_outcome'] for e in events)),
             'motion_segments_attached':sum(e['motion_segments']-1 for e in events),'suppressed_motion_candidates':len(excluded),
             'identity_link_candidates':len(links),'accepted_identity_links':sum(p['accepted'] for p in links),
             'confirmed_throws':None,'confirmed_catches':None,'confirmed_misses':None,'catch_rate':None}
    return events,ledger,{'metrics':metrics,'identity_links':links,'suppressed_candidates':excluded}
