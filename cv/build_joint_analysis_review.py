"""Build an independent index for three complete joint-analysis runs."""
import argparse
import hashlib
import html
import json
from pathlib import Path

if __package__:
    from .analyze_dog_disc import read_json,sha256,write_json
else:
    from analyze_dog_disc import read_json,sha256,write_json

PROJECT=Path(__file__).resolve().parents[1]


def build(root):
    root=Path(root).resolve()
    summaries=[]
    for slug,title in [('front','正面'),('side','侧面'),('handheld','手持')]:
        folder=root/f'{slug}-v1'
        s=read_json(folder/'summary.json')
        if s.get('status')!='complete': raise ValueError('Incomplete joint run')
        for name,digest in s['artifact_sha256'].items():
            target=(folder/name).resolve()
            if not target.is_relative_to(folder) or sha256(target)!=digest: raise ValueError('Joint run artifact modified')
        summaries.append((slug,title,s))
    signature={'code':sha256(__file__),'runs':{slug:sha256(root/f'{slug}-v1'/'summary.json') for slug,_,_ in summaries}}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()
    cache=root/'gallery.json'
    if (root/'index.html').exists() or cache.exists():
        old=read_json(cache)
        if old.get('cache_key')!=key or old.get('index_sha256')!=sha256(root/'index.html'):
            raise ValueError('Gallery already exists with changed input/content; choose a new root')
        print(f'Verified joint review: {root}',flush=True)
        return root/'index.html'
    cards=[]
    for slug,title,s in summaries:
        m=s['metrics']
        candidates=sum(m['candidate_types'].values())
        cards.append(f'<section><h2>{title}</h2><p>{m["processed_frames"]} 源帧 · 双目标同帧观测 {m["joint_observed_frames"]} 帧 · {candidates} 个待核查候选</p><p><a href="{slug}-v1/index.html">打开视频与逐帧联合分析</a> · <a href="{slug}-v1/events.json">候选证据</a></p></section>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>狗与飞盘联合分析</title><style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:0 20px;background:#f5f6f8;color:#20242b}section{padding:24px;background:white;margin:20px 0;border-radius:12px}p{line-height:1.7}a{color:#075fc0}</style><h1>狗与飞盘联合分析 · 第一版</h1><p>按真实源帧对齐狗和飞盘的观测，输出移动、接近和疑似接触窗口。每个候选都等待人工核查，没有自动确认的接盘或失误。</p><p>候选数量不是投掷次数或准确率；同一飞盘可能有多个候选。前、侧面可能记录同一次投掷，不能直接相加。手持暂不补偿镜头移动。</p>'''+''.join(cards)+'''<p><a href="../disc-tracking-v2/index.html">飞盘恢复版</a> · <a href="../dog-tracking/index.html">狗追踪版</a></p></html>'''
    (root/'index.html').write_text(page,encoding='utf-8')
    write_json(cache,{'status':'complete','cache_key':key,'signature':signature,'index_sha256':sha256(root/'index.html'),
                     'processed_frames':sum(s['metrics']['processed_frames'] for _,_,s in summaries)})
    print(f'Joint review: {root/"index.html"}',flush=True)
    return root/'index.html'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=PROJECT/'outputs'/'joint-analysis')
    args=parser.parse_args()
    try: build(args.root)
    except (ValueError,OSError,KeyError) as exc: parser.exit(1,f'Joint review failed: {exc}\n')


if __name__=='__main__': main()
