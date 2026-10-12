"""Human and Codex entry points; no network requests or embedded source videos."""
from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote


def write_guides(root, manifest):
    root = Path(root).resolve()
    lines = [
        "# Codex 视频读取指南", "",
        "这份资料包从真实视频帧生成。原视频未改动，抽帧与候选排序不调用 GPT 或外部 API。",
        "模型读取图片、摘要和写代码仍会使用额度；不能按原视频 MB 推算额度。", "",
        "## 首次读取", "",
        "1. 先读取 manifest.json，检查每段视频 status；失败视频不得默默忽略。",
        "2. 仅打开下面每段视频的 overview.jpg，共最多四张图集、20个画面。",
        "3. 图集只用于导航。需要判断小飞盘时，打开对应独立截图，必要时按原尺寸裁切。",
        "4. 一次只分析一个问题，每批最多打开8张独立图片；不要遍历所有图片或把原片转成base64。", "",
        "## 视频入口", "",
    ]
    cards = []
    reading_plan = {"schema_version": 1, "initial_image_budget": 4, "detail_image_budget": 8,
                    "initial_overviews": [], "initial_frame_count": 0, "candidate_batches": [],
                    "instruction": "Read at most four overview images, then choose one candidate batch of at most eight images."}
    names = {"Landscape_Tripod_FrontView": "正面固定机位", "Landscape_Tripod_SideView": "侧面固定机位",
             "Portrait_Handheld": "竖屏手持", "Setup": "拍摄环境参考"}
    for video in manifest["videos"]:
        video_id = video["id"]
        title = names.get(video_id, video_id)
        safe_title = html.escape(title)
        lines.append(f"- **{video_id}**：{video['status']}；角色 {video['role']}。")
        if video["status"] != "complete":
            error = str(video.get("error") or "未知错误")
            lines.append(f"  - 解码失败：{error}")
            cards.append(f'<section class="card"><h2>{safe_title}</h2><p class="bad">处理失败</p><pre>{html.escape(error)}</pre></section>')
            continue
        overview = video["paths"]["overview"]
        reading_plan["initial_overviews"].append({"video_id": video_id, "path": overview})
        reading_plan["initial_frame_count"] += video["overview_count"]
        lines.append(f"  - 图集：[overview]({overview})；帧索引：{video['paths']['frame_index']}；图片索引：{video['paths']['image_index']}。")
        lines.append(f"  - 显示原尺寸：{video['width']}×{video['height']}；{video['duration']:.3f}秒；完整验证{video['frames_count']}源帧。")
        windows = json.loads((root / video["paths"]["candidates"]).read_text(encoding="utf-8"))
        images = json.loads((root / video["paths"]["image_index"]).read_text(encoding="utf-8"))
        video_directory = (root / video["paths"]["image_index"]).parent
        window_html = []
        for window in windows:
            candidates = [item for item in images if window["id"] in item.get("window_ids", [])]
            if len(candidates) > 8:
                indices = sorted({round(index * (len(candidates) - 1) / 7) for index in range(8)})
                candidates = [candidates[index] for index in indices]
            figures = []
            batch_images = []
            for image in candidates:
                relative = (video_directory / image["path"]).relative_to(root).as_posix()
                url = quote(relative, safe="/")
                batch_images.append({**image, "path": relative})
                figures.append(f'<figure><a href="{url}" target="_blank"><img loading="lazy" src="{url}" alt="候选源帧"></a><figcaption>{image["t_sec"]:.3f}s · 帧 {image["frame_id"]}</figcaption></figure>')
            reading_plan["candidate_batches"].append({"video_id": video_id, "window_id": window["id"],
                                                     "start_sec": window["start_sec"], "end_sec": window["end_sec"], "images": batch_images})
            window_html.append(f'<details><summary>候选片段 {window["start_sec"]:.3f}–{window["end_sec"]:.3f} 秒</summary><p>按运动变化推荐，尚未确认是投掷、接盘或跟踪错误。</p><div class="frames">{"".join(figures)}</div></details>')
        warnings = ''.join(f'<li>{html.escape(str(warning))}</li>' for warning in video.get("warnings", []))
        overview_url = quote(overview, safe="/")
        subtitle = f'{video["duration"]:.2f} 秒 · {video["width"]}×{video["height"]} · {video["frames_count"]} 个源帧'
        cards.append(f'<section class="card"><h2>{safe_title}</h2><p>{subtitle}</p><a href="{overview_url}" target="_blank"><img class="overview" src="{overview_url}" alt="{safe_title} 时间概览"></a>{"".join(window_html)}<details><summary>索引与说明</summary><p>视频 ID：<code>{html.escape(video_id)}</code></p><p><a href="{quote(video["paths"]["frame_index"],safe="/")}">真实帧时间索引</a> · <a href="{quote(video["paths"]["image_index"],safe="/")}">图片索引</a></p><ul>{warnings}</ul></details></section>')
    lines.extend([
        "", "## 精查与坐标", "",
        "- reading-plan.json 列出首次图集和每个候选的最多8张代表图；不要一次打开所有候选批次。",
        "- inspect-window 的时间使用源帧索引 t_sec，起点含、终点不含；pts_sec 保存原始PTS。",
        "- sampling=source 保留窗口内所有真实源帧；sampling=10 只选择真实帧，不插帧、不补重复帧。",
        "- --frame-id 指定单帧；--tiles 要同时指定 --frame-id，生成4×4、每格边缘扩展10%的原像素局部图。",
        "- --boxes 接受 [{frame_id,bbox:[x1,y1,x2,y2],label?}]；框必须使用显示方向原尺寸，四周扩25%上下文。",
        "- 回映射：original_x=crop[0]+image_x/scale_x；original_y=crop[1]+image_y/scale_y。crop=[x,y,width,height]。",
        "- 竖屏已按显示矩阵统一方向。旋转后坐标和编码坐标不同，不能直接混用。", "",
        "## 算法结果复盘", "",
        "1. 算法逐帧读取原视频，输出 tracking JSONL；字段规范见工具 README。",
        "2. review-results 验证原片内容、时间与坐标，优先选择 missing、低置信度和位置跳变处；不足则用运动候选补位。",
        "3. 每窗口最多8张代表带框图；HTML回放使用连续源帧和真实时间间隔，未提交结果的帧会明确标记。",
        "4. 修改算法后重跑同样本，用上一版 report.json 比较；不同来源或覆盖范围不作直接比较。",
        "5. 没有人工真值时，不把诊断计数称为准确率，不用GPT判断充当精确轨迹真值。", "",
        "## 样本限制", "",
        "- 固定机位和手持场景分别查看；手持相机运动可能导致候选误选。",
        "- 四段短视频只能进行样本验证。正侧面若为同一次投掷，训练/评估必须归入同一拍摄组。",
        "- 像素位移不等于真实距离或米/秒；需要场地标定才能测量。",
        "- 旧WPF预览没有可靠的时间定位，不属于本资料包。", "",
    ])
    (root / "CODEX_GUIDE.md").write_text("\n".join(lines), encoding="utf-8")
    (root / "reading-plan.json").write_text(json.dumps(reading_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    document = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>飞盘犬 · 视频资料包</title>
<style>body{margin:0;background:#f3f5f8;color:#182333;font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1200px;margin:40px auto;padding:0 24px}h1{font-size:32px;margin-bottom:8px}h2{font-size:21px}.intro{color:#536174;max-width:900px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.card{background:white;padding:22px;border-radius:18px;border:1px solid #dde3eb}.overview{width:100%;display:block;border-radius:8px}.frames{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}figure{margin:0}figure img{width:100%;max-height:260px;object-fit:contain;background:#eee}figcaption{font-size:13px;color:#59687a}details{border-top:1px solid #e6eaf0;padding-top:14px;margin-top:16px}summary{cursor:pointer;color:#2457a5;font-weight:600}a{color:#2457a5}pre{white-space:pre-wrap;overflow-wrap:anywhere}.bad{color:#b42318}code{font-size:13px;overflow-wrap:anywhere}@media(max-width:800px){.grid{grid-template-columns:1fr}main{padding:0 14px}}</style>
<main><h1>飞盘犬 · 视频资料包</h1><p class="intro">四个视角的真实时间概览。先看全景，再展开一个候选片段；点击图片可以单独查看。候选片段按运动变化推荐，需要结合原视频和算法结果确认。</p><p class="intro">原视频保留在电脑上。图集用于导航，小飞盘需要独立画面或原尺寸局部图。每轮只分析一个问题，每批最多读取八张图片。</p><p><a href="CODEX_GUIDE.md">Codex 读取指南</a> · <a href="manifest.json">视频清单</a></p><div class="grid">CARDS</div><p class="intro">当前资料包提供样本验证材料，不代表已经完成追踪算法或证明识别准确率。</p></main></html>'''.replace("CARDS", "".join(cards))
    (root / "index.html").write_text(document, encoding="utf-8")
