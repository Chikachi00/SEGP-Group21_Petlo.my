"""Build candidate event counts and session rates from fused throw-event results."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

SCHEMA_VERSION = 1
BUCKETS = ("in_air_catch_candidate", "ground_pickup_candidate", "miss_candidate", "uncertain")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bucket_outcome(value: object) -> str:
    mapping = {
        "catch_success": "in_air_catch_candidate",
        "catch_candidate": "in_air_catch_candidate",
        "ground_pickup": "ground_pickup_candidate",
        "ground_pickup_candidate": "ground_pickup_candidate",
        "miss": "miss_candidate",
        "miss_candidate": "miss_candidate",
        "uncertain": "uncertain",
    }
    if value not in mapping:
        raise ValueError(f"Unsupported fused outcome: {value!r}")
    return mapping[value]


def summarize(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Expected fused-results schema_version 1")
    rows = payload.get("results")
    if not isinstance(rows, list):
        raise ValueError("Fused results must contain a results list")

    counts = {name: 0 for name in BUCKETS}
    events = []
    seen_ids = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sample_throw_id"), str):
            raise ValueError("Every result needs a sample_throw_id")
        event_id = row["sample_throw_id"]
        if event_id in seen_ids:
            raise ValueError(f"Duplicate sample_throw_id: {event_id}")
        seen_ids.add(event_id)
        bucket = bucket_outcome(row.get("outcome"))
        counts[bucket] += 1
        events.append({
            "sample_throw_id": event_id,
            "category": bucket,
            "front_outcome": row.get("front_outcome"),
            "side_outcome": row.get("side_outcome"),
            "front_source_time_sec": row.get("front_source_time_sec"),
            "side_source_time_sec": row.get("side_source_time_sec"),
            "conflict": bool(row.get("conflict", False)),
        })

    total = len(events)
    uncertain = counts["uncertain"]
    classified = total - uncertain
    catches = counts["in_air_catch_candidate"]
    pickups = counts["ground_pickup_candidate"]
    misses = counts["miss_candidate"]
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": "unverified_candidate_statistics",
        "algorithm": payload.get("algorithm"),
        "source_sha256": payload.get("source_sha256", {}),
        "total_throw_candidates": total,
        "classified_candidate_events": classified,
        "uncertain_events": uncertain,
        "candidate_counts": counts,
        "candidate_coverage": classified / total if total else None,
        "in_air_catch_candidate_rate": catches / classified if classified else None,
        "retrieval_candidate_rate": (catches + pickups) / classified if classified else None,
        "denominator_definition": "Classified throw candidates; uncertain outcomes are excluded. Ground pickups count as non-air catches in the in-air catch rate and as retrieved in the retrieval rate.",
        "human_labels_used_for_statistics": False,
        "events": events,
        "limitations": [
            "Outcomes are algorithm candidates and are not verified ground truth.",
            "These rates summarize this analyzed sample and are not general accuracy estimates.",
            "The two camera views are paired by event order and are not time-synchronized.",
        ],
    }


def render_html(stats: dict) -> str:
    def pct(value):
        return "—" if value is None else f"{value * 100:.1f}%"

    labels = {
        "in_air_catch_candidate": "In-air catch candidates",
        "ground_pickup_candidate": "Ground-pickup candidates",
        "miss_candidate": "Miss candidates",
        "uncertain": "Uncertain",
    }
    cards = "".join(
        f'<article><span>{html.escape(labels[key])}</span><strong>{stats["candidate_counts"][key]}</strong></article>'
        for key in BUCKETS
    )
    rows = []
    for event in stats["events"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(event['sample_throw_id'])}</td>"
            f"<td>{html.escape(labels[event['category']])}</td>"
            f"<td>{html.escape(str(event.get('front_outcome') or '—'))}</td>"
            f"<td>{html.escape(str(event.get('side_outcome') or '—'))}</td>"
            f"<td>{'Yes' if event['conflict'] else 'No'}</td>"
            "</tr>"
        )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Throw-event sample statistics</title><style>
body{{font:16px system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;background:#f4f6f8;color:#20242b}}
section{{background:white;padding:22px;margin:18px 0;border-radius:12px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}}
article{{background:#f1f5fa;padding:16px;border-radius:9px;display:grid;gap:12px}}strong{{font-size:30px}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}}.metric{{font-size:27px;font-weight:700}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:11px;border-bottom:1px solid #ddd}}p{{line-height:1.6}}
</style></head><body><h1>Throw-event sample statistics</h1>
<p>These are model-generated candidates for review, not confirmed outcomes. The two tripod views are paired by event order; their timestamps are not synchronized.</p>
<section><h2>Candidate counts</h2><div class="cards">{cards}</div></section>
<section><h2>Candidate rates</h2><div class="metrics">
<div>Candidate coverage<div class="metric">{pct(stats['candidate_coverage'])}</div><small>classified candidates / all throw candidates</small></div>
<div>In-air catch candidate rate<div class="metric">{pct(stats['in_air_catch_candidate_rate'])}</div><small>air catches / classified candidates</small></div>
<div>Retrieval candidate rate<div class="metric">{pct(stats['retrieval_candidate_rate'])}</div><small>air catches plus ground pickups / classified candidates</small></div>
</div><p>{html.escape(stats['denominator_definition'])}</p><p>Human review labels are not used to calculate these statistics.</p></section>
<section><h2>Per-event candidates</h2><table><thead><tr><th>Event</th><th>Combined category</th><th>Front</th><th>Side</th><th>Conflict</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section><h2>Limits</h2><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in stats['limitations'])}</ul><a href="../index.html">Back to two-angle event review</a></section>
</body></html>'''


def build(input_path: Path, output_dir: Path) -> dict:
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
    stats = summarize(payload)
    input_hash = sha256(input_path)
    cache_key = hashlib.sha256(json.dumps({
        "input_sha256": input_hash,
        "script_sha256": sha256(Path(__file__)),
        "schema_version": SCHEMA_VERSION,
    }, sort_keys=True).encode()).hexdigest()
    stats["input_sha256"] = input_hash
    stats["cache_key"] = cache_key
    outputs = {
        "statistics.json": json.dumps(stats, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        "statistics.html": render_html(stats),
    }
    manifest_path = output_dir / "manifest.json"

    if output_dir.exists():
        if not manifest_path.is_file():
            raise FileExistsError(f"Output directory exists without a valid manifest: {output_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if manifest.get("cache_key") != cache_key:
            raise FileExistsError("Statistics output already exists for different input/code; choose another output directory")
        for name, expected_hash in manifest.get("artifacts", {}).items():
            artifact = output_dir / name
            if not artifact.is_file() or sha256(artifact) != expected_hash:
                raise ValueError(f"Modified or missing statistics artifact: {name}")
        if set(manifest.get("artifacts", {})) != set(outputs):
            raise ValueError("Statistics manifest is incomplete")
        return {"output_dir": str(output_dir), "cache": "verified", "statistics": stats}

    output_dir.mkdir(parents=True)
    for name, content in outputs.items():
        (output_dir / name).write_text(content, encoding="utf-8")
    manifest = {
        "status": "complete",
        "cache_key": cache_key,
        "input_sha256": input_hash,
        "artifacts": {name: sha256(output_dir / name) for name in outputs},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"output_dir": str(output_dir), "cache": "created", "statistics": stats}


def main():
    default_root = Path(__file__).resolve().parents[1] / "outputs" / "throw-events-v3"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=default_root / "fused-results.json")
    parser.add_argument("--output-dir", type=Path, default=default_root / "statistics-v1")
    args = parser.parse_args()
    result = build(args.input, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
