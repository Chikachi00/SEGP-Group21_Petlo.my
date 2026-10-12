"""Compare throw-event predictions with source-bound human review labels."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

PREDICTION_MAP = {
    "catch_candidate": "catch_success",
    "ground_pickup_candidate": "ground_pickup",
    "miss_candidate": "miss",
}
VALID = {"catch_success", "ground_pickup", "miss", "uncertain"}


def load(path: Path):
    with path.open(encoding="utf-8-sig") as f:
        return json.load(f)


def evaluate(events_path: Path, labels_path: Path, summary_path: Path | None = None):
    payload = load(events_path)
    labels = load(labels_path)
    summary_path = summary_path or events_path.with_name("summary.json")
    summary = load(summary_path)
    video_id = payload.get("video_id")
    source_hash = summary.get("provenance", {}).get("source_sha256")
    if labels.get("video_id") != video_id or labels.get("source_sha256") != source_hash:
        raise ValueError("Review labels do not match the prediction video/source hash")
    predicted = {e["throw_id"]: e.get("predicted_outcome") for e in payload.get("event_candidates", [])}
    reviewed = labels.get("event_labels")
    if not isinstance(reviewed, list) or not reviewed:
        raise ValueError("At least one reviewed event label is required")
    ids = [r.get("throw_id") for r in reviewed]
    if len(ids) != len(set(ids)) or any(i not in predicted for i in ids):
        raise ValueError("Reviewed event IDs must be unique and exist in the prediction file")
    if any(r.get("review_status") != "reviewed" or r.get("confirmed_throw") is not True or r.get("verified_outcome") not in VALID - {"uncertain"} for r in reviewed):
        raise ValueError("Each benchmark item needs a reviewed throw and a decisive ground-truth outcome")
    rows=[]
    for r in reviewed:
        raw=predicted[r["throw_id"]]
        pred=PREDICTION_MAP.get(raw, "uncertain")
        truth=r["verified_outcome"]
        rows.append({"throw_id":r["throw_id"],"predicted_raw":raw,"predicted":pred,"ground_truth":truth,"correct":pred==truth})
    decisive=[r for r in rows if r["predicted"]!="uncertain"]
    return {
        "schema_version":1,"video_id":video_id,"source_sha256":source_hash,
        "reviewed_events":len(rows),"decisive_predictions":len(decisive),
        "coverage":len(decisive)/len(rows),
        "correct_decisive_predictions":sum(r["correct"] for r in decisive),
        "accuracy_when_decisive":(sum(r["correct"] for r in decisive)/len(decisive) if decisive else None),
        "exact_end_to_end_matches":sum(r["correct"] for r in rows),
        "exact_end_to_end_rate":sum(r["correct"] for r in rows)/len(rows),
        "events":rows,
        "interpretation":"Sample-only diagnostic. Coverage and exact-match rate are not a general accuracy estimate."
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--events",type=Path,required=True)
    p.add_argument("--labels",type=Path,required=True)
    p.add_argument("--summary",type=Path)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    result=evaluate(a.events,a.labels,a.summary)
    text=json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(text+"\n",encoding="utf-8")
    print(text)

if __name__ == "__main__":
    main()
