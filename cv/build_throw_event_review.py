"""Verify complete event runs and build a separate offline review index."""
import argparse
import hashlib
import json
from pathlib import Path

if __package__:
    from .analyze_dog_disc import read_json,write_json,sha256
else:
    from analyze_dog_disc import read_json,write_json,sha256

PROJECT=Path(__file__).resolve().parents[1]


def build(root):
    root=Path(root).resolve();samples=[]
    for slug,title in [('front','Front'),('side','Side'),('handheld','Handheld')]:
        folder=root/f'{slug}-v1';s=read_json(folder/'summary.json')
        if s.get('status')!='complete':raise ValueError('Complete event runs required')
        for name,digest in s['artifact_sha256'].items():
            target=(folder/name).resolve()
            if not target.is_relative_to(folder) or sha256(target)!=digest:raise ValueError('Event artifact modified')
        samples.append((slug,title,s))
    signature={'code':sha256(__file__),'runs':{slug:sha256(root/f'{slug}-v1'/'summary.json') for slug,_,_ in samples}}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest();cache=root/'gallery.json'
    if cache.exists() or (root/'index.html').exists():
        old=read_json(cache)
        if old.get('cache_key')!=key or old.get('index_sha256')!=sha256(root/'index.html'):raise ValueError('Event gallery changed; use a new root')
        print(f'Verified event gallery: {root}',flush=True);return root/'index.html'
    sections=[]
    for slug,title,s in samples:
        counts=s['outcome_candidates']
        sections.append(f'<section><h2>{title}</h2><p>{s["processed_frames"]} source frames | {s["episode_candidates"]} episode candidates</p><p>Catch candidates: {counts.get("catch_candidate",0)} | Miss candidates: {counts.get("miss_candidate",0)} | Uncertain: {counts.get("uncertain",0)}</p><p><a href="{slug}-v1/index.html">Open event replay and contact crops</a> · <a href="{slug}-v1/events-v2.json">Episode evidence</a> · <a href="{slug}-v1/summary.json">Run summary</a></p></section>')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Throw Events v2</title><style>body{font:16px system-ui;max-width:1050px;margin:32px auto;padding:0 20px;background:#f5f6f8;color:#20242b}section{background:white;padding:24px;margin:20px 0;border-radius:12px}p{line-height:1.7}a{color:#075fc0}</style><h1>Throw Events v2 · Review Prototype</h1><p>Episode IDs group motion, approach and contact evidence. Every outcome is an unverified candidate. Candidate counts are not accuracy, verified throws or a catch rate. Different camera views may describe the same physical throw.</p><p>Missing observations never prove a catch or miss. Catch candidates use sustained 2D co-motion and do not localize mouth contact. Miss candidates require explicitly reviewed ground-contact frames. Handheld outcomes remain uncertain.</p>'''+''.join(sections)+'''<p><a href="../joint-analysis/index.html">Joint analysis v1</a> · <a href="../disc-tracking-v2/index.html">Disc recovery</a> · <a href="../dog-tracking/index.html">Dog tracking</a></p></html>'''
    (root/'index.html').write_text(page,encoding='utf-8')
    write_json(cache,{'status':'complete','cache_key':key,'signature':signature,'index_sha256':sha256(root/'index.html'),
                     'processed_frames':sum(s['processed_frames'] for _,_,s in samples)})
    print(f'Event review: {root/"index.html"}',flush=True);return root/'index.html'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=PROJECT/'outputs'/'throw-events-v2')
    args=parser.parse_args()
    try:build(args.root)
    except (ValueError,OSError,KeyError) as exc:parser.exit(1,f'Event review failed: {exc}\n')


if __name__=='__main__':main()
