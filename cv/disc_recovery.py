"""Bounded local observations for discs missed by the saved detector.

Model detections and colour-component tracking are separate measurement sources.
Predictions never create or refresh an appearance template. No gap interpolation.
"""
from dataclasses import dataclass, asdict
import math
import cv2
import numpy as np

if __package__:
    from .disc_tracker import DiscTracker, DiscSettings, center, finite
    from .detect_disc_video import convert_boxes
else:
    from disc_tracker import DiscTracker, DiscSettings, center, finite
    from detect_disc_video import convert_boxes


@dataclass(frozen=True)
class RecoverySettings:
    max_visual_sec: float = .8
    roi_model_interval_sec: float = .15
    roi_imgsz: int = 640
    hue_tolerance: float = 9.
    min_motion_box_diagonals: float = .8
    min_history: int = 4
    max_queries_per_frame: int = 2

    def __post_init__(self):
        for name in ('roi_imgsz','min_history','max_queries_per_frame'):
            if type(getattr(self,name)) is not int or getattr(self,name) < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.roi_imgsz < 32 or self.min_history < 2:
            raise ValueError('Image size >= 32 and history >= 2 required')
        for name,value in asdict(self).items():
            if name not in ('roi_imgsz','min_history','max_queries_per_frame') and (not finite(value) or value <= 0):
                raise ValueError(f'{name} must be finite and positive')
        if self.max_visual_sec > 1. or self.hue_tolerance > 15:
            raise ValueError('Local recovery must remain bounded: <= 1 second and <= 15 hue units')


def hue_mask(hsv, hue, tolerance, saturation, value):
    difference = np.abs(hsv[:,:,0].astype(float)-hue)
    difference = np.minimum(difference,180-difference)
    return ((difference <= tolerance) & (hsv[:,:,1] >= saturation) & (hsv[:,:,2] >= value)).astype(np.uint8)


def seed_profile(frame, box, tolerance):
    x1,y1,x2,y2 = [int(v) for v in box]
    x2,y2 = max(x1+1,x2),max(y1+1,y2)
    hsv = cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
    usable = (hsv[:,:,1] >= 45) & (hsv[:,:,2] >= 50)
    if usable.mean() < .2:
        return None
    histogram = np.bincount((hsv[:,:,0][usable]//5).flatten(),minlength=36)
    hue = float(np.argmax(histogram)*5+2)
    foreground = hue_mask(hsv,hue,tolerance,35,50)
    if foreground.mean() < .25 or foreground.sum() < 12:
        return None
    saturation = max(30.,float(np.median(hsv[:,:,1][foreground!=0]))*.55)
    value = max(45.,float(np.median(hsv[:,:,2][foreground!=0]))*.55)
    foreground = hue_mask(hsv,hue,tolerance,saturation,value)
    height,width = frame.shape[:2]
    padding = max(5,round(max(x2-x1,y2-y1)*.5))
    rx1,ry1,rx2,ry2 = max(0,x1-padding),max(0,y1-padding),min(width,x2+padding),min(height,y2+padding)
    surrounding = cv2.cvtColor(frame[ry1:ry2,rx1:rx2],cv2.COLOR_BGR2HSV)
    ring = np.ones(surrounding.shape[:2],dtype=bool)
    ring[y1-ry1:y2-ry1,x1-rx1:x2-rx1] = False
    background_fraction = hue_mask(surrounding,hue,tolerance,saturation,value)[ring].mean() if ring.any() else 0.
    if foreground.mean() < 2*background_fraction+.15:
        return None
    return {'hue':hue,'saturation':saturation,'value':value,'area':int(foreground.sum()),'box_area':(x2-x1)*(y2-y1)}


class RecoveryTracker:
    def __init__(self,width,height,settings=None,recovery=None,model=None,names=None):
        self.base = DiscTracker(width,height,settings or DiscSettings())
        self.recovery = recovery or RecoverySettings()
        self.model,self.names = model,names
        self.anchors = {}
        self.histories = {}
        self.last_query = {}
        self.counts = {'roi_queries':0,'colour_candidates':0,'roi_model_candidates':0,'colour_accepted':0,'roi_model_accepted':0}

    @property
    def track_count(self): return self.base.track_count

    def _moving(self,track):
        history = self.histories.get(track.track_id,[])
        if len(history) < self.recovery.min_history:
            return False
        size = math.hypot(track.box[2]-track.box[0],track.box[3]-track.box[1])
        return math.dist(history[0][1],history[-1][1]) >= size*self.recovery.min_motion_box_diagonals

    def _roi(self,track,now):
        dt = now-track.last_time
        c = [p+v*dt for p,v in zip(center(track.box),track.velocity)]
        # Search grows with elapsed time but never becomes a whole-frame search.
        extent = max(track.box[2]-track.box[0],track.box[3]-track.box[1])
        radius = min(self.base.diagonal*.09,max(48.,extent*2.5)+self.base.diagonal*dt*.12)
        x1,y1 = max(0,math.floor(c[0]-radius)),max(0,math.floor(c[1]-radius))
        x2,y2 = min(self.base.width,math.ceil(c[0]+radius)),min(self.base.height,math.ceil(c[1]+radius))
        return [x1,y1,x2,y2] if x2>x1 and y2>y1 else None

    def _colour_candidate(self,frame,track,anchor,roi,now):
        x1,y1,x2,y2 = roi
        hsv = cv2.cvtColor(frame[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        p = anchor['profile']
        mask = hue_mask(hsv,p['hue'],self.recovery.hue_tolerance,p['saturation'],p['value'])
        _,_,stats,_ = cv2.connectedComponentsWithStats(mask,8)
        candidates = []
        for x,y,w,h,area in stats[1:]:
            if min(w,h) < 2 or w < 6 or not .20*p['area'] <= area <= 4*p['area']:
                continue
            if area/(w*h) < .35 or not .12 <= (w*h)/p['box_area'] <= 5:
                continue
            # Cut components and coloured background patches are not observations.
            if x<=0 or y<=0 or x+w>=x2-x1 or y+h>=y2-y1 or w/h > 14 or h/w > 4:
                continue
            detection = {'label':'disc','bbox':[float(x1+x),float(y1+y),float(x1+x+w),float(y1+y+h)],
                         'confidence':self.base.settings.confidence,'origin':'local_visual',
                         'recovery_target_id':track.track_id,'visual_fill_fraction':float(area/(w*h))}
            cost = self.base._cost(track,detection,now)
            if cost is not None:
                candidates.append((cost,detection))
        candidates.sort(key=lambda item:item[0])
        # Require a unique compatible component; do not simply select the bluest pixel.
        if len(candidates)!=1:
            return None
        return candidates[0][1]

    def update(self,now,detections,frame):
        if frame.shape[:2] != (self.base.height,self.base.width):
            raise ValueError('Recovery frame must use oriented source dimensions')
        if not finite(now) or now<0 or self.base.previous_time is not None and now<=self.base.previous_time:
            raise ValueError('Source times must be strictly increasing')
        self.base._candidates(detections)  # Validate before touching state or model.
        enhanced = [dict(d) for d in detections]
        diagnostics = []
        queries = 0
        for track in self.base.tracks:
            if not track.track_id or now-track.last_time > self.base.settings.identity_gap_sec:
                continue
            raw_discs = [d for d in detections if d.get('label')=='disc' and d['confidence']>=self.base.settings.confidence]
            if any(self.base._cost(track,d,now) is not None for d in raw_discs) or not self._moving(track):
                continue
            anchor = self.anchors.get(track.track_id)
            if not anchor or now-anchor['time'] > self.recovery.max_visual_sec:
                continue
            roi = self._roi(track,now)
            if roi is None: continue
            recovered = self._colour_candidate(frame,track,anchor,roi,now) if anchor['profile'] else None
            if recovered:
                self.counts['colour_candidates'] += 1
            elif self.model is not None and queries<self.recovery.max_queries_per_frame and now-self.last_query.get(track.track_id,-math.inf)>=self.recovery.roi_model_interval_sec:
                x1,y1,x2,y2=roi
                classes=[i for i,name in self.names.items() if name.lower()=='frisbee']
                prediction=self.model.predict(source=frame[y1:y2,x1:x2],imgsz=self.recovery.roi_imgsz,
                    conf=self.base.settings.confidence,classes=classes,device='cpu',verbose=False)[0]
                compatible=[]
                for d in convert_boxes(prediction,self.names,(self.base.width,self.base.height),(x1,y1),'local_yolo'):
                    d={'label':'disc','bbox':d.bbox,'confidence':d.confidence,'origin':'local_yolo','recovery_target_id':track.track_id}
                    if self.base._cost(track,d,now) is not None: compatible.append(d)
                if len(compatible)==1: recovered=compatible[0]
                self.last_query[track.track_id]=now
                self.counts['roi_queries']+=1
                self.counts['roi_model_candidates']+=len(compatible)
                queries+=1
            # A recovery candidate must belong to this gate alone. The shared
            # associator drops provenance metadata, so reject competing gates
            # before submission instead of letting visual evidence migrate IDs.
            if recovered and any(t.serial!=track.serial and self.base._cost(t,recovered,now) is not None for t in self.base.tracks):
                recovered=None
            diagnostics.append({'track_id':track.track_id,'roi_xyxy':roi,'anchor_age_sec':now-anchor['time'],
                                'candidate':recovered,'accepted':False})
            if recovered: enhanced.append(recovered)
        previous_motion={t.track_id:(list(t.velocity),t.last_time,t.missing) for t in self.base.tracks if t.track_id}
        state=self.base.update(now,enhanced)
        for observation in state['tracks']:
            observation['measurement_source']=None
            if not observation['bbox']: continue
            matches=[d for d in enhanced if d['label']=='disc' and d['bbox']==observation['bbox']]
            origin=matches[0].get('origin','saved_detector') if matches else 'saved_detector'
            source=origin if origin in ('local_visual','local_yolo') else 'saved_detector'
            observation['measurement_source']=source
            identity=observation['track_id']
            before=previous_motion.get(identity)
            active_track=next(t for t in self.base.tracks if t.track_id==identity)
            suspicious_velocity_jump=before and math.hypot(*active_track.velocity)>max(2*math.hypot(*before[0]),.5*self.base.diagonal)
            if before and before[2] and now-before[1]>self.base.settings.prediction_sec and suspicious_velocity_jump:
                # Displacement across a long unobserved interval is not current
                # velocity. Keep the pre-gap estimate until fresh consecutive
                # observations can update it; otherwise reacquisition can cause
                # a large one-frame extrapolation and immediately lose the ID.
                active_track.velocity=before[0]
                observation['velocity_update_held_after_gap']=True
            history=self.histories.setdefault(identity,[])
            history.append((now,center(observation['bbox'])))
            history[:]=[(t,c) for t,c in history if now-t<=.2]
            if source=='local_visual':
                observation['confidence']=None  # Colour scores are not YOLO confidence.
                self.counts['colour_accepted']+=1
            else:
                self.anchors[identity]={'time':now,'profile':seed_profile(frame,observation['bbox'],self.recovery.hue_tolerance)}
                if source=='local_yolo': self.counts['roi_model_accepted']+=1
            for d in diagnostics:
                if d['track_id']==identity and d['candidate'] and d['candidate']['bbox']==observation['bbox']:
                    d['accepted']=True
        active={t.track_id for t in self.base.tracks if t.track_id}
        for mapping in (self.anchors,self.histories,self.last_query):
            for key in list(mapping):
                if key not in active: del mapping[key]
        return {**state,'recovery':diagnostics}
