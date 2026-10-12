"""Build a separate offline gallery for existing complete disc tracking runs."""
import argparse
import html
import json
from pathlib import Path
import subprocess
import uuid

if __package__:
    from .track_dog_video import read_json, write_json
    from .detect_disc_video import sha256
    from .video_tools.media import Toolchain
else:
    from track_dog_video import read_json, write_json
    from detect_disc_video import sha256
    from video_tools.media import Toolchain

PROJECT = Path(__file__).resolve().parents[1]


def build(root, ffmpeg_dir=None, run_version='v1'):
    root = Path(root).resolve()
    tools = Toolchain.discover(ffmpeg_dir)
    samples = []
    for slug,title in [('front','正面'),('side','侧面'),('handheld','手持')]:
        run_name = f'{slug}-{run_version}'
        run_dir = root/run_name
        if run_dir.parent != root:
            raise ValueError('Invalid run version')
        summary = read_json(run_dir/'summary.json')
        if summary.get('status') != 'complete':
            raise ValueError(f'Incomplete run: {run_dir}')
        for name,digest in summary['artifact_sha256'].items():
            target = (run_dir/name).resolve()
            if not target.is_relative_to(run_dir) or sha256(target) != digest:
                raise ValueError(f'Changed disc output: {target}')
        states = [json.loads(s) for s in (run_dir/'states.jsonl').read_text(encoding='utf-8').splitlines()]
        if len(states) != summary['processed_frames']:
            raise ValueError('State frame coverage mismatch')
        samples.append({'slug':slug,'title':title,'run_name':run_name,'summary':summary,'frames':states})
    gallery_cache = root/'gallery.json'
    signature = {'run_version':run_version,'runs':{s['slug']:sha256(root/s['run_name']/'summary.json') for s in samples},
                 'builder':sha256(Path(__file__)),'toolchain':tools.version}
    if (root/'index.html').exists() or (root/'all-tracks.jsonl').exists():
        if not gallery_cache.exists():
            raise ValueError('Existing gallery has no provenance; refusing to overwrite')
        cache = read_json(gallery_cache)
        if cache['signature'] != signature:
            raise ValueError('Existing gallery uses different inputs/code; use a new root directory')
        for name,digest in cache['artifact_sha256'].items():
            if sha256(root/name) != digest:
                raise ValueError(f'Gallery changed: {name}')
        print(f'Verified gallery cache: {root}',flush=True)
        return root/'index.html'
    sections, combined = [], []
    for s in samples:
        slug,summary = s['slug'],s['summary']
        preview = root/f'{slug}-preview.mp4'
        preview_cache = preview.with_suffix('.json')
        preview_signature = {'input':sha256(root/s['run_name']/'tracked.mp4'),'toolchain':tools.version,'max_side':1280,'crf':23}
        if preview.exists():
            cache = read_json(preview_cache)
            if cache['signature'] != preview_signature or cache['sha256'] != sha256(preview):
                raise ValueError('Changed preview; refusing to overwrite')
        else:
            pending = root/f'.{slug}-preview-{uuid.uuid4().hex}.mp4'
            command = [tools.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-threads','4','-filter_threads','1',
                       '-i',str(root/s['run_name']/'tracked.mp4'),'-vf',
                       "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                       '-an','-c:v','libx264','-preset','veryfast','-crf','23','-threads','4','-fps_mode','passthrough','-movflags','+faststart',str(pending)]
            try:
                subprocess.run(command,capture_output=True,check=True)
                pending.rename(preview)
            finally:
                if pending.exists(): pending.unlink()
        probe = subprocess.run([tools.ffprobe,'-v','error','-count_frames','-select_streams','v:0','-show_entries',
                                'stream=nb_read_frames,width,height,avg_frame_rate','-of','json',str(preview)],capture_output=True,check=True)
        stream = json.loads(probe.stdout)['streams'][0]
        if int(stream['nb_read_frames']) != summary['processed_frames']:
            raise RuntimeError('Preview frame coverage mismatch')
        numerator,denominator = map(int,stream['avg_frame_rate'].split('/'))
        s['fps'] = numerator/denominator
        s['first_frame'] = s['frames'][0]['frame_id']
        # Image dimensions are available from the validated source-size replay.
        replay_probe = subprocess.run([tools.ffprobe,'-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',
                                       str(root/s['run_name']/'tracked.mp4')],capture_output=True,check=True)
        dim = json.loads(replay_probe.stdout)['streams'][0]
        s['width'],s['height'] = dim['width'],dim['height']
        write_json(preview_cache,{'signature':preview_signature,'sha256':sha256(preview),'frames':summary['processed_frames']})
        combined.append((root/s['run_name']/'tracks.jsonl').read_text(encoding='utf-8'))
        counts = summary['frames_with_state']
        settings = summary['provenance']['settings']
        sections.append(f'''<section><h2>{s['title']}</h2><p>源帧 {summary['processed_frames']} · 至少一个实测盘 {counts['detected']} 帧 · 短轨迹 {summary['track_count']} 条</p><p>预测时限 {settings['prediction_sec']} 秒 · ID 保留时限 {settings['identity_gap_sec']} 秒</p>
<video controls preload="metadata" src="{slug}-preview.mp4"></video><p><a href="{s['run_name']}/tracked.mp4">原尺寸回放</a> · <a href="{s['run_name']}/trajectory.csv">像素轨迹 CSV</a> · <a href="{s['run_name']}/summary.json">运行记录</a></p>
<label>查看轨迹 <select aria-label="飞盘轨迹"><option value="all">全部</option>{''.join(f'<option value="{html.escape(t)}">{html.escape(t)}</option>' for t in summary['tracklets'])}</select></label>
<label><input type="checkbox" checked>显示预测点</label><canvas aria-label="飞盘的像素轨迹"></canvas><p class="clock"></p></section>''')
        print(f'{slug}: full-frame preview verified',flush=True)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>飞盘追踪局部恢复版</title>
<style>body{font:16px system-ui,sans-serif;color:#20242b;background:#f5f6f8;max-width:1080px;margin:32px auto;padding:0 20px}section{background:white;padding:22px;margin:24px 0;border-radius:10px}p{line-height:1.65}video{width:100%;max-height:620px;background:#111}canvas{display:block;width:100%;height:auto;max-height:540px;border:1px solid #ddd;margin-top:14px}a{color:#075fc0}label{margin-right:18px}select{padding:5px}</style>
<h1>飞盘追踪 · 局部恢复版</h1><p><a href="comparison.json">同源帧前后对比</a> · <a href="../disc-tracking/index.html">第一版回放</a></p><p>蓝色实框和线表示画面观测，包括模型检测及局部外观跟踪；视频中的 VISUAL 表示局部外观跟踪，置信度为空；黄色虚框和点表示短时位置预测；灰色框表示待确认候选。按每段记录中的时限停止预测并结束旧 ID。暂停视频、选择 ID 可检查对应轨迹。</p>
<p>手持、地面和空中飞盘都会建立轨迹。误检也可能形成 ID，断轨后的新 ID 可能仍是同一只飞盘。这里的计数不是准确率、投掷次数或接盘结果。手持镜头尚无相机运动补偿。局部外观跟踪不算模型检测，预测不算画面观测。仍可能误接，需人工检查。</p>
''' + ''.join(sections) + '''<script>
const samples=DATA;
document.querySelectorAll('section').forEach((section,i)=>{
 const s=samples[i],v=section.querySelector('video'),c=section.querySelector('canvas'),ctx=c.getContext('2d'),select=section.querySelector('select'),toggle=section.querySelector('input');
 c.width=1000;c.height=Math.round(1000*s.height/s.width);const sx=1000/s.width,sy=c.height/s.height;
 function draw(){ctx.fillStyle='#fafafa';ctx.fillRect(0,0,c.width,c.height);const idx=Math.min(s.frames.length-1,Math.max(0,Math.floor(v.currentTime*s.fps+1e-6))),current=s.frames[idx];let previous=new Map();
  for(let j=0;j<=idx;j++){const frame=s.frames[j],next=new Map();for(const t of frame.tracks){if(!t.track_id||(select.value!=='all'&&t.track_id!==select.value))continue;const b=t.bbox||((toggle.checked&&t.prediction_bbox)?t.prediction_bbox:null);if(!b)continue;const p=[(b[0]+b[2])/2*sx,(b[1]+b[3])/2*sy];ctx.fillStyle=t.bbox?'#177ba5':'#c18b00';ctx.beginPath();ctx.arc(...p,j===idx?5:2,0,Math.PI*2);ctx.fill();if(t.bbox){ctx.strokeStyle='#177ba5';ctx.lineWidth=1.5;const old=previous.get(t.track_id);if(old){ctx.beginPath();ctx.moveTo(...old);ctx.lineTo(...p);ctx.stroke();}next.set(t.track_id,p);}}previous=next;}
  section.querySelector('.clock').textContent=`源帧 ${current.frame_id} · 真实时间 ${current.t_sec.toFixed(3)} 秒 · 观测 ${current.tracks.filter(t=>t.bbox).length} 个盘（外观 ${current.tracks.filter(t=>t.measurement_source==='local_visual').length}） · 预测 ${current.tracks.filter(t=>t.prediction_bbox).length} 个盘`;
 }['timeupdate','loadedmetadata','seeked'].forEach(e=>v.addEventListener(e,draw));select.addEventListener('change',draw);toggle.addEventListener('change',draw);draw();
});</script></html>'''
    data = [{key:s[key] for key in ('width','height','fps','frames')} for s in samples]
    page = page.replace('DATA',json.dumps(data,ensure_ascii=False,allow_nan=False).replace('<','\\u003c'))
    (root/'all-tracks.jsonl').write_text(''.join(combined),encoding='utf-8')
    (root/'index.html').write_text(page,encoding='utf-8')
    names = ['all-tracks.jsonl','index.html']+[f"{s['slug']}-preview.mp4" for s in samples]
    write_json(gallery_cache,{'signature':signature,'artifact_sha256':{n:sha256(root/n) for n in names}})
    print(f'Gallery: {root / "index.html"}',flush=True)
    return root/'index.html'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=PROJECT/'outputs'/'disc-tracking-v2')
    parser.add_argument('--run-version',default='v1')
    parser.add_argument('--ffmpeg-dir',type=Path)
    args = parser.parse_args()
    try: build(args.root,args.ffmpeg_dir,args.run_version)
    except (ValueError,OSError,RuntimeError,KeyError,subprocess.SubprocessError) as exc: parser.exit(1,f'Disc review failed: {exc}\n')


if __name__ == '__main__': main()
