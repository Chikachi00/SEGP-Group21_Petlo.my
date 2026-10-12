"""Create clean CFR browsing videos with every original frame; no model inference."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import uuid

if __package__:
    from .analyze_dog_disc import read_json,write_json,sha256
    from .video_tools.media import Toolchain
else:
    from analyze_dog_disc import read_json,write_json,sha256
    from video_tools.media import Toolchain

PROJECT=Path(__file__).resolve().parents[1]


def build(pack,output,ffmpeg_dir=None):
    pack,output=Path(pack).resolve(),Path(output).resolve()
    manifest=read_json(pack/'manifest.json')
    tools=Toolchain.discover(ffmpeg_dir)
    videos=[v for v in manifest['videos'] if v.get('status')=='complete' and v.get('role')=='action']
    if not videos: raise ValueError('No complete action videos')
    protected=[pack,PROJECT/'sources',PROJECT/'cv',PROJECT/'docs',PROJECT/'tests']+[Path(v['source']).resolve().parent for v in videos]
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected): raise ValueError('Independent preview directory required')
    output.mkdir(parents=True,exist_ok=True)
    for v in videos:
        source=Path(v['source']).resolve()
        if sha256(source)!=v['source_sha256']: raise ValueError('Original source hash changed')
        fps=v['metadata']['avg_frame_rate']
        if not math.isfinite(fps) or fps<=0: raise ValueError('Positive nominal FPS required')
        scale=min(1,1280/max(v['width'],v['height']))
        w=max(2,int(v['width']*scale)//2*2);h=max(2,int(v['height']*scale)//2*2)
        name=v['id']
        if Path(name).name!=name or '/' in name or '\\' in name: raise ValueError('Unsafe video ID')
        target=output/f'{name}.mp4';cache=output/f'{name}.json'
        signature={'source_sha256':v['source_sha256'],'size':[w,h],'fps':fps,'source_frames':v['frames_count'],
                   'source_metadata':v['metadata'],'toolchain':tools.version,'code':sha256(__file__)}
        if target.exists() or cache.exists():
            old=read_json(cache)
            if old.get('signature')!=signature or old.get('sha256')!=sha256(target): raise ValueError('Preview cache changed; choose a new directory')
            print(f'Verified clean preview: {name}',flush=True)
            continue
        temp=output/f'.clean-{uuid.uuid4().hex}.mp4'
        try:
            # Reset replay timestamps without a frame-rate filter or inserted frames.
            command=[tools.ffmpeg,'-v','error','-i',str(source),'-map','0:v:0','-an',
                     '-vf',f'scale={w}:{h},setpts=N/{fps:.12f}/TB','-fps_mode','passthrough',
                     '-c:v','libx264','-threads','4','-preset','fast','-crf','23','-pix_fmt','yuv420p',
                     '-movflags','+faststart','-y',str(temp)]
            result=subprocess.run(command,capture_output=True)
            if result.returncode: raise RuntimeError(result.stderr.decode('utf-8',errors='replace').strip())
            result=subprocess.run([tools.ffprobe,'-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=width,height,nb_read_frames,avg_frame_rate','-of','json',str(temp)],check=True,capture_output=True)
            stream=json.loads(result.stdout)['streams'][0]
            ratio=stream['avg_frame_rate'].split('/');actual_fps=float(ratio[0])/float(ratio[1])
            if int(stream['nb_read_frames'])!=v['frames_count'] or [stream['width'],stream['height']]!=[w,h] or abs(actual_fps-fps)>1e-4:
                raise RuntimeError('Clean preview changed frame count, dimensions or replay FPS')
            if sha256(source)!=v['source_sha256']: raise ValueError('Source changed during preview generation')
            temp.rename(target)
            write_json(cache,{'status':'complete','signature':signature,'sha256':sha256(target),
                             'source_time_note':'CFR browsing only; evidence times come from original frame index.'})
            print(f'Clean preview: {name}, {v["frames_count"]} original frames',flush=True)
        finally:
            if temp.exists():
                if temp.resolve().parent!=output or not temp.name.startswith('.clean-'): raise RuntimeError('Unsafe preview cleanup')
                temp.unlink()
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack',type=Path,default=PROJECT/'outputs'/'video-analysis-pack')
    parser.add_argument('--output-dir',type=Path,default=PROJECT/'outputs'/'joint-previews')
    parser.add_argument('--ffmpeg-dir',type=Path)
    args=parser.parse_args()
    try: build(args.pack,args.output_dir,args.ffmpeg_dir)
    except (ValueError,OSError,RuntimeError,KeyError,subprocess.SubprocessError) as exc: parser.exit(1,f'Joint preview failed: {exc}\n')


if __name__=='__main__': main()
