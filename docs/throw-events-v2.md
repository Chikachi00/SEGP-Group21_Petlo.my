# 投掷事件分析第二版

更新日期：2026-10-12。新增独立事件层，原检测、狗追踪、飞盘追踪与恢复、联合分析、原视频和 URS 不改动。视频叠加与新版回看页使用英语。

## 当前实现与边界

新增 `cv/throw_events.py`、`cv/analyze_throw_events.py`、`cv/build_throw_event_review.py` 和 `tests/test_throw_events.py`。

`throw_id` 是一个待核查的事件过程编号，与 `disc_id` 分开。程序把本次观测到的移动、向狗靠近和接触后的过程关联起来；同一过程中的多段移动合并，人在手中移动飞盘及狗叼盘返回的近身移动尽量抑制。新的持续离人运动可以为同一飞盘 ID 建立下一次事件。它仍可能漏分、误分和误关联，编号不是已确认的物理投掷。

阶段为 `Ready / Flight candidate / Approaching dog / Contact pending / Carry candidate / Ground candidate / Unobserved`。没有观测的位置不填成检测成功。页面用于离线复查，显示的结果是事后候选，不能作为实时接盘报警。

## 怎样测试与回看

```powershell
# Run these commands from the repository root
Start-Process 'outputs\throw-events-v2\index.html'
```

进入一个角度，选择 `throw-001` 等事件，回看起止过程；滑块定位真实源帧，`Next source frame` 逐帧前进。绿色实框表示狗观测，蓝色实框表示飞盘观测，`VISUAL` 为局部外观观测；预测默认隐藏，黄色虚框只作为回看参考。原始源时间来自索引，不用播放器秒数测量变帧率视频。

选择有接触证据的事件后，下面显示最多 8 张原分辨率局部图，每张有全景参考链接。检查一轮最多打开 8 张独立图片，只讨论一个事件窗口。局部图按实测狗框扩展 25%，并包含本帧相关飞盘框；狗未观测到的帧不以预测框生成裁剪。局部图没有重新执行 YOLO，也没有定位嘴部。

## 再运行

```powershell
.\.venv\Scripts\python.exe cv\analyze_throw_events.py `
  --joint-dir outputs\joint-analysis\front-v1 `
  --detections outputs\front_disc_enhanced.jsonl `
  --output-dir outputs\throw-events-v2\front-v1 `
  --preview outputs\joint-previews\Landscape_Tripod_FrontView.mp4

.\.venv\Scripts\python.exe cv\analyze_throw_events.py `
  --joint-dir outputs\joint-analysis\side-v1 `
  --detections outputs\multi-angle-check\side_disc_enhanced.jsonl `
  --output-dir outputs\throw-events-v2\side-v1 `
  --preview outputs\joint-previews\Landscape_Tripod_SideView.mp4

.\.venv\Scripts\python.exe cv\analyze_throw_events.py `
  --joint-dir outputs\joint-analysis\handheld-v1 `
  --detections outputs\multi-angle-check\handheld_disc_enhanced.jsonl `
  --output-dir outputs\throw-events-v2\handheld-v1 `
  --preview outputs\joint-previews\Portrait_Handheld.mp4

.\.venv\Scripts\python.exe cv\build_throw_event_review.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

相同输入、参数和代码先校验缓存再复用。输入、原视频或缓存改变时明确报错，使用新的根目录保存实验，例如 `outputs/throw-events-v3/front-v1`；三个角度完成后给汇总入口传 `--root outputs/throw-events-v3`。原追踪结果不需要重跑或覆盖。

## 事件证据

- **投出线索**：固定镜头下，飞盘先在检测到的人框附近出现，再持续离开人框至少 0.12 秒并移动至少两个盘框对角线，形成疑似投出。人框只是空间参照，未识别手部或验证投掷者身份。没有观察到离人过程时保留 `flight_motion_candidate`，不假设真正看到了投出。
- **事件关联**：沿真实时间读取所有观测，默认最长过程 8 秒，超过 0.35 秒没有飞盘观测则停止自动延续。飞盘换 ID 时，先检查不重叠的观测时间、位置、尺寸和运动方向，再对真实原帧端点的 HSV 颜色直方图比较。时差最多 0.35 秒，颜色相似度默认至少 0.9，前后候选必须各自唯一；缺少外观或匹配有歧义时不续接。颜色不能证明物理身份，每条续接仍需复查，短缺失帧保持 `Unobserved`。手持禁用跨 ID 续接。
- **接触线索**：同一个狗 ID 此前与盘有明确分离，随后出现至少 3 次、至少 0.08 秒的近身观测。整狗框重叠不是嘴部接触。
- **接盘候选**：接触开始后 0.8 秒内，同狗同盘近身观测持续至少 0.3 秒、至少 5 个样本，狗和盘都移动且相对位移较小，并有至少两个在时间上分开的模型观测。允许短缺失，缺失不增加样本；纯预测或纯局部外观序列不能满足模型观测条件。输出 `catch_candidate`，不输出已确认接盘。地上拾盘后同行也可能产生相似现象。
- **失误候选**：必须提供明确核查过的原帧落地记录，随后盘持续静止至少 0.3 秒且与观测到的狗分离，才输出 `miss_candidate`。没有落地记录时，静止、遮挡或盘消失均不足以判断失误。若落地在共同移动之前，按落地后取回处理，不把取回误当作空中接盘证据。
- **不确定**：释放未观测、接触后缺少持续证据、长缺失、视频结束等保留原因。手持暂未补偿相机移动，事件结果始终保持 `uncertain`。

这些阈值是可配置的原型规则，尚未用独立人工标签校准，不能解释成事件概率。

## 落地记录与人工核查

每个角度有 `ground-contact-template.json`。复制后，仅向 `ground_contacts` 添加已检查的真实源帧，例如：

```json
{
  "disc_id": "disc-026",
  "frame_id": 1500,
  "verified": true,
  "reviewer": "Actual reviewer name",
  "notes": "Ground contact visible on this original frame."
}
```

上述编号只是格式示例，不是真实落地标签。保留模板的 `video_id` 和 `source_sha256`，以保证来源一致；帧上必须有对应飞盘实测框。然后给分析入口传 `--ground-evidence <复制后填写的文件>`，并选择新的输出目录。`example_only` 不参与判断。

`manual-review-template.json` 为每个事件保存审核人、证据源帧、是否确认投掷和最终结果的空记录。先复制再填写。该版没有自动导入最终审核结果、计算接盘率或评分，以免把候选当作已确认事件。所有自动结果的 `review_status` 为 `unreviewed`，`verified_outcome`、`confirmed_throw`、`event_probability` 均为空。

## 输出与本次验证

正式结果位于 `outputs/throw-events-v2/{front,side,handheld}-v1/`：

| 文件 | 内容 |
|---|---|
| `events-v2.json` | 事件编号、关联盘 ID、候选结果、投出/接触/共同移动/落地证据及不确定原因 |
| `event-states.jsonl` | 所有真实源帧的事件阶段、狗/盘是否观测，保持缺失为空 |
| `diagnostics.json` | 跨 ID 续接提议、接受/拒绝原因及抑制的运动片段 |
| `crop-index.json` | 接触局部图、全景参考、真实时间、裁剪坐标与缩放映射 |
| `contact-crops/`、`link-audit/` | 按需生成的原分辨率局部证据 |
| `index.html` | 英语视频叠加、事件跳转、逐帧检查和局部图入口 |
| `summary.json` | 来源、参数、文件哈希、运行指标和限制 |

| 视频 | 分析源帧 | 事件候选 | 接盘候选 | 不确定 | 合并的后续运动段 | 抑制的运动候选 |
|---|---:|---:|---:|---:|---:|---:|
| 正面 | 2200 | 4 | 2 | 2 | 2 | 2 |
| 侧面 | 2163 | 4 | 0 | 4 | 3 | 2 |
| 手持 | 179 | 2 | 0 | 2 | 2 | 0 |

共分析 4542 帧，生成 32 张原分辨率接触局部图及对应全景参考。正面、侧面各 4 个候选不是已验证的 4 次投掷；两视角也可能是同一组投掷，不能相加。本次没有提供落地标签，因此没有生成失误候选；不能把这理解为没有失误。

正面第一事件抽查 3.700、3.816667、4.083333、4.316667 秒，局部图可看到飞盘接近狗以及随后出现在狗嘴附近，与接盘候选一致。此抽查仍不能代替独立人工真值。第二事件 10.633333–13.083333 秒保留不确定，没有把飞盘丢失直接判为接盘。

这三段已有局部恢复追踪中，没有跨 ID 续接提议满足初步几何门限，因此实际接受续接为 0；续接能力通过换 ID、短缺失、颜色不匹配和多候选的测试验证，尚未在这些真实样本上证明效果。

首次侧面生成截图约 75 秒，主要是从 4K HEVC 原视频解码所选原帧，不是重新跑模型；再次运行复用校验通过的缓存。不能将该耗时作为最终系统实时性能。

103 项回归测试通过，其中新增 18 项，覆盖释放、连续事件、同盘再次投出、共同移动、缺失/预测排除、叼盘返回且狗漏检、换 ID 唯一续接/歧义拒绝、颜色证据、手持限制、落地核查来源、变帧率时间、原尺寸裁剪、缓存损坏与旧数据保持。`validation.json` 记录真实源帧、时间、裁剪及原文件校验；142 个已有文件保持原校验值，四段原视频内容不变。

下一步用人工审核记录评估漏分、重复、错误接盘候选及不确定比例，再校准门限、加强嘴部/落地定位和引入可核查的统计。暂不宣称准确率或输出评分。
