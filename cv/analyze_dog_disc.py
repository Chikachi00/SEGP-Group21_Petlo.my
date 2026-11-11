"""Align complete saved dog/disc-v2 observations and build an offline joint review."""
import argparse
from dataclasses import asdict
import hashlib
import html
import json
import os
from pathlib import Path
import time
from urllib.parse import quote
import uuid

if __package__:
    from .joint_analysis import JointSettings, analyze
else:
    from joint_analysis import JointSettings, analyze

PROJECT=Path(__file__).resolve().parents[1]


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Non-finite JSON')))


def read_rows(path):
    return [json.loads(line,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Non-finite JSON'))) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def write_json(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def checked_run(root):
    summary=read_json(root/'summary.json')
    if summary.get('status')!='complete': raise ValueError('Tracking input is not complete')
    expected=summary.get('artifact_sha256',{}).get('states.jsonl')
    if not expected or sha256(root/'states.jsonl')!=expected: raise ValueError('Tracking states differ from their recorded hash')
    return summary,read_rows(root/'states.jsonl')


def run(dog_dir,disc_dir,pack,output_dir,settings=None,preview=None,*,review=True):
    started=time.perf_counter()
    dog_dir,disc_dir,pack,output=map(lambda p:Path(p).resolve(),(dog_dir,disc_dir,pack,output_dir))
    cfg=settings or JointSettings()
    ds,dogs=checked_run(dog_dir)
    cs,discs=checked_run(disc_dir)
    manifest=read_json(pack/'manifest.json')
    if ds['video_id']!=cs['video_id']: raise ValueError('Dog and disc videos must match')
    video=next((v for v in manifest['videos'] if v['id']==ds['video_id']),None)
    if not video or video['status']!='complete' or video['role']!='action': raise ValueError('Complete action video required')
    source=Path(video['source']).resolve()
    index=(pack/video['paths']['frame_index']).resolve()
    if not index.is_relative_to(pack): raise ValueError('Unsafe frame index path')
    preview=Path(preview).resolve() if preview and review else None
    protected=[dog_dir,disc_dir,pack,source.parent,PROJECT/'sources',PROJECT/'cv',PROJECT/'tests',PROJECT/'docs']
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Use an independent output directory outside existing inputs/code/docs/raw video')
    if preview and (not preview.is_file() or preview.is_relative_to(output)): raise ValueError('Preview must exist outside output directory')
    digest=sha256(source)
    if digest!=video['source_sha256'] or any(s['provenance']['source_sha256']!=digest or Path(s['source']).resolve()!=source for s in (ds,cs)):
        raise ValueError('Source identity/content mismatch')
    if cs['provenance']['display_size']!=[video['width'],video['height']]: raise ValueError('Disc display coordinates mismatch')
    if ds['provenance']['detections_sha256']!=cs['provenance']['detections_sha256']:
        raise ValueError('Dog/disc detections have different provenance')
    for s in (ds,cs):
        if s['processed_frames']!=video['frames_count']: raise ValueError('Full source coverage required; window runs cannot be combined')
    records=read_json(index)
    if len(records)!=video['frames_count']: raise ValueError('Source-index count mismatch')
    inputs=[dog_dir/'summary.json',dog_dir/'states.jsonl',disc_dir/'summary.json',disc_dir/'states.jsonl',pack/'manifest.json',index]
    if preview: inputs.append(preview)
    input_hashes={str(p):sha256(p) for p in inputs}
    signature={'schema_version':1,'source_sha256':digest,'video_id':video['id'],'camera':video['camera'],
               'review':review,
               'settings':asdict(cfg),'display_size':[video['width'],video['height']],'inputs':input_hashes,
               'code':{n:sha256(Path(__file__).with_name(n)) for n in ('joint_analysis.py','analyze_dog_disc.py')}}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    if output.exists():
        summary=read_json(output/'summary.json')
        if summary.get('status')!='complete' or summary.get('cache_key')!=key: raise ValueError('Existing output differs; choose a new output directory')
        artifacts=summary.get('artifact_sha256',{})
        required={'joint-states.jsonl','events.json'}
        if review: required.update(('manual-review-template.json','index.html'))
        if not required.issubset(artifacts): raise ValueError('Invalid output cache manifest')
        for name,value in artifacts.items():
            target=(output/name).resolve()
            if not target.is_relative_to(output) or sha256(target)!=value: raise ValueError('Output cache changed; choose a new directory')
        print(f'Verified joint-analysis cache: {output}',flush=True)
        return summary
    frames,events,metrics=analyze(dogs,discs,records,video['width'],video['height'],video['camera'],cfg)
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.parent/f'.joint-{uuid.uuid4().hex}'
    temp.mkdir()
    try:
        (temp/'joint-states.jsonl').write_text(''.join(json.dumps(f,allow_nan=False)+'\n' for f in frames),encoding='utf-8')
        write_json(temp/'events.json',{'video_id':video['id'],'candidate_events':events,'confirmed_results_available':False})
        if review:
            write_json(temp/'manual-review-template.json',{'video_id':video['id'],'instructions':'Copy this file before editing. These records are manual review only; no statistics are inferred or imported automatically.',
                'reviews':[{'event_id':e['event_id'],'review_status':'unreviewed','confirmed_throw':None,'outcome':'uncertain',
                            'allowed_outcomes':['catch','miss','uncertain','false_candidate'],'reviewer':None,'evidence_frames':[],'notes':''} for e in events]})
            (temp/'index.html').write_text(review_page(video,frames,events,preview,output),encoding='utf-8')
        if any(sha256(p)!=v for p,v in input_hashes.items()) or sha256(source)!=digest:
            raise ValueError('Input changed during joint analysis')
        summary={'status':'complete','video_id':video['id'],'cache_key':key,'provenance':signature,'metrics':metrics,
                 'processing_seconds':time.perf_counter()-started,
                 'validated':{'exact_source_frame_alignment':True,'source_content_unchanged':True,'predictions_excluded_from_evidence':True},
                 'limitations':['Candidates are not verified throws/catches/misses. No accuracy or catch rate without human labels.',
                                'Moving held/ground discs, association errors and camera motion may create false candidates.',
                                'Dog rectangle proximity is not mouth contact; disappearance never proves a catch or miss.',
                                'IDs may fragment: candidate counts are not physical throw counts. Front and side may describe the same throw.',
                                'Local visual boxes can cover only the coloured portion. Pixel motion is not physical speed.',
                                'Handheld has no camera compensation; throw promotion is disabled.',
                                'Replay uses nominal FPS; displayed evidence uses indexed original timestamps.']}
        summary['artifact_sha256']={p.name:sha256(p) for p in temp.iterdir() if p.is_file()}
        write_json(temp/'summary.json',summary)
        temp.rename(output)
    finally:
        # Only remove files generated by this attempt, never inputs/existing outputs.
        if temp.exists():
            if temp.resolve().parent!=output.parent or not temp.name.startswith('.joint-'): raise RuntimeError('Unsafe staging cleanup')
            for p in temp.iterdir():
                if p.is_file(): p.unlink()
            temp.rmdir()
    print(json.dumps({'output':str(output),'frames':len(frames),'candidate_types':metrics['candidate_types']},ensure_ascii=False),flush=True)
    return summary


def review_page(video,frames,events,preview,output):
    payload={'width':video['width'],'height':video['height'],'fps':video['metadata']['avg_frame_rate'],'frames':frames,'events':events}
    labels={'throw_candidate':'疑似投掷','disc_motion_candidate':'飞盘移动候选','contact_candidate':'疑似接触'}
    buttons=''.join(f'<button data-event="{i}">{html.escape(labels[e["type"]])} · {e["start_sec"]:.3f}–{e["end_sec"]:.3f}s · {html.escape(e["disc_id"])}</button>' for i,e in enumerate(events))
    src=quote(os.path.relpath(preview,output).replace('\\','/'),safe='/.:') if preview else ''
    media=f'<div class="player"><video controls preload="metadata" src="{html.escape(src,quote=True)}"></video><canvas></canvas></div>' if preview else '<p>没有连接视频预览；用下面的帧滑块检查源时间与几何结果。</p><canvas class="plain"></canvas>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>狗与飞盘联合分析</title>
<style>body{max-width:1100px;margin:28px auto;padding:0 20px;background:#f5f6f8;color:#20242b;font:16px system-ui}p{line-height:1.6}.player{position:relative;width:100%;aspect-ratio:WIDTH/HEIGHT;background:#111}.player video,.player canvas{position:absolute;width:100%;height:100%;inset:0}.player canvas{pointer-events:none}.plain{width:100%;background:#eee}button{display:block;margin:8px 0;padding:10px;text-align:left}input[type=range]{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:16px}a{color:#075fc0}</style>
<h1>狗与飞盘联合分析 · VIDEO</h1><p>绿框为狗观测，蓝框为飞盘观测，VISUAL 是局部外观观测；勾选后黄色虚框表示预测。预测不会参与距离、移动或事件证据。这里给出候选，所有接盘/失误结果仍为不确定。</p>
<p>距离是二维框间距，无法确认嘴部接触。手持镜头未补偿相机移动。移动飞盘可能在手中或地面；多个候选和 ID 不能直接当作投掷次数。</p>MEDIA
<p><label><input id="pred" type="checkbox">显示预测框</label> <button id="step">下一源帧</button></p><input id="frame" type="range" min="0" max="MAX" value="0" aria-label="源帧"><p id="clock"></p>
<h2>自动候选窗口</h2><p>点选一个窗口回看，并检查候选记录中的证据来源。帧滑块可逐帧定位。源时间显示来自原视频索引。</p>BUTTONS
<pre id="event">请选择候选。没有候选也不代表没有真实事件。</pre><p><a href="events.json">候选记录</a> · <a href="joint-states.jsonl">逐帧联合状态</a> · <a href="manual-review-template.json">人工核查模板（复制后填写）</a> · <a href="summary.json">运行摘要</a></p>
<script>const data=PAYLOAD;const v=document.querySelector('video'),c=document.querySelector('canvas'),ctx=c.getContext('2d'),slider=document.getElementById('frame'),toggle=document.getElementById('pred');c.width=data.width;c.height=data.height;const phases={unobserved:'Unobserved',moving_candidate:'Moving candidate',stationary_or_slow:'Stationary / slow',insufficient_motion_history:'Insufficient motion history',near_dog_candidate:'Near dog',approaching_dog_candidate:'Approaching dog'},dogStates={detected:'Observed',predicted:'Short-term prediction',lost:'Lost',acquiring:'Confirming',searching:'Searching'};
function box(b,color,text,dashed=false){if(!b)return;ctx.strokeStyle=color;ctx.lineWidth=Math.max(2,data.width/600);ctx.setLineDash(dashed?[12,8]:[]);ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.setLineDash([]);ctx.font=`${Math.max(15,data.width/100)}px sans-serif`;ctx.fillStyle=color;ctx.fillText(text,b[0],Math.max(25,b[1]-8));}
function draw(i){i=Math.max(0,Math.min(data.frames.length-1,i));slider.value=i;const f=data.frames[i];ctx.clearRect(0,0,c.width,c.height);box(f.dog.bbox,'#54f16a',f.dog.track_id||'Dog');if(toggle.checked)box(f.dog.prediction_bbox,'#ffe04b','Dog prediction',true);for(const d of f.discs){box(d.bbox,'#36cafa',`${d.disc_id} ${phases[d.phase]||d.phase}${d.measurement_source==='local_visual'?' VISUAL':''}`);if(toggle.checked)box(d.prediction_bbox,'#ffe04b',`${d.disc_id} Prediction`,true);}document.getElementById('clock').textContent=`Source frame ${f.frame_id} · Source time ${f.t_sec.toFixed(6)}s · Dog: ${dogStates[f.dog.state]||f.dog.state} · Joint observation: ${(!!f.dog.bbox&&f.discs.some(d=>d.bbox))?'Yes':'No'}`;}
let pendingFrame=null;function seek(i){draw(i);if(v){if(v.readyState===0)pendingFrame=i;else v.currentTime=(i+.5)/data.fps;}}
slider.addEventListener('input',()=>seek(Number(slider.value)));toggle.addEventListener('change',()=>draw(Number(slider.value)));document.getElementById('step').addEventListener('click',()=>{if(v)v.pause();seek(Math.min(data.frames.length-1,Number(slider.value)+1));});
if(v){v.addEventListener('loadedmetadata',()=>{if(pendingFrame!==null){const i=pendingFrame;pendingFrame=null;seek(i);}});v.addEventListener('timeupdate',()=>draw(Math.floor(v.currentTime*data.fps+1e-6)));v.addEventListener('seeked',()=>draw(Math.floor(v.currentTime*data.fps+1e-6)));}
document.querySelectorAll('[data-event]').forEach(b=>b.addEventListener('click',()=>{const e=data.events[Number(b.dataset.event)];document.getElementById('event').textContent=JSON.stringify(e,null,2);if(v)v.pause();seek(data.frames.findIndex(f=>f.t_sec>=e.review_start_sec));}));draw(0);</script></html>'''
    for marker,value in [('WIDTH',str(video['width'])),('HEIGHT',str(video['height'])),('VIDEO',html.escape(video['id'])),('MEDIA',media),('MAX',str(len(frames)-1)),('BUTTONS',buttons),('PAYLOAD',json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('<','\\u003c'))]:
        page=page.replace(marker,value)
    return page


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dog-dir',required=True,type=Path)
    parser.add_argument('--disc-dir',required=True,type=Path)
    parser.add_argument('--pack',default=PROJECT/'outputs'/'video-analysis-pack',type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--preview',type=Path)
    parser.add_argument('--no-review',action='store_true',help='Write analysis data without offline HTML or manual review files.')
    args=parser.parse_args()
    try: run(args.dog_dir,args.disc_dir,args.pack,args.output_dir,preview=args.preview,review=not args.no_review)
    except (ValueError,OSError,RuntimeError,KeyError,StopIteration) as exc: parser.exit(1,f'Joint analysis failed: {exc}\n')


if __name__=='__main__': main()
