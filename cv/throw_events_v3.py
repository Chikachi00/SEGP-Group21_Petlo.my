"""V3 event refinements layered on the shared conservative event rules."""
from collections import Counter
import math

if __package__:
    from .joint_analysis import center, diagonal
    from .throw_events import (
        EventSettings, observed_points, velocity, link_proposals, resolve_links,
        groups, person_gap, release_evidence, carry_evidence, ground_evidence,
        analyze_events as _analyze_events_v2,
    )
else:
    from joint_analysis import center, diagonal
    from throw_events import (
        EventSettings, observed_points, velocity, link_proposals, resolve_links,
        groups, person_gap, release_evidence, carry_evidence, ground_evidence,
        analyze_events as _analyze_events_v2,
    )


def _relative_carry(sequence, contact, cfg):
    """Accept stable disc position in the moving dog's box, robust to pose changes."""
    after=[p for p in sequence if contact[0]['t_sec']<=p['t_sec']<=contact[0]['t_sec']+cfg.post_contact_sec]
    for group in groups(after,lambda p:p['dog_id']==contact[0]['dog_id'] and p['dog_bbox'] is not None and p['dog_gap'] is not None and p['dog_gap']<=cfg.near_dog_diagonals,cfg.observation_gap_sec,True):
        anchors=[p for p in group if p['measurement_source'] in ('saved_detector','local_yolo')]
        relative=[]
        for p in anchors:
            b,db=p['bbox'],p['dog_bbox'];w=db[2]-db[0];h=db[3]-db[1]
            if w<=0 or h<=0:relative.append(None)
            else:relative.append((((b[0]+b[2]-db[0]-db[2])*.5)/w,((b[1]+b[3]-db[1]-db[3])*.5)/h))
        # Extend each window's extrema once per anchor instead of rescanning it.
        for left in range(len(anchors)):
            if relative[left] is None:continue
            min_x=max_x=relative[left][0];min_y=max_y=relative[left][1]
            for right in range(left+1,len(anchors)):
                position=relative[right]
                # Every larger window contains this invalid dog box as well.
                if position is None:break
                min_x=min(min_x,position[0]);max_x=max(max_x,position[0])
                min_y=min(min_y,position[1]);max_y=max(max_y,position[1])
                first,last=anchors[left],anchors[right]
                if right<left+2 or last['t_sec']-first['t_sec']<cfg.min_carry_sec-1e-9:continue
                sx=max_x-min_x;sy=max_y-min_y
                if sx>.25 or sy>.65:continue
                scale=diagonal(first['dog_bbox'])
                disc_move=math.dist(center(first['bbox']),center(last['bbox']))
                dog_move=math.dist(center(first['dog_bbox']),center(last['dog_bbox']))
                if min(disc_move,dog_move)<.08*scale:continue
                return {'start_frame':first['frame_id'],'end_frame':last['frame_id'],
                        'start_sec':first['t_sec'],'end_sec':last['t_sec'],'dog_id':first['dog_id'],
                        'observed_samples':right-left+1,'model_observed_samples':right-left+1,
                        'relative_position_x_spread':sx,'relative_position_y_spread':sy,
                        'relative_displacement_px':disc_move-dog_move,
                        'mouth_localized':False,'evidence_type':'disc_stays_in_dog_box_during_motion'}
    return None


def _interception_loss(sequence, frames, cfg):
    """Use a close airborne interception followed by disc loss as a catch candidate."""
    near_groups=groups(sequence,lambda p:p['dog_bbox'] is not None and p['dog_gap'] is not None and p['dog_gap']<=cfg.near_dog_diagonals,
                       max(cfg.observation_gap_sec,.2),True)
    for group in near_groups:
        if len(group)<2 or group[-1]['t_sec']-group[0]['t_sec']<.08-1e-9:continue
        anchors=[p for p in group if p['measurement_source'] in ('saved_detector','local_yolo')]
        if len(anchors)<2 or not any(p['dog_gap']<=1e-9 for p in group):continue
        before=[p for p in sequence if p['t_sec']<group[0]['t_sec'] and p['dog_id']==group[0]['dog_id'] and p['dog_gap'] is not None]
        if not any(p['dog_gap']>=cfg.far_dog_diagonals for p in before):continue
        if not any(p.get('moving') or p.get('approaching') for p in sequence if p['t_sec']<=group[-1]['t_sec']):continue
        last_anchor=anchors[-1]
        later_reliable=[p for p in sequence if p['t_sec']>last_anchor['t_sec']+.08 and p['measurement_source'] in ('saved_detector','local_yolo') and p['dog_bbox'] is not None and p['dog_gap'] is not None and p['dog_gap']>cfg.near_dog_diagonals]
        if later_reliable and later_reliable[0]['t_sec']-last_anchor['t_sec']<.25:continue
        dog_after=[r for r in frames if last_anchor['t_sec']+.08<=r['t_sec']<=last_anchor['t_sec']+.4 and r['dog']['state']=='detected' and r['dog']['bbox'] is not None]
        if len(dog_after)<4:continue
        first,last=dog_after[0]['dog']['bbox'],dog_after[-1]['dog']['bbox']
        if math.dist(center(first),center(last))<.06*diagonal(first):continue
        return {'start_frame':group[0]['frame_id'],'end_frame':anchors[-1]['frame_id'],
                'start_sec':group[0]['t_sec'],'end_sec':anchors[-1]['t_sec'],'dog_id':group[0]['dog_id'],
                'observed_samples':len(group),'model_observed_samples':len(anchors),'direct_box_overlap':True,
                'dog_observed_after_disc_loss':len(dog_after),'mouth_localized':False,
                'evidence_type':'airborne_disc_intersects_dog_then_disc_measurements_stop'}
    return None


def _ground_pickup_candidate(sequence, frames, width, height):
    """Find a descending low disc followed by the measured dog reaching its endpoint."""
    model=[p for p in sequence if p['measurement_source'] in ('saved_detector','local_yolo')]
    if len(model)<5:return None
    last=model[-1]
    tail=[p for p in model if last['t_sec']-.3<=p['t_sec']<=last['t_sec']]
    if len(tail)<4 or tail[-1]['t_sec']-tail[0]['t_sec']<.1:return None
    first_y=(tail[0]['bbox'][1]+tail[0]['bbox'][3])*.5
    last_y=(last['bbox'][1]+last['bbox'][3])*.5
    if last_y/height<.6 or last_y-first_y<.04*height:return None
    target=center(last['bbox'])
    dogs=[r for r in frames if last['t_sec']<r['t_sec']<=last['t_sec']+.8 and r['dog']['state']=='detected' and r['dog']['bbox'] is not None]
    if len(dogs)<4 or last['dog_bbox'] is None:return None
    start_gap=math.dist(center(last['dog_bbox']),target)/diagonal(last['dog_bbox'])
    arrivals=[]
    for r in dogs:
        db=r['dog']['bbox'];gap=math.dist(center(db),target)/diagonal(db)
        if gap<=.25:arrivals.append((r,gap))
    if start_gap<.4 or not arrivals:return None
    arrival,gap=arrivals[0]
    if arrival['t_sec']-last['t_sec']<.05:return None
    return {'last_disc_frame':last['frame_id'],'last_disc_sec':last['t_sec'],'dog_arrival_frame':arrival['frame_id'],
            'dog_arrival_sec':arrival['t_sec'],'last_disc_center_px':target,'dog_arrival_gap_diagonals':gap,
            'disc_descended_px':last_y-first_y,'ground_contact_directly_observed':False,
            'evidence_type':'descending_low_disc_then_dog_reaches_last_observed_location'}


def analyze_events(frames,detections,width,height,camera='tripod',settings=None,appearances=None,ground_contacts=None):
    cfg=settings or EventSettings()
    events,ledger,diagnostics=_analyze_events_v2(frames,detections,width,height,camera,cfg,appearances,ground_contacts)
    points_by_id=observed_points(frames,detections)
    for event in events:
        sequence=sorted((p for disc_id in event['disc_ids'] for p in points_by_id.get(disc_id,[])
                         if event['start_sec']-.25<=p['t_sec']<=event['end_sec']+.8),key=lambda p:p['t_sec'])
        if not sequence:continue
        # Keep v2 carry first, then use a pose-tolerant dog-relative carry check.
        if event['carry_evidence'] is None and camera=='tripod' and event['contact_evidence']:
            event['carry_evidence']=_relative_carry(sequence,[next(p for p in sequence if p['frame_id']==event['contact_evidence']['start_frame'])],cfg)
        intercept=_interception_loss(sequence,frames,cfg) if camera=='tripod' and event['carry_evidence'] is None else None
        if intercept:
            event['catch_evidence']=intercept
            event['predicted_outcome']='catch_candidate'
            event['termination']='interception_then_disc_loss_candidate'
            event['contact_evidence']={'start_frame':intercept['start_frame'],'start_sec':intercept['start_sec'],
                'dog_id':intercept['dog_id'],'observed_samples':intercept['observed_samples'],'mouth_localized':False}
        pickup=_ground_pickup_candidate(sequence,frames,width,height) if camera=='tripod' and event['carry_evidence'] is None and not intercept else None
        if pickup:
            event['pickup_evidence']=pickup
            event['predicted_outcome']='ground_pickup_candidate'
            event['termination']='low_disc_dog_arrival_candidate'
            arrival=next(r for r in frames if r['frame_id']==pickup['dog_arrival_frame'])
            if arrival['t_sec']>event['end_sec']:
                event['end_frame'],event['end_sec']=arrival['frame_id'],arrival['t_sec']
                event['review_end_sec']=min(frames[-1]['t_sec'],arrival['t_sec']+1)
        if event['carry_evidence']:
            event['predicted_outcome']='catch_candidate'
            event['termination']='sustained_dog_relative_disc_candidate'
        if event['predicted_outcome']!='uncertain':
            event['uncertainty_reasons']=[r for r in event['uncertainty_reasons'] if r not in ('contact_unresolved','track_observations_ended','long_observation_gap')]
            if event['predicted_outcome']=='ground_pickup_candidate' and 'ground_contact_not_directly_observed' not in event['uncertainty_reasons']:
                event['uncertainty_reasons'].append('ground_contact_not_directly_observed')
    outcomes=Counter(e['predicted_outcome'] for e in events)
    diagnostics['metrics']['outcome_candidates']=dict(outcomes)
    diagnostics['metrics']['candidate_catches']=outcomes.get('catch_candidate',0)
    diagnostics['metrics']['candidate_ground_pickups']=outcomes.get('ground_pickup_candidate',0)
    diagnostics['metrics']['uncertain_outcomes']=outcomes.get('uncertain',0)
    event_by_id={e['throw_id']:e for e in events}
    source_by_frame={r['frame_id']:r for r in frames}
    for row in ledger:
        for item in row['events']:
            event=event_by_id[item['throw_id']]
            item['predicted_outcome']=event['predicted_outcome']
            if event['carry_evidence'] and row['t_sec']>=event['carry_evidence']['end_sec']:item['phase']='carrying_candidate'
            elif event.get('pickup_evidence') and row['t_sec']>=event['pickup_evidence']['last_disc_sec']:item['phase']='ground_pickup_candidate'
    first_frame=frames[0]['frame_id']
    for event in events:
        for index in range(event['start_frame']-first_frame,event['end_frame']-first_frame+1):
            row=ledger[index]
            if not any(item['throw_id']==event['throw_id'] for item in row['events']):
                source=source_by_frame[row['frame_id']]
                disc_seen=any(d['disc_id'] in event['disc_ids'] and d['bbox'] is not None for d in source['discs'])
                phase='ground_pickup_candidate' if event.get('pickup_evidence') and row['t_sec']>=event['pickup_evidence']['last_disc_sec'] else ('flight_candidate' if disc_seen else 'unobserved')
                row['events'].append({'throw_id':event['throw_id'],'phase':phase,'disc_observed':disc_seen,
                                      'dog_observed':source['dog']['bbox'] is not None,'predicted_outcome':event['predicted_outcome']})
    return events,ledger,diagnostics
