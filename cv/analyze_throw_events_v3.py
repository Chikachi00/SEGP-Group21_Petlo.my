"""Independent offline throw-episode analysis, bounded identity links and crop audit."""
import argparse
from dataclasses import asdict
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import quote
import uuid

import cv2
import numpy as np

if __package__:
    from .throw_events_v3 import EventSettings,observed_points,link_proposals,analyze_events
    from .analyze_dog_disc import read_json,read_rows,write_json,sha256
    from .track_dog_video import load_detections
    from .video_tools.media import Toolchain,iter_source_frames
else:
    from throw_events_v3 import EventSettings,observed_points,link_proposals,analyze_events
    from analyze_dog_disc import read_json,read_rows,write_json,sha256
    from track_dog_video import load_detections
    from video_tools.media import Toolchain,iter_source_frames

PROJECT=Path(__file__).resolve().parents[1]


def crop_bounds(box,width,height,context=0.):
    if not isinstance(box,list) or len(box)!=4 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in box):raise ValueError('Invalid crop box')
    x1,y1,x2,y2=box
    if not 0<=x1<x2<=width or not 0<=y1<y2<=height:raise ValueError('Crop box outside display frame')
    dx=(x2-x1)*context;dy=(y2-y1)*context
    return [max(0,math.floor(x1-dx)),max(0,math.floor(y1-dy)),min(width,math.ceil(x2+dx)),min(height,math.ceil(y2+dy))]


def colour_feature(crop):
    if crop.size==0:return None
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    histogram=cv2.calcHist([hsv],[0,1,2],None,[12,4,4],[0,180,0,256,0,256]).reshape(-1)
    total=float(histogram.sum())
    return (histogram/total).astype(float).tolist() if total else None


def validate_joint(root):
    s=read_json(root/'summary.json')
    if s.get('status')!='complete':raise ValueError('Complete joint analysis required')
    for name,digest in s['artifact_sha256'].items():
        p=(root/name).resolve()
        if not p.is_relative_to(root) or sha256(p)!=digest:raise ValueError('Joint analysis artifact changed')
    for path,digest in s['provenance']['inputs'].items():
        if sha256(path)!=digest:raise ValueError('Joint analysis input provenance changed')
    return s,read_rows(root/'joint-states.jsonl')


def validate_ground(path,video,points):
    if path is None:return []
    data=read_json(path)
    if data.get('video_id')!=video['id'] or data.get('source_sha256')!=video['source_sha256']:raise ValueError('Ground annotation source mismatch')
    labels=data.get('ground_contacts')
    if not isinstance(labels,list):raise ValueError('Ground contacts must be a list')
    seen=set()
    for label in labels:
        key=(label.get('frame_id'),label.get('disc_id'))
        if key in seen:raise ValueError('Duplicate ground annotation')
        seen.add(key)
        if label.get('verified') is not True or not isinstance(label.get('reviewer'),str) or not label['reviewer'].strip() or type(label.get('frame_id')) is not int:
            raise ValueError('Ground contact requires reviewer and explicit verified=true')
        if not any(p['frame_id']==label['frame_id'] for p in points.get(label.get('disc_id'),[])):
            raise ValueError('Ground annotation must reference a measured disc/source frame')
    return labels


def make_link_features(video,records,points,proposals,tools,temp):
    requests={}
    for p in proposals:
        for frame_id,identity in ((p['from_frame'],p['from_disc_id']),(p['to_frame'],p['to_disc_id'])):
            if not re.fullmatch(r'[A-Za-z0-9_-]+',identity):raise ValueError('Unsafe disc identifier')
            point=next(o for o in points[identity] if o['frame_id']==frame_id)
            requests.setdefault(frame_id,{})[identity]=point
    if not requests:return {},[]
    selected=[r for r in records if r['frame_id'] in requests]
    folder=temp/'link-audit';folder.mkdir()
    features={};index=[]
    for record,frame in iter_source_frames(Path(video['source']),selected,video['metadata'],tools):
        for identity,point in requests[record['frame_id']].items():
            bounds=crop_bounds(point['bbox'],video['width'],video['height'])
            x1,y1,x2,y2=bounds;crop=frame[y1:y2,x1:x2]
            feature=colour_feature(crop)
            if feature is not None:features[(record['frame_id'],identity)]=feature
            name=f'{identity}-frame-{record["frame_id"]:06d}.jpg'
            if not cv2.imwrite(str(folder/name),crop):raise RuntimeError('Cannot save link evidence')
            index.append({**record,'disc_id':identity,'measurement_source':point['measurement_source'],
                          'file':f'link-audit/{name}','crop_xyxy':bounds,'original_size':[video['width'],video['height']],
                          'coordinate_mapping':'Original pixels = crop pixels + crop_xyxy top-left; no resize.'})
    return features,index


def make_contact_crops(video,records,frames,events,tools,temp):
    requests={}
    by_id={r['frame_id']:r for r in frames}
    for event in events:
        contact=event['contact_evidence']
        if not contact:continue
        start=contact['start_sec']-.25;end=min(event['end_sec'],contact['start_sec']+.6)
        candidates=[r for r in records if start<=r['t_sec']<=end and by_id[r['frame_id']]['dog']['bbox'] is not None]
        if not candidates:continue
        indices=sorted({round(i*(len(candidates)-1)/min(7,len(candidates)-1)) for i in range(min(8,len(candidates)))}) if len(candidates)>1 else [0]
        for i in indices:requests.setdefault(candidates[i]['frame_id'],[]).append(event)
    if not requests:return []
    selected=[r for r in records if r['frame_id'] in requests]
    folder=temp/'contact-crops';folder.mkdir();index=[]
    for record,frame in iter_source_frames(Path(video['source']),selected,video['metadata'],tools):
        state=by_id[record['frame_id']]
        for event in requests[record['frame_id']]:
            # Use only this frame's measured dog/disc boxes; no prediction crop centers.
            dog=state['dog']['bbox'];bounds=crop_bounds(dog,video['width'],video['height'],.25)
            for d in state['discs']:
                if d['disc_id'] in event['disc_ids'] and d['bbox'] is not None:
                    disc_bounds=crop_bounds(d['bbox'],video['width'],video['height'],.25)
                    bounds=[min(bounds[0],disc_bounds[0]),min(bounds[1],disc_bounds[1]),max(bounds[2],disc_bounds[2]),max(bounds[3],disc_bounds[3])]
            x1,y1,x2,y2=bounds
            name=f'{event["throw_id"]}-frame-{record["frame_id"]:06d}.jpg'
            panorama_name=f'{event["throw_id"]}-frame-{record["frame_id"]:06d}-full.jpg'
            if not cv2.imwrite(str(folder/name),frame[y1:y2,x1:x2]):raise RuntimeError('Cannot save native contact crop')
            scale=min(1,1280/max(frame.shape[:2]));overview=cv2.resize(frame,(round(frame.shape[1]*scale),round(frame.shape[0]*scale)))
            cv2.rectangle(overview,(round(x1*scale),round(y1*scale)),(round(x2*scale),round(y2*scale)),(30,210,255),2)
            cv2.putText(overview,f'{event["throw_id"]} | frame {record["frame_id"]} | source {record["t_sec"]:.6f}s',(10,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(30,210,255),1)
            if not cv2.imwrite(str(folder/panorama_name),overview):raise RuntimeError('Cannot save crop parent overview')
            index.append({**record,'throw_id':event['throw_id'],'file':f'contact-crops/{name}','parent_file':f'contact-crops/{panorama_name}',
                          'crop_xyxy':bounds,'original_size':[video['width'],video['height']],'crop_size':[x2-x1,y2-y1],
                          'parent_scale':scale,'dog_state':'detected','disc_ids':event['disc_ids'],
                          'coordinate_mapping':'Original pixels = native crop pixels + crop_xyxy top-left.'})
    return index


def run(joint_dir,detections,pack,output_dir,preview,settings=None,ground_path=None,ffmpeg_dir=None):
    started=time.perf_counter();cfg=settings or EventSettings()
    joint,detections,pack,output,preview=map(lambda p:Path(p).resolve(),(joint_dir,detections,pack,output_dir,preview))
    ground_path=Path(ground_path).resolve() if ground_path else None
    s,frames=validate_joint(joint)
    video,records,detector_rows,_=load_detections(detections,pack)
    if video['id']!=s['video_id'] or video['source_sha256']!=s['provenance']['source_sha256']:raise ValueError('Joint/detector source mismatch')
    if s['metrics']['processed_frames']!=video['frames_count'] or len(frames)!=len(records):raise ValueError('Full video coverage required')
    for row,record in zip(frames,records):
        if any(row.get(k)!=record[k] for k in ('frame_id','t_sec','pts_sec')):raise ValueError('Joint/index source mismatch')
    tracking_summaries=[read_json(p) for p in s['provenance']['inputs'] if p.endswith('summary.json')]
    if not tracking_summaries or any(sha256(detections)!=item['provenance']['detections_sha256'] for item in tracking_summaries):
        raise ValueError('Detector file differs from joint input')
    protected=[joint,pack,Path(video['source']).resolve().parent,PROJECT/'sources',PROJECT/'cv',PROJECT/'docs',PROJECT/'tests',
               PROJECT/'outputs'/'dog-tracking',PROJECT/'outputs'/'disc-tracking',PROJECT/'outputs'/'disc-tracking-v2',PROJECT/'outputs'/'joint-previews']
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected) or any(p.is_relative_to(output) for p in (detections,preview)):
        raise ValueError('Choose an independent event output directory')
    preview_report=read_json(preview.with_suffix('.json'))
    if preview_report.get('status')!='complete' or preview_report['signature']['source_sha256']!=video['source_sha256'] or preview_report['signature']['source_frames']!=len(records) or preview_report['sha256']!=sha256(preview):
        raise ValueError('Verified clean source preview required')
    points=observed_points(frames,detector_rows)
    labels=validate_ground(ground_path,video,points)
    tools=Toolchain.discover(ffmpeg_dir)
    names=['throw_events_v3.py','analyze_throw_events_v3.py','joint_analysis.py','analyze_dog_disc.py','track_dog_video.py','dog_tracker.py','detect_disc_video.py','video_tools/media.py','video_tools/review.py']
    inputs=[joint/'summary.json',joint/'joint-states.jsonl',detections,detections.with_suffix('.json'),pack/'manifest.json',pack/video['paths']['frame_index'],preview,preview.with_suffix('.json')]
    if ground_path:inputs.append(ground_path)
    signature={'schema_version':3,'video_id':video['id'],'source_sha256':video['source_sha256'],'settings':asdict(cfg),'camera':video['camera'],
               'toolchain':tools.version,'opencv':cv2.__version__,'inputs':{str(p):sha256(p) for p in inputs},
               'code':{n:sha256(Path(__file__).parent/n) for n in names},'output_dir':str(output)}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    if output.exists():
        cached=read_json(output/'summary.json')
        artifacts=cached.get('artifact_sha256',{})
        if cached.get('status')!='complete' or cached.get('cache_key')!=key or not {'events-v3.json','event-states.jsonl','index.html','crop-index.json'}.issubset(artifacts):raise ValueError('Existing event output differs; choose a new directory')
        for name,digest in artifacts.items():
            target=(output/name).resolve()
            if not target.is_relative_to(output) or sha256(target)!=digest:raise ValueError('Event cache modified; choose a new directory')
        print(f'Verified throw-event cache: {output}',flush=True);return cached
    output.parent.mkdir(parents=True,exist_ok=True);temp=output.parent/f'.throw-{uuid.uuid4().hex}';temp.mkdir()
    try:
        proposals=link_proposals(points,video['width'],video['height'],video['camera'],cfg)
        print(f'{video["id"]}: {len(proposals)} geometric identity-link proposals; reading actual endpoint crops',flush=True)
        features,link_images=make_link_features(video,records,points,proposals,tools,temp)
        events,ledger,diagnostics=analyze_events(frames,detector_rows,video['width'],video['height'],video['camera'],cfg,features,labels)
        print(f'{video["id"]}: {len(events)} episode candidates; preparing bounded contact crops',flush=True)
        crop_index=make_contact_crops(video,records,frames,events,tools,temp)
        write_json(temp/'events-v3.json',{'schema_version':3,'video_id':video['id'],'event_candidates':events,'confirmed_results_available':False})
        (temp/'event-states.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in ledger),encoding='utf-8')
        write_json(temp/'diagnostics.json',diagnostics)
        write_json(temp/'crop-index.json',{'video_id':video['id'],'link_endpoint_images':link_images,'contact_images':crop_index,
                   'model_reading_rule':'Inspect one throw window at a time, at most 8 independent images per batch. Native crops are not labels.'})
        write_json(temp/'manual-review-template.json',{'video_id':video['id'],'source_sha256':video['source_sha256'],
                   'instructions':'Copy before editing. Predicted outcomes are unverified; retain uncertain when evidence is insufficient. No automatic review import in this version.',
                   'reviews':[{'throw_id':e['throw_id'],'review_status':'unreviewed','confirmed_throw':None,'verified_outcome':None,
                               'allowed_outcomes':['catch','ground_pickup','miss','uncertain','false_candidate'],'reviewer':None,'evidence_frames':[],'notes':''} for e in events]})
        write_json(temp/'ground-contact-template.json',{'video_id':video['id'],'source_sha256':video['source_sha256'],'ground_contacts':[],
                   'example_only':{'disc_id':'disc-XXX','frame_id':0,'verified':True,'reviewer':'REPLACE_WITH_REVIEWER','notes':'Observed ground contact on this original frame; example is not used.'}})
        (temp/'index.html').write_text(review_page(video,frames,ledger,events,crop_index,preview,output),encoding='utf-8')
        if any(sha256(p)!=h for p,h in signature['inputs'].items()) or sha256(video['source'])!=video['source_sha256']:raise ValueError('Input changed during event analysis')
        summary={'status':'complete','video_id':video['id'],'cache_key':key,'provenance':signature,**diagnostics['metrics'],
                 'processing_seconds':time.perf_counter()-started,'contact_crop_frames':len(crop_index),
                 'validated':{'full_source_frame_alignment':True,'source_content_unchanged':True,'predictions_excluded':True,'native_crop_coordinate_mapping':True},
                 'limitations':['throw_id identifies a review episode, not a verified physical throw. Counts are not precision/recall.',
                    'Catch candidate uses 2D proximity and co-motion; mouth contact is not localized. Retrieval can look similar.',
                    'Miss candidates require explicit reviewed ground frames plus subsequent stillness/separation; missing boxes never imply a miss.',
                    'Bounded unique geometry/colour identity links can be wrong; every link remains a review candidate.',
                    'Handheld lacks camera compensation: outcomes remain uncertain and cross-ID links are disabled.',
                    'The review is offline: episode outcomes are retrospective, not real-time alerts.',
                    'Different cameras may record one physical throw; do not sum or split them independently.']}
        summary['artifact_sha256']={p.relative_to(temp).as_posix():sha256(p) for p in temp.rglob('*') if p.is_file()}
        write_json(temp/'summary.json',summary);temp.rename(output)
        print(json.dumps({'output':str(output),'episodes':len(events),'outcomes':summary['outcome_candidates'],'links':summary['accepted_identity_links']}),flush=True)
        return summary
    finally:
        if temp.exists():
            if temp.resolve().parent!=output.parent or not temp.name.startswith('.throw-'):raise RuntimeError('Unsafe staging cleanup')
            for p in sorted(temp.rglob('*'),key=lambda p:len(p.parts),reverse=True):
                if not p.resolve().is_relative_to(temp.resolve()):raise RuntimeError('Unsafe staging child')
                if p.is_dir():p.rmdir()
                else:p.unlink()
            temp.rmdir()


def review_page(video,frames,ledger,events,crops,preview,output):
    src=quote(os.path.relpath(preview,output).replace('\\','/'),safe='/.:')
    buttons=''.join(f'<button data-event="{i}">{e["throw_id"]} | {e["start_sec"]:.3f}–{e["end_sec"]:.3f}s | {html.escape(e["predicted_outcome"])}</button>' for i,e in enumerate(events))
    payload={'fps':video['metadata']['avg_frame_rate'],'width':video['width'],'height':video['height'],'frames':frames,'ledger':ledger,'events':events,'crops':crops}
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Throw Event Review v3</title>
<style>body{font:16px system-ui;max-width:1100px;margin:28px auto;padding:0 20px;background:#f5f6f8;color:#20242b}p{line-height:1.6}.player{position:relative;aspect-ratio:WIDTH/HEIGHT;background:#111}.player video,.player canvas{position:absolute;inset:0;width:100%;height:100%}.player canvas{pointer-events:none}button{padding:10px;margin:8px 0;display:block}input[type=range]{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:18px}a{color:#075fc0}.crops{display:flex;flex-wrap:wrap;gap:12px}.crops a{max-width:240px}.crops img{width:220px;max-height:220px;object-fit:contain;background:#ddd}</style>
<h1>Throw Event Review v3 · VIDEO</h1><p>Episode IDs associate observed motion, approach and contact evidence. All outcomes are unreviewed candidates. Missing observations never establish a catch or miss. Catch candidates do not prove mouth contact. Handheld outcomes remain uncertain.</p>
<div class="player"><video controls preload="metadata" src="SRC"></video><canvas></canvas></div>
<p><label><input id="pred" type="checkbox">Show predictions</label> <label><input id="all" type="checkbox" checked>Show all discs</label></p><button id="step">Next source frame</button><input id="frame" aria-label="Source frame" type="range" min="0" max="MAX" value="0"><p id="clock"></p>
<h2>Episode candidates</h2><p>Choose one episode to inspect its evidence and native contact crops. Predictions are excluded from event evidence. Outcomes shown on the replay are retrospective candidates.</p>BUTTONS
<pre id="event">Select an episode. No candidate does not mean no real throw.</pre><h2>Contact crops</h2><p>Open at most eight independent images per review batch. Crop coordinates and source timestamps are in crop-index.json; each crop links to its full-frame reference.</p><div class="crops"></div>
<p><a href="events-v3.json">Events v3</a> · <a href="event-states.jsonl">Source-frame episode states</a> · <a href="diagnostics.json">Identity links and suppressed motion</a> · <a href="crop-index.json">Crop mappings</a> · <a href="manual-review-template.json">Manual review template</a> · <a href="ground-contact-template.json">Ground evidence template</a> · <a href="summary.json">Run summary</a></p>
<script>const data=PAYLOAD,v=document.querySelector('video'),c=document.querySelector('canvas'),ctx=c.getContext('2d'),slider=document.getElementById('frame'),pred=document.getElementById('pred'),all=document.getElementById('all');c.width=data.width;c.height=data.height;let selected=null,pending=null;const names={ready:'Ready',flight_candidate:'Flight candidate',approaching_dog:'Approaching dog',contact_pending:'Contact pending',carrying_candidate:'Carry candidate',ground_candidate:'Ground candidate',unobserved:'Unobserved'};
function box(b,color,text,dash=false){if(!b)return;ctx.strokeStyle=color;ctx.lineWidth=Math.max(2,data.width/600);ctx.setLineDash(dash?[12,8]:[]);ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.setLineDash([]);ctx.fillStyle=color;ctx.font=`${Math.max(16,data.width/95)}px sans-serif`;ctx.fillText(text,b[0],Math.max(30,b[1]-8));}
function draw(i){i=Math.max(0,Math.min(data.frames.length-1,i));slider.value=i;const f=data.frames[i],r=data.ledger[i];ctx.clearRect(0,0,c.width,c.height);box(f.dog.bbox,'#50ed65',f.dog.track_id||'Dog');if(pred.checked)box(f.dog.prediction_bbox,'#ffe04b','Dog prediction',true);for(const d of f.discs){if(!all.checked&&selected&&!selected.disc_ids.includes(d.disc_id))continue;box(d.bbox,'#35cafa',`${d.disc_id}${d.measurement_source==='local_visual'?' VISUAL':''}`);if(pred.checked)box(d.prediction_bbox,'#ffe04b',`${d.disc_id} Prediction`,true);}const active=r.events.filter(e=>!selected||e.throw_id===selected.throw_id);ctx.fillStyle='#151a1edc';ctx.fillRect(0,0,c.width,Math.max(42,data.width/40));ctx.fillStyle='white';ctx.font=`${Math.max(16,data.width/100)}px sans-serif`;ctx.fillText(active.map(e=>`${e.throw_id}: ${names[e.phase]} | ${e.predicted_outcome}`).join(' / ')||'No active episode candidate',12,Math.max(28,data.width/65));document.getElementById('clock').textContent=`Source frame ${f.frame_id} | Source time ${f.t_sec.toFixed(6)}s | Dog observed: ${!!f.dog.bbox}`;}
function seek(i){draw(i);if(v.readyState===0)pending=i;else v.currentTime=(i+.5)/data.fps;}v.addEventListener('loadedmetadata',()=>{if(pending!==null){const i=pending;pending=null;seek(i);}});['timeupdate','seeked'].forEach(e=>v.addEventListener(e,()=>draw(Math.floor(v.currentTime*data.fps+1e-6))));slider.addEventListener('input',()=>{v.pause();seek(Number(slider.value));});pred.addEventListener('change',()=>draw(Number(slider.value)));all.addEventListener('change',()=>draw(Number(slider.value)));document.getElementById('step').addEventListener('click',()=>{v.pause();seek(Math.min(data.frames.length-1,Number(slider.value)+1));});
document.querySelectorAll('[data-event]').forEach(b=>b.addEventListener('click',()=>{selected=data.events[Number(b.dataset.event)];document.getElementById('event').textContent=JSON.stringify(selected,null,2);const pane=document.querySelector('.crops');pane.replaceChildren();for(const p of data.crops.filter(p=>p.throw_id===selected.throw_id)){const a=document.createElement('a'),img=document.createElement('img'),parent=document.createElement('a');a.href=p.file;img.src=p.file;img.alt=`${p.throw_id} source frame ${p.frame_id}`;a.append(img,document.createTextNode(`Frame ${p.frame_id}, ${p.t_sec.toFixed(3)}s`));parent.href=p.parent_file;parent.textContent='Full-frame reference';const card=document.createElement('div');card.append(a,document.createElement('br'),parent);pane.append(card);}v.pause();seek(data.frames.findIndex(f=>f.t_sec>=selected.review_start_sec));}));draw(0);</script></html>'''
    for marker,value in [('WIDTH',str(video['width'])),('HEIGHT',str(video['height'])),('VIDEO',html.escape(video['id'])),('SRC',html.escape(src,quote=True)),('MAX',str(len(frames)-1)),('BUTTONS',buttons),('PAYLOAD',json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<','\\u003c'))]:page=page.replace(marker,value)
    return page


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--joint-dir',type=Path,required=True)
    parser.add_argument('--detections',type=Path,required=True)
    parser.add_argument('--pack',type=Path,default=PROJECT/'outputs'/'video-analysis-pack')
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--preview',type=Path,required=True)
    parser.add_argument('--ground-evidence',type=Path)
    parser.add_argument('--ffmpeg-dir',type=Path)
    args=parser.parse_args()
    try:run(args.joint_dir,args.detections,args.pack,args.output_dir,args.preview,ground_path=args.ground_evidence,ffmpeg_dir=args.ffmpeg_dir)
    except (ValueError,OSError,RuntimeError,KeyError,StopIteration) as exc:parser.exit(1,f'Throw-event analysis failed: {exc}\n')


if __name__=='__main__':main()
