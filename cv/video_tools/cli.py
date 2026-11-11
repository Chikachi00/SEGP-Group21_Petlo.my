"""Small CLI: source videos never become output paths."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="本地视频资料包：真实时间索引、分层抽帧、轨迹结果复盘")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="完整解码并生成概览和候选窗口")
    prepare_parser.add_argument("--source", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    prepare_parser.add_argument("--force", action="store_true")
    prepare_parser.add_argument("--no-review-artifacts", action="store_true",
                                help="Validate all source frames and save indexes without review JPEGs, sheets or HTML")
    inspect_parser = commands.add_parser("inspect-window", help="提取真实源帧和按需局部图")
    inspect_parser.add_argument("--pack", required=True, type=Path)
    inspect_parser.add_argument("--video-id", required=True)
    inspect_parser.add_argument("--start", required=True, type=float)
    inspect_parser.add_argument("--end", required=True, type=float)
    inspect_parser.add_argument("--sampling", choices=("source", "10"), default="source")
    inspect_parser.add_argument("--frame-id", type=int)
    inspect_parser.add_argument("--tiles", action="store_true")
    inspect_parser.add_argument("--boxes", type=Path, help="可选 JSON 框列表；坐标使用原尺寸显示方向")
    review_parser = commands.add_parser("review-results", help="验证轨迹结果并生成失败证据和版本对比")
    review_parser.add_argument("--pack", required=True, type=Path)
    review_parser.add_argument("--results", required=True, type=Path)
    review_parser.add_argument("--previous", type=Path, help="上一版 report.json 或复盘目录，用于校验同源与覆盖范围")
    review_parser.add_argument("--processing-seconds", type=float)
    default_tools = Path(__file__).resolve().parents[2] / "tools" / "ffmpeg"
    for command in (prepare_parser, inspect_parser, review_parser):
        command.add_argument("--ffmpeg-dir", type=Path, default=None, help=f"工具目录；默认搜索环境变量/PATH/工作区 {default_tools}")
    args = parser.parse_args(argv)
    try:
        from .media import Toolchain
        import os
        tools_dir = args.ffmpeg_dir or os.environ.get("VIDEO_TOOLS_FFMPEG_DIR")
        if tools_dir is None and default_tools.is_dir():
            tools_dir = default_tools
        tools = Toolchain.discover(tools_dir)
        writable_packet = args.output if args.command == "prepare" else args.pack
        synced_sources = Path(__file__).resolve().parents[2] / "sources"
        if writable_packet.resolve().is_relative_to(synced_sources.resolve()):
            raise ValueError("资料包输出不能位于只读同步 sources/ 目录中。")
        if args.command == "prepare":
            from .prepare import prepare
            report = prepare(args.source, args.output, tools, force=args.force,
                             review_artifacts=not args.no_review_artifacts)
            if not args.no_review_artifacts:
                from .guide import write_guides
                write_guides(args.output, report)
            completed = [video for video in report["videos"] if video["status"] == "complete"]
            print(json.dumps({"manifest": str((args.output / "manifest.json").resolve()),
                              "complete": len(completed), "failed": len(report["videos"]) - len(completed),
                              "videos": [{"id": video["id"], "status": video["status"], "cached": video.get("cached", False),
                                          "frames_count": video.get("frames_count"), "error": video.get("error")} for video in report["videos"]]}, ensure_ascii=False, indent=2))
            return 0 if len(completed) == len(report["videos"]) and completed else 1
        if args.command == "inspect-window":
            from .inspect import inspect_window
            boxes = json.loads(args.boxes.read_text(encoding="utf-8-sig")) if args.boxes else None
            report = inspect_window(args.pack, args.video_id, args.start, args.end, tools,
                                    sampling=args.sampling, tiles=args.tiles, frame_id=args.frame_id, bboxes=boxes)
            summary = {key: report[key] for key in ("video_id", "output_dir", "report_path", "cached")}
            summary.update(frames=len(report["images"]), crops=len(report["crops"]), batches=len(report["batches"]), reading_limit=8)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        from .review import review
        report = review(args.pack, args.results, tools, previous_path=args.previous, processing_seconds=args.processing_seconds)
        # Avoid flooding model context with full frame records or results rows.
        summary = {key: value for key, value in report.items() if key in {"status", "render_errors", "report_path", "output_dir", "paths", "metrics", "comparison", "warnings", "cached"}}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if report.get("status") == "complete" else 1
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"视频工具失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
