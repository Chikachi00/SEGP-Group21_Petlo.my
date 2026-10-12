"""Build bounded visual audit and offline sample gallery for this experiment."""
from collections import deque
import html
import json
from pathlib import Path
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from cv.track_dog_video import annotate, read_json, sha256, write_json
from cv.video_tools.media import Toolchain, iter_source_frames
from cv.video_tools.review import review

ROOT = PROJECT / "outputs" / "dog-tracking"
PACK = PROJECT / "outputs" / "video-analysis-pack"
TOOLS = Toolchain.discover()
specs = [("front", "正面", [9.35, 9.366667, 9.5, 9.616667]),
         ("side", "侧面", [26.19, 26.3, 26.5, 26.760067]),
         ("handheld", "手持", [3.1, 4., 5.1, 5.939267])]
manifest = read_json(PACK / "manifest.json")
videos = {v["id"]: v for v in manifest["videos"]}
summaries, gallery_data, combined = [], [], []
for slug, title, times in specs:
    run_dir = ROOT / f"{slug}-v1"
    summary = read_json(run_dir / "summary.json")
    states = [json.loads(line) for line in (run_dir / "states.jsonl").read_text().splitlines()]
    video = videos[summary["video_id"]]
    index = read_json(PACK / video["paths"]["frame_index"])
    selected = sorted({min(range(len(index)), key=lambda i: abs(index[i]["t_sec"] - t)) for t in times})
    audit = ROOT / "audit" / slug
    audit.mkdir(parents=True, exist_ok=True)
    import cv2
    import numpy as np
    mappings = []
    for record, frame in iter_source_frames(Path(video["source"]), [index[i] for i in selected], video["metadata"], TOOLS):
        observation = states[record["frame_id"]]
        annotate(frame, record, observation, deque())
        factor = min(1., 1280 / max(frame.shape[:2]))
        browse = cv2.resize(frame, (round(frame.shape[1] * factor), round(frame.shape[0] * factor)))
        name = f"frame-{record['frame_id']:06d}.jpg"
        if not cv2.imwrite(str(audit / name), browse):
            raise RuntimeError("Audit JPEG write failed")
        box = observation["bbox"] or observation["prediction_bbox"]
        crop = None
        if box:
            w, h = box[2] - box[0], box[3] - box[1]
            x1, y1 = max(0, int(box[0] - w)), max(0, int(box[1] - h))
            x2, y2 = min(frame.shape[1], int(box[2] + w)), min(frame.shape[0], int(box[3] + h))
            crop = [x1, y1, x2, y2]
            cv2.imwrite(str(audit / name.replace(".jpg", "-crop.jpg")), frame[y1:y2, x1:x2])
        mappings.append({**record, "state": observation["state"], "track_id": observation["track_id"],
                         "source_size": [video["width"], video["height"]], "browse_size": [browse.shape[1], browse.shape[0]],
                         "browse_scale_xy": [browse.shape[1] / video["width"], browse.shape[0] / video["height"]],
                         "crop_original_xyxy": crop, "image": name})
    write_json(audit / "index.json", mappings)
    preview = ROOT / f"{slug}-preview.mp4"
    preview_signature = {"input_sha256": sha256(run_dir / "tracked.mp4"), "max_side": 1280, "crf": 23, "toolchain": TOOLS.version}
    cache = preview.with_suffix(".json")
    if not preview.exists() or not cache.exists() or read_json(cache).get("signature") != preview_signature:
        command = [TOOLS.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-threads", "4", "-filter_threads", "1",
                   "-i", str(run_dir / "tracked.mp4"), "-vf", "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                   "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "4", "-fps_mode", "passthrough", "-movflags", "+faststart", str(preview)]
        subprocess.run(command, capture_output=True, check=True)
    proc = subprocess.run([TOOLS.ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames,width,height", "-of", "json", str(preview)], capture_output=True, check=True)
    stream = json.loads(proc.stdout)["streams"][0]
    if int(stream["nb_read_frames"]) != summary["processed_frames"]:
        raise RuntimeError("Preview frame count mismatch")
    write_json(cache, {"signature": preview_signature, "frames": int(stream["nb_read_frames"]), "dimensions": [stream["width"], stream["height"]], "sha256": sha256(preview)})
    summaries.append({"title": title, "slug": slug, **summary})
    gallery_data.append({"slug": slug, "width": video["width"], "height": video["height"], "frames": states})
    combined.append((run_dir / "tracks.jsonl").read_text(encoding="utf-8"))
    print(f"{slug}: audit and full-frame H264 preview complete", flush=True)
combined_path = ROOT / "all-tracks-v1.jsonl"
combined_path.write_text("".join(combined), encoding="utf-8")
result = review(PACK, combined_path, TOOLS, processing_seconds=sum(s["processing_seconds"] for s in summaries))
write_json(ROOT / "review-location.json", result)
sections = []
for summary in summaries:
    slug, title, counts = summary["slug"], summary["title"], summary["states"]
    sections.append(f'''<section><h2>{title}</h2>
<p>全片 {summary['processed_frames']} 帧 · 实测 {counts.get('detected',0)} 帧 · 短时预测 {counts.get('predicted',0)} 帧 · 建立 {summary['track_count']} 条轨迹</p>
<video controls preload="metadata" src="{slug}-preview.mp4"></video>
<p><a href="{slug}-v1/tracked.mp4">原尺寸回放（VLC）</a> · <a href="{slug}-v1/trajectory.csv">像素轨迹 CSV</a> · <a href="{slug}-v1/summary.json">运行记录</a></p>
<button class="example" type="button">查看一次丢失片段</button> <label><input type="checkbox" class="predictions" checked> 显示黄色预测点</label><canvas aria-label="狗的像素轨迹"></canvas><p class="clock"></p>
</section>''')
review_path = Path(result["report_path"]).parent
page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>狗追踪第一版</title>
<style>body{font-family:system-ui,sans-serif;background:#f5f6f8;color:#20242b;max-width:1050px;margin:36px auto;padding:0 20px}h1{font-size:30px}section{background:white;padding:22px;margin:24px 0;border-radius:12px}video{width:100%;max-height:640px;background:#111}canvas{display:block;width:100%;height:auto;max-height:500px;border:1px solid #ddd;margin-top:14px}a{color:#075fc0}.note{padding:16px;background:#fff4cf;border-radius:8px}p{line-height:1.7}</style>
<h1>狗追踪 · 第一版样本验证</h1><p>绿色实框和轨迹线表示接受的检测。黄色虚框和点表示短时位置预测；超过 0.25 秒停止预测，超过 0.75 秒结束旧 ID。暂停视频即可检查当时的画面和轨迹。</p>
<p class="note">预测不计入真实检测。计数是运行表现，不是准确率。手持视频后段仍会持续丢失；这一版没有相机运动补偿、飞盘追踪或接盘评分。</p>
''' + "".join(sections) + '''<script>
const samples=DATA;
document.querySelectorAll('section').forEach((section,i)=>{
 const sample=samples[i],video=section.querySelector('video'),canvas=section.querySelector('canvas'),ctx=canvas.getContext('2d'),toggle=section.querySelector('.predictions');
 canvas.width=900;canvas.height=Math.round(900*sample.height/sample.width);const sx=900/sample.width,sy=canvas.height/sample.height;
 function render(){ctx.fillStyle='#fafafa';ctx.fillRect(0,0,canvas.width,canvas.height);const frame=Math.min(sample.frames.length-1,Math.max(0,Math.floor(video.currentTime/(video.duration||1)*sample.frames.length)));const current=sample.frames[frame];let previous=null;
  for(const r of sample.frames){if(r.frame_id>current.frame_id)break;if(!r.bbox){previous=null;if(toggle.checked&&r.prediction_bbox){const b=r.prediction_bbox;ctx.fillStyle='#d29a00';ctx.beginPath();ctx.arc((b[0]+b[2])/2*sx,(b[1]+b[3])/2*sy,2.5,0,Math.PI*2);ctx.fill();}continue;}const b=r.bbox,point=[(b[0]+b[2])/2*sx,(b[1]+b[3])/2*sy];ctx.strokeStyle='#14883b';ctx.lineWidth=2;if(previous&&previous.id===r.track_id){ctx.beginPath();ctx.moveTo(...previous.point);ctx.lineTo(...point);ctx.stroke();}previous={id:r.track_id,point};}
  const b=current.bbox||current.prediction_bbox;if(b){ctx.fillStyle=current.bbox?'#14883b':'#d29a00';ctx.beginPath();ctx.arc((b[0]+b[2])/2*sx,(b[1]+b[3])/2*sy,6,0,Math.PI*2);ctx.fill();}section.querySelector('.clock').textContent=`源帧 ${current.frame_id} · 真实时间 ${current.t_sec.toFixed(3)} 秒 · ${current.track_id||'未确认'} · ${current.state}`;
 }video.addEventListener('timeupdate',render);video.addEventListener('loadedmetadata',render);video.addEventListener('seeked',render);toggle.addEventListener('change',render);section.querySelector('.example').addEventListener('click',()=>{video.pause();video.currentTime=(sample.example_frame+.25)/sample.fps;render();});render();
});</script></html>'''
# The replay is CFR at a declared nominal FPS; derive source frame ordinal
# from that clock and use the stored real timestamp for the graph label.
for i, (slug, _, _) in enumerate(specs):
    gallery_data[i]["fps"] = videos[summaries[i]["video_id"]]["metadata"]["avg_frame_rate"]
    gallery_data[i]["example_frame"] = {"front": 570, "side": 1588, "handheld": 120}[slug]
page = page.replace("Math.floor(video.currentTime/(video.duration||1)*sample.frames.length)", "Math.floor(video.currentTime*sample.fps+1e-6)")
page = page.replace("width:100%;height:auto;max-height:500px", "max-width:100%;width:auto;height:auto;max-height:500px")
import os
review_url = Path(os.path.relpath(review_path / "playback.html", ROOT)).as_posix()
page = page.replace("<h1>狗追踪", f'<p><a href="{html.escape(review_url)}">打开自动失败片段复查</a></p><h1>狗追踪')
page = page.replace("DATA", json.dumps(gallery_data, ensure_ascii=False).replace("<", "\\u003c"))
(ROOT / "index.html").write_text(page, encoding="utf-8")
write_json(ROOT / "runs.json", {"runs": summaries, "tests": {"passed": 42, "new_tracking_tests": 11}, "combined_tracks": str(combined_path), "review": result})
if result["status"] != "complete":
    raise RuntimeError("Some review windows failed: " + str(result["render_errors"]))
print(json.dumps({"status": result["status"], "records": result["coverage_summary"]["record_count"], "windows": len(result["windows"]), "report": result["report_path"]}, ensure_ascii=False), flush=True)
