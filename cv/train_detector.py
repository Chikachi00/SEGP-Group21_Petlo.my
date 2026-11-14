"""Fine-tune the baseline YOLO weights on the disc-dog dataset (person / dog / frisbee).

Small, fast discs benefit from high input resolution, so training defaults to 1280 px.
Class names are kept identical to the COCO names the pipeline already looks up, so the
resulting best.pt is a drop-in replacement: no detection or tracking code changes.
Nothing is downloaded: the base weights must already exist locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
EXPECTED_NAMES = ["person", "dog", "frisbee"]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_names(yaml_path):
    """Read class names and split folders from the simple yaml make_dataset.py writes."""
    names, splits, in_names = {}, {}, False
    for raw in Path(yaml_path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line:
            continue
        if line.startswith("names:"):
            in_names = True
            continue
        if in_names and line.startswith(" "):
            key, _, value = line.strip().partition(":")
            names[int(key)] = value.strip()
        else:
            in_names = False
            key, _, value = line.partition(":")
            splits[key.strip()] = value.strip()
    return [names[i] for i in sorted(names)], splits


def resolve_dataset(yaml_path, destination):
    """Check the dataset and write a copy of the yaml with an absolute path for reproducibility."""
    yaml_path = Path(yaml_path).resolve()
    names, splits = read_names(yaml_path)
    if names != EXPECTED_NAMES:
        raise ValueError(f"dataset.yaml classes must be {EXPECTED_NAMES} in this order, found {names}")
    counts = {}
    for split in ("train", "val"):
        folder = (yaml_path.parent / splits[split]).resolve()
        counts[split] = sum(1 for p in folder.glob("*.jpg")) if folder.is_dir() else 0
        if counts[split] == 0:
            raise ValueError(f"No images in the {split} split: {folder}")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"path: {yaml_path.parent.as_posix()}"] + [f"{k}: {v}" for k, v in splits.items()]
    lines.append("names:")
    lines += [f"  {i}: {n}" for i, n in enumerate(names)]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    test_folder = (yaml_path.parent / splits.get("test", "")).resolve() if "test" in splits else None
    counts["test"] = sum(1 for _ in test_folder.glob("*.jpg")) if test_folder and test_folder.is_dir() else 0
    return counts


def build_train_kwargs(args, data_yaml):
    """Training arguments for Ultralytics, tuned for small, fast-moving objects."""
    return {
        "data": str(data_yaml), "epochs": args.epochs, "imgsz": args.imgsz, "batch": args.batch,
        "device": args.device, "seed": args.seed, "deterministic": True, "patience": args.patience,
        "project": str(Path(args.project).resolve()), "name": args.name, "exist_ok": False,
        "freeze": args.freeze, "workers": args.workers, "cache": False, "amp": True, "plots": True,
        # Augmentation: keep scale/translation variety (discs appear at many sizes and positions);
        # mosaic puts small discs into varied contexts. copy_paste needs segment labels and is off.
        "mosaic": 1.0, "close_mosaic": args.close_mosaic, "scale": .5, "translate": .1,
        "fliplr": .5, "flipud": 0., "degrees": 0., "mixup": 0., "copy_paste": 0.,
        "hsv_h": .015, "hsv_s": .6, "hsv_v": .4, "lr0": args.lr0, "cos_lr": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=PROJECT / "data" / "dataset.yaml")
    parser.add_argument("--base", type=Path, default=PROJECT / "yolo11n.pt", help="Local starting weights")
    parser.add_argument("--name", required=True, help="Run name, e.g. disc-dog-v1")
    parser.add_argument("--project", type=Path, default=PROJECT / "outputs" / "training")
    parser.add_argument("--export-dir", type=Path, default=PROJECT / "models",
                        help="best.pt and its record are copied to <export-dir>/<name>/ (ignored by Git)")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--batch", type=int, default=4, help="Keep small for 1280 px on a 6 GB GPU")
    parser.add_argument("--device", default="0", help="CUDA index or 'cpu'")
    parser.add_argument("--freeze", type=int, default=10,
                        help="Freeze the first N layers (reduces overfitting on small datasets; 0 = none)")
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--close-mosaic", type=int, default=10)
    parser.add_argument("--lr0", type=float, default=.005)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if min(args.epochs, args.imgsz, args.batch, args.workers) < 1 or args.freeze < 0:
        parser.error("epochs, imgsz, batch and workers must be positive; freeze must be non-negative")
    if not args.base.is_file():
        parser.error(f"Base weights not found (no download is performed): {args.base}")
    run_dir = Path(args.project).resolve() / args.name
    if run_dir.exists() or (Path(args.export_dir) / args.name).exists():
        parser.error(f"Run '{args.name}' already exists; choose a new --name")
    try:
        resolved = Path(args.project).resolve() / f"{args.name}-dataset.yaml"
        counts = resolve_dataset(args.data, resolved)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Dataset check failed: {exc}", file=sys.stderr)
        return 1
    from ultralytics import YOLO
    import torch
    import ultralytics
    started = time.time()
    model = YOLO(str(args.base))
    kwargs = build_train_kwargs(args, resolved)
    model.train(**kwargs)
    best = Path(getattr(getattr(model, "trainer", None), "best", None) or run_dir / "weights" / "best.pt")
    if not best.is_file():
        print("Training finished without a best.pt; nothing exported", file=sys.stderr)
        return 1
    tuned = YOLO(str(best))
    metrics = {}
    for split in ("val", "test"):
        if counts.get(split):
            result = tuned.val(data=str(resolved), split=split, imgsz=args.imgsz, device=args.device, plots=False)
            metrics[split] = {"mAP50": float(result.box.map50), "mAP50-95": float(result.box.map),
                              "precision": float(result.box.mp), "recall": float(result.box.mr),
                              "per_class_mAP50": {EXPECTED_NAMES[int(c)]: float(v)
                                                for c, v in zip(result.box.ap_class_index, result.box.ap50)}}
    export = Path(args.export_dir).resolve() / args.name
    export.mkdir(parents=True)
    shutil.copy2(best, export / "best.pt")
    record = {"name": args.name, "created_unix": started, "elapsed_seconds": time.time() - started,
              "base_weights": str(args.base), "base_sha256": sha256(args.base),
              "best_sha256": sha256(export / "best.pt"), "dataset_yaml": str(resolved),
              "image_counts": counts, "ultralytics": ultralytics.__version__, "torch": torch.__version__,
              "train_arguments": kwargs, "metrics": metrics,
              "note": "Metrics are on this dataset's own val/test splits; they are not general accuracy."}
    (export / "training-record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"weights": str(export / "best.pt"), "metrics": metrics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
