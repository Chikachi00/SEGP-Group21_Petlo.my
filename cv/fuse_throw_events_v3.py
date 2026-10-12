"""Build a two-tripod sample event fusion page and optional label comparison."""
import argparse
import hashlib
import html
import json
from pathlib import Path

PREDICTION_MAP={"catch_candidate":"catch_success","ground_pickup_candidate":"ground_pickup","miss_candidate":"miss_candidate"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def run(root,labels_path=None):
    root=Path(root).resolve();front=root/"front-v1";side=root/"side-v1"
    summaries={name:read(folder/"summary.json") for name,folder in (("front",front),("side",side))}
    expected={"front":"Landscape_Tripod_FrontView","side":"Landscape_Tripod_SideView"}
    events={}
    for name,folder in (("front",front),("side",side)):
        summary=summaries[name]
        if summary.get("status")!="complete" or summary.get("video_id")!=expected[name] or summary.get("provenance",{}).get("camera")!="tripod":
            raise ValueError(f"A complete {name} tripod sample run is required")
        for rel,sha in summary.get("artifact_sha256",{}).items():
            path=(folder/rel).resolve()
            if not path.is_relative_to(folder) or not path.is_file() or digest(path)!=sha:raise ValueError(f"Modified or missing {name} artifact: {rel}")
        payload=read(folder/"events-v3.json")
        if payload.get("video_id")!=expected[name] or payload.get("schema_version")!=3:raise ValueError("Unexpected v3 event schema")
        events[name]=payload["event_candidates"]
    if len(events["front"])!=len(events["side"]) or not events["front"]:raise ValueError("Front and side must contain the same number of event candidates")
    if any(not e.get("release_evidence") for name in events for e in events[name]):raise ValueError("Ordinal fusion needs release evidence for every event")
    source_hashes={name:summaries[name]["provenance"]["source_sha256"] for name in summaries}
    labels=None
    if labels_path:
        labels=read(labels_path)
        if labels.get("video_id")!=expected["side"] or labels.get("source_sha256")!=source_hashes["side"]:raise ValueError("Human labels must match the side-view source")
    fused=[]
    labels_by_id={r["throw_id"]:r for r in labels.get("event_labels",[])} if labels else {}
    for index,(f,s) in enumerate(zip(events["front"],events["side"]),1):
        front_vote=PREDICTION_MAP.get(f.get("predicted_outcome"))
        side_vote=PREDICTION_MAP.get(s.get("predicted_outcome"))
        votes={v for v in (front_vote,side_vote) if v}
        conflict=len(votes)>1
        outcome=next(iter(votes)) if len(votes)==1 else "uncertain"
        row={"sample_throw_id":f"sample-throw-{index:03d}","front_throw_id":f["throw_id"],"side_throw_id":s["throw_id"],
             "front_outcome":f["predicted_outcome"],"side_outcome":s["predicted_outcome"],
             "front_source_time_sec":[f["start_sec"],f["end_sec"]],"side_source_time_sec":[s["start_sec"],s["end_sec"]],
             "outcome":outcome,"conflict":conflict,"pairing":"event order; source videos are not time-synchronized"}
        label=labels_by_id.get(s["throw_id"])
        if label:
            row["human_outcome"]=label["verified_outcome"]
            row["matches_human_label"]=label["verified_outcome"]==outcome
        fused.append(row)
    benchmark={"labels_used":bool(labels),"evaluated_events":sum("matches_human_label" in r for r in fused),
               "matches":sum(r.get("matches_human_label",False) for r in fused),
               "same_sample_rule_tuning":True,"independent_accuracy_claim_allowed":False}
    benchmark["sample_match_rate"]=(benchmark["matches"]/benchmark["evaluated_events"] if benchmark["evaluated_events"] else None)
    outputs={"schema_version":1,"algorithm":"throw-events-v3 two-angle ordinal fusion","source_sha256":source_hashes,
             "pairing_method":"Ordinal pairing is permitted only for these two matching sample recordings; timestamps are retained per view and not treated as synchronized.",
             "results":fused,"benchmark":benchmark}
    signature=hashlib.sha256(json.dumps({"source_sha256":source_hashes,"front_cache":summaries["front"]["cache_key"],
        "side_cache":summaries["side"]["cache_key"],"labels_sha256":digest(labels_path) if labels_path else None,
        "code_sha256":digest(__file__)},sort_keys=True).encode()).hexdigest()
    outputs["cache_key"]=signature
    result_path=root/"fused-results.json";index_path=root/"index.html";gallery_path=root/"gallery.json"
    for path in (result_path,index_path,gallery_path):
        if path.exists():raise ValueError("Fusion output already exists; choose a new output root")
    result_path.write_text(json.dumps(outputs,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    counts={}
    for r in fused:counts[r["outcome"]]=counts.get(r["outcome"],0)+1
    rows="".join(f"<tr><td>{html.escape(r['sample_throw_id'])}</td><td>{html.escape(r['outcome'])}</td><td>{html.escape(r['front_outcome'])}<br>{r['front_source_time_sec'][0]:.3f}–{r['front_source_time_sec'][1]:.3f}s</td><td>{html.escape(r['side_outcome'])}<br>{r['side_source_time_sec'][0]:.3f}–{r['side_source_time_sec'][1]:.3f}s</td><td>{'Yes' if r['conflict'] else 'No'}</td><td>{'Yes' if r.get('matches_human_label') else ('No' if 'matches_human_label' in r else 'Not reviewed')}</td></tr>" for r in fused)
    html_text=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Two-angle sample event review v3</title><style>body{{font:16px system-ui;max-width:1120px;margin:32px auto;padding:0 20px;background:#f5f6f8;color:#20242b}}section{{background:white;padding:22px;margin:18px 0;border-radius:12px}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #ddd}}p{{line-height:1.65}}a{{color:#075fc0}}</style><h1>Two-angle Sample Event Review · v3</h1><p>Matched by event order because these front and side clips show the same ordered sample attempts. The recordings are not synchronized. A catch or ground-pickup outcome is a candidate from either view; disagreement is reported as uncertain.</p><section><h2>Combined candidates</h2><p>{html.escape(json.dumps(counts,ensure_ascii=False))}</p><table><thead><tr><th>Sample event</th><th>Combined candidate</th><th>Front evidence</th><th>Side evidence</th><th>Conflict</th><th>Human label match</th></tr></thead><tbody>{rows}</tbody></table></section><section><h2>Review videos</h2><p><a href="front-v1/index.html">Open front event replay</a> · <a href="side-v1/index.html">Open side event replay</a></p><p><a href="fused-results.json">Open fused results</a> · <a href="../throw-events-v2/index.html">Previous v2 results</a></p></section><p>These four attempts were used to refine the rules; a 4/4 match on this sample is a development check, not an independent accuracy estimate. Predictions remain review candidates.</p></html>'''
    index_path.write_text(html_text,encoding="utf-8")
    gallery_path.write_text(json.dumps({"status":"complete","cache_key":signature,"index_sha256":digest(index_path),
        "fused_results_sha256":digest(result_path),"candidate_counts":counts,"benchmark":benchmark},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"index":str(index_path),"candidate_counts":counts,"benchmark":benchmark},ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1]/"outputs"/"throw-events-v3");p.add_argument("--labels",type=Path);a=p.parse_args();run(a.root,a.labels)

if __name__=="__main__":main()
