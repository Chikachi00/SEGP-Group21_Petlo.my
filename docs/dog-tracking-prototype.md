# 狗追踪第一版：实现与验证

更新日期：2026-10-12。代码已加入 SEGP GROUP21；原视频保持只读。

## 已实现

`cv/track_dog_video.py` 读取已有逐帧检测，不重新运行 YOLO；`cv/dog_tracker.py` 根据真实源时间、位置和框大小关联一只主要的狗。默认需要 3 次相邻且一致的检测才建立 ID。多个候选无法明确区分时保留缺失状态，不强制接轨迹。

绿色实框表示本帧接受的检测，绿色线只连接连续实测点；漏检间隔不画成连续实测轨迹。黄色虚框表示恒定速度的短时预测，最多持续 0.25 秒。超过这个时间停止画预测框，但最多保留旧 ID 到最后实测后的 0.75 秒；在此期间重新匹配可以恢复同一 ID。超过 0.75 秒结束旧轨迹，后续需要重新确认。预测不会刷新最后实测时间。

这是一版保守的单狗关联工具，没有外观重识别、多狗身份验证或相机运动补偿。不能凭检测的 `person` 标签推断为狗。不同 ID 可能属于同一只狗；同一 ID 的持续输出也不能证明所有框都正确。

## 怎样测试

在 PowerShell 中运行：

```powershell
# Run these commands from the repository root

# 使用已保存的正面检测结果，不需要重新下载模型或跑检测
.\.venv\Scripts\python.exe cv\track_dog_video.py `
  --detections outputs\front_disc_enhanced.jsonl `
  --output-dir outputs\dog-tracking\front-v1

# 侧面
.\.venv\Scripts\python.exe cv\track_dog_video.py `
  --detections outputs\multi-angle-check\side_disc_enhanced.jsonl `
  --output-dir outputs\dog-tracking\side-v1

# 手持
.\.venv\Scripts\python.exe cv\track_dog_video.py `
  --detections outputs\multi-angle-check\handheld_disc_enhanced.jsonl `
  --output-dir outputs\dog-tracking\handheld-v1

# 查看本次已生成的三个完整回放及轨迹
Start-Process 'outputs\dog-tracking\index.html'

# 三个追踪输出生成后，可重建回放页与自动失败窗口
.\.venv\Scripts\python.exe cv\build_dog_tracking_review.py
```

相同输入和参数会验证缓存并复用。更改参数时使用新的输出目录，例如 `front-v2`，保留上一版用于对比。源文件内容、检测结果和报告、参数、工具版本或代码变化都会使缓存失效；缓存文件被修改也会明确报错。

窗口测试可以加 `--start 9 --end 10`，输出只覆盖检测结果中该时间段的连续真实帧。窗口内重新初始化 ID，不能用窗口 ID 直接推断与全片 ID 是同一轨迹。新视频先 `prepare` 再用 `detect_disc_video.py` 生成检测及配套 JSON 报告，然后交给这个入口。

## 输出及接口

每个输出目录包含：

| 文件 | 内容 |
|---|---|
| `tracked.mp4` | 原尺寸全帧回放，ID、状态、真实源时间及最近两秒实测轨迹 |
| `tracks.jsonl` | 可直接交给 `review-results` 的狗轨迹记录 |
| `states.jsonl` | 每帧实测、预测、初始化、丢失状态及关联原因 |
| `trajectory.csv` | 实测中心与预测中心分列保存，单位为像素 |
| `summary.json` | 状态计数、轨迹数、重新匹配次数、缺失窗口、耗时和文件哈希 |
| `frame-*.jpg` | 首、中、末及首次短预测/长丢失附近的少量核查图 |

JSONL 使用原视频源帧编号、真实 PTS 和方向统一后的原尺寸坐标。缺失位置留空。`tracks.jsonl` 中，预测帧仍为 `status: missing`，`bbox` 和 `confidence` 都是空；预测位置只在 `states.jsonl` 和 CSV 的预测列中。首次确认前 `dog-unassigned` 是占位符，不是真实身份。

MP4 使用标称播放帧率，不带原音频；变帧率视频的分析必须使用 JSONL/CSV 的真实时间，不能以播放器秒数代替。浏览页 H264 预览缩小到最长边 1280，保留全部源帧；视频旁的像素轨迹图可以隐藏预测点。

```powershell
.\.venv\Scripts\python.exe -m cv.video_tools review-results `
  --pack outputs\video-analysis-pack `
  --results outputs\dog-tracking\all-tracks-v1.jsonl
```

`all-tracks-v1.jsonl` 是本次三个动作视频的合并输出。单视频也可传各自 `tracks.jsonl`；复查工具可能用画面变化补充其他视频候选。下一版可增加 `--previous <上一版的report.json>`，在相同源文件及相同帧覆盖范围下对比。

## 本次完整运行

| 视频 | 总帧数 | 原检测含狗 | 接受的实测 | 短时预测 | 保留ID但停止预测 | 搜索/确认 | 建立轨迹 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 正面 | 2200 | 1737 | 1733 | 418 | 0 | 49 | 1 |
| 侧面 | 2163 | 1911 | 1907 | 207 | 47 | 2 | 1 |
| 手持 | 179 | 95 | 92 | 32 | 15 | 40 | 1 |

总共验证 4542 帧。正面和侧面确认后始终保留 `dog-001`，分别记录 126 次和 66 次漏检后的重新匹配。手持记录 8 次重新匹配，后段长缺失导致旧 ID 结束。计数是程序表现，不是准确率；没有人工真值，不能计算检测精确率或确认 ID 切换率。

抽查证据保存在 `outputs/dog-tracking/audit/`，每个角度只取 4 个源帧，每张都有源时间、编号和缩放/裁剪映射：

- 正面 9.35–9.617 秒：短缺失后恢复同一 ID。9.5 秒预测框已有偏移，不能作为真实位置用于速度或接盘判断。
- 侧面约 26.2–26.8 秒：超过 0.25 秒后停止预测，检测恢复时仍可在 0.75 秒限内恢复原 ID。
- 手持约 3.97–5.94 秒：持续缺失未被自动填成识别成功。约 5.1 秒孤立的一次检测不足以重新确认。

Setup 保持拍摄环境参考，不作为狗运动追踪验收视频。

## 验证和下一步

42 项自动测试通过，其中新增 11 项测试，覆盖短缺失、预测过期、长缺失重建、候选歧义、远处异常框、人狗类别隔离、真实变帧率时间、完整回放、坐标输出和缓存损坏。另修复旧抽帧工具的长选帧表达式限制：连续范围合并、稀疏范围平衡组合，并用 150 帧连续窗口和 180 帧稀疏窗口验证。三段原视频完整解码回放，检查输出帧数、尺寸和轨迹格式；前后源内容哈希一致。

这一版已提供狗的像素轨迹与状态，尚未实现飞盘追踪、真实距离/速度、投掷/接盘/失误识别或评分。下一步优先接入飞盘候选的时序关联，同时保留手持长缺失与预测偏移案例作为回归样本。事件判断只采用有证据的观测；持续缺失应允许输出“不确定”。
