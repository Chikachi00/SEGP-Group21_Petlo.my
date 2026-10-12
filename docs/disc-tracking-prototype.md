# 飞盘追踪第一版

更新日期：2026-10-12。新模块复用已保存的检测，不重新跑 YOLO；既有检测、狗追踪、文档和原视频保持不变。

## 已实现与边界

- `cv/disc_tracker.py` 按真实源时间关联多个飞盘候选。手持、地面和空中飞盘分别建立局部 ID，不指定唯一的“正在飞行的盘”。
- 默认连续两次相容检测后建立 `disc-001` 等 ID。按运动预测、中心位移、框面积变化进行一对一匹配；候选接近或两条轨迹争同一个框时拒绝强行匹配。
- 对高度包含、中心接近的局部裁剪重复框额外去重；这可能合并严重重叠的真实飞盘，需要人工核查。
- 蓝色实框及轨迹线表示接受的检测；黄色虚框表示最多 0.12 秒的短预测；灰色框表示尚未确认的候选。预测不刷新最后实测时间，不被导出为检测。轨迹线不连接漏检间隔。
- 超过 0.12 秒停止画预测；超过最后实测后 0.35 秒结束旧 ID。后续重新检测需确认并建立新 ID。离开画面的预测不强行压在画面边缘。
- 只提供局部几何连续性，没有外观重识别、相机运动补偿或完整物理身份保证。长缺失、突然转向和交叉仍可能造成断轨或串轨。持续误检也能建立 ID。
- 暂未实现投掷、接盘、失误、评分或真实距离/速度。地面盘的持续检测不能证明空中盘一直被追踪；不同 ID 也不等于不同投掷。

## 怎样查看与重跑

已有三个完整回放，可直接打开 `outputs/disc-tracking/index.html`。页面可选择一个 ID 看轨迹，并开关预测点。原尺寸视频用 VLC 打开；JSONL/CSV 才是分析用的真实源时间。浏览视频使用标称帧率、不含原音频，长边不超过 1280，但保留全部源帧。

在 PowerShell 中运行：

```powershell
# Run these commands from the repository root
Start-Process 'outputs\disc-tracking\index.html'

# 正面：复用已有增强检测
.\.venv\Scripts\python.exe cv\track_disc_video.py `
  --detections outputs\front_disc_enhanced.jsonl `
  --output-dir outputs\disc-tracking\front-v1

# 侧面
.\.venv\Scripts\python.exe cv\track_disc_video.py `
  --detections outputs\multi-angle-check\side_disc_enhanced.jsonl `
  --output-dir outputs\disc-tracking\side-v1

# 手持
.\.venv\Scripts\python.exe cv\track_disc_video.py `
  --detections outputs\multi-angle-check\handheld_disc_enhanced.jsonl `
  --output-dir outputs\disc-tracking\handheld-v1

# 三段结果均生成后，建立独立回看页
.\.venv\Scripts\python.exe cv\build_disc_tracking_review.py

# 所有自动测试（59 项）
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

相同输入和设置会校验缓存并复用，已有输出不被默默覆盖。改变参数时用新的目录，例如 `outputs/disc-tracking-v2/front-v1`；三个角度均完成后通过 `build_disc_tracking_review.py --root outputs/disc-tracking-v2` 建立另一版回看页。保留旧版用于比较。

支持 `--start 11.8 --end 12.5` 等半开时间窗口、`--confidence`、`--confirm-samples`、`--prediction-seconds` 和 `--identity-gap-seconds`。窗口从空状态初始化，窗口 ID 不能直接对应全片 ID。输入必须是 `detect_disc_video.py` 输出的连续 JSONL 及同名 JSON 报告，原视频须已建立资料包；普通 `detect_video.py` 的 MP4 不能直接作为追踪输入。

## 输出与复查接口

每个运行目录包含：

| 文件 | 内容 |
|---|---|
| `tracked.mp4` | 原尺寸、全部连续源帧的飞盘 ID 与状态回放 |
| `tracks.jsonl` | 兼容现有 `review-results` 的检测/缺失记录；同一帧可有多个 ID |
| `states.jsonl` | 每个源帧的候选、实测、预测、丢失及结束状态和拒绝原因 |
| `trajectory.csv` | 实测中心和预测中心分列，均为方向统一后的原图像素坐标 |
| `summary.json` | 参数、来源/代码/工具哈希、帧统计、每条短轨迹及耗时 |
| `frame-*.jpg` | 少量首中末及首次短预测、长缺失附近的核查图 |

`tracks.jsonl` 使用视频 ID、真实源帧编号、真实 `t_sec`、`label=disc`、ID、框、置信度及 `detected/missing`。预测帧的 `bbox`、`confidence` 为空，预测仅存于状态文件和 CSV 的预测列。没有确认轨迹的帧使用 `disc-unassigned` 缺失占位，确保完整帧覆盖；该占位符不是物理目标。每帧候选数、去重数、未分配数及容量拒绝数也记录在状态文件。

合并结果为 `outputs/disc-tracking/all-tracks.jsonl`。可运行：

```powershell
.\.venv\Scripts\python.exe -m cv.video_tools review-results `
  --pack outputs\video-analysis-pack `
  --results outputs\disc-tracking\all-tracks.jsonl
```

这会新建 `outputs/video-analysis-pack/reviews/<内容哈希>/` 下的诊断窗口，保留旧狗追踪复查。下一版可加 `--previous <上一版的report.json>`，比较相同源视频和帧覆盖范围的结果。诊断中的 missing、低置信度或跳变均为候选问题，不是已核实错误。原始检测框始终可以回查，未确认候选没有被删除出原检测文件。

## 本次验证

原有 42 项测试通过；新增 17 项测试覆盖多盘及顺序变化、高速小盘、真实变帧率时间、漏检恢复、预测/ID 到期、离开画面、远处跳点、人狗类别隔离、重复框、交叉歧义、容量、输入保护、缓存、完整回放与浏览时钟。全部 59 项通过，没有修改旧测试。

| 视频 | 完整源帧 | 原检测至少有一个盘 | 追踪至少有一个实测盘 | 至少有一个预测盘 | 建立短轨迹 |
|---|---:|---:|---:|---:|---:|
| 正面 | 2200 | 1661 | 1567 | 603 | 40 |
| 侧面 | 2163 | 2163 | 2142 | 743 | 51 |
| 手持 | 179 | 106 | 105 | 21 | 4 |

总计 4542 帧完整解码、方向/时间索引、输出帧数与尺寸、结果格式以及源内容哈希校验通过。帧状态可能重叠：同一帧可同时有实测盘、预测盘或丢失的另一条轨迹。以上统计不是精确率或召回率；尤其侧面的手持/地面盘会贡献很多实测帧。短轨迹数量反映几何关联及断轨，不是飞盘个数或投掷次数。

有限的人工抽查保存在 `outputs/disc-tracking/audit/`：每个角度一个窗口、4 张全景帧，另有实际检测盘的局部图及坐标映射。局部图保留原尺寸裁剪，并提供明确缩放的浏览版本。每批阅读不超过 8 张独立图片。

- 正面 11.8–12.4 秒：12.0、12.2、12.4 秒空中蓝盘保持 `disc-017`，手持盘为另一 ID；原像素局部核查可见蓝盘。
- 侧面 2.803–3.403 秒：浅色空中盘保持 `disc-006`，3 秒左右手持粉色盘有独立 ID。
- 手持 2.803–4.004 秒：2.803、3.003、3.203 秒蓝盘保持 `disc-004`；4.004 秒狗嘴边蓝盘仍可见，但已无实测/预测框，正确保留“丢失”而非编造识别成功。

现有复查工具验证合并结果 12238 条，覆盖三个动作视频的全部源帧；六个候选窗口均完成。0 个大跳变候选并不证明没有串轨，仍需标注几次完整投掷，核查同一物理盘的 ID 连续性、遮挡与交叉。

## 建议下一步

先人工核查完整动作，给盘标注“手持／飞行／狗嘴边／地面／不可见”，建立投掷片段和物理身份参考。再针对断轨、交叉及持续误检改进关联或检测。事件判断需要联合狗轨迹、飞盘轨迹和可见性证据；持续丢失应允许“不确定”，不能直接计为接盘或失误。
