# 狗与飞盘联合分析第一版

更新日期：2026-10-12。独立新增模块，保留检测、狗追踪、飞盘追踪第一版、局部恢复版、原视频和 URS。

## 本次实现

- `cv/joint_analysis.py`：仅用观测框计算狗与飞盘的二维框间距、短窗口像素运动、靠近证据及候选事件。
- `cv/analyze_dog_disc.py`：校验追踪结果的文件哈希、源视频内容、检测来源、原尺寸坐标与完整帧覆盖；生成每帧联合状态、候选、人工核查模板和离线回看页。
- `cv/prepare_joint_previews.py`：独立生成最长边不超过 1280 的干净 H264 预览，保留每个原帧，播放时钟改为标称帧率；不插帧、不重新跑检测、不覆盖旧视频。方向沿用 FFmpeg 的显示方向。验收输出帧数、尺寸、标称播放帧率及前后源内容哈希。
- `cv/build_joint_analysis_review.py`：汇总正面、侧面、手持三个完整结果，提供独立入口。
- `tests/test_joint_analysis.py`：14 项新测试；与原有 71 项组成 85 项回归测试。

这是事件分析的可核查原型，尚未自动确认成功接盘、失误、比赛投掷次数或得分。候选数量不是准确率或实际投掷次数。

## 怎样回看

在 PowerShell 中运行：

```powershell
# Run these commands from the repository root
Start-Process 'outputs\joint-analysis\index.html'
```

进入某个角度，点击一个候选窗口，视频跳到候选前约一秒。滑块按源帧定位，“下一源帧”每次前进一个真实帧。显示的原始时间来自索引，不能拿播放器秒数直接作为变帧率源视频的测量时间。逐帧定位选取该帧在浏览视频中的时间区间中点，避免播放器对微秒舍入导致反复显示上一帧。

绿色实框是狗的观测，蓝色实框是飞盘的观测，`VISUAL` 表示局部外观观测，模型置信度仍为空。预测框默认隐藏；勾选后显示黄色虚框，预测位置不参与距离、运动或事件证据。干净预览没有提前画入任何检测/预测框，页面叠加层可独立控制显示。

原尺寸算法输入仍为原视频；浏览预览和这份联合分析都不替代原帧检测。页面依赖相邻的 `outputs/joint-previews/` 预览文件，移动资料时保持目录关系。

## 重新运行

已生成的三个角度可直接读取；相同输入会校验缓存，不重新运行 YOLO。

```powershell
# 一次性生成或校验三个干净预览
.\.venv\Scripts\python.exe cv\prepare_joint_previews.py

.\.venv\Scripts\python.exe cv\analyze_dog_disc.py `
  --dog-dir outputs\dog-tracking\front-v1 `
  --disc-dir outputs\disc-tracking-v2\front-v1 `
  --output-dir outputs\joint-analysis\front-v1 `
  --preview outputs\joint-previews\Landscape_Tripod_FrontView.mp4

.\.venv\Scripts\python.exe cv\analyze_dog_disc.py `
  --dog-dir outputs\dog-tracking\side-v1 `
  --disc-dir outputs\disc-tracking-v2\side-v1 `
  --output-dir outputs\joint-analysis\side-v1 `
  --preview outputs\joint-previews\Landscape_Tripod_SideView.mp4

.\.venv\Scripts\python.exe cv\analyze_dog_disc.py `
  --dog-dir outputs\dog-tracking\handheld-v1 `
  --disc-dir outputs\disc-tracking-v2\handheld-v1 `
  --output-dir outputs\joint-analysis\handheld-v1 `
  --preview outputs\joint-previews\Portrait_Handheld.mp4

.\.venv\Scripts\python.exe cv\build_joint_analysis_review.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

输入或参数变化、代码变化、缓存文件损坏时明确报错，使用新的独立输出目录，例如 `outputs/joint-analysis-v2/front-v1`，其余角度放在相同新根目录，再给回看汇总入口传 `--root outputs/joint-analysis-v2`。该入口使用每角度的 `*-v1` 子目录名称，但根目录可代表任何实验版本。不要手工改自动结果或删除旧追踪输出来强行复用缓存。

## 分析规则与证据范围

狗、飞盘、视频索引必须覆盖整个相同视频，源帧编号、真实 `t_sec`、`pts_sec` 逐帧完全一致。窗口运行、不同来源或改变后的原视频会拒绝分析。当前要求飞盘局部恢复版的 `measurement_source`，不自动将旧版未知来源当成模型观测。

默认只在最近 0.25 秒的真实飞盘观测中计算位移，需要至少 3 个样本、至少 0.12 秒跨度。观测间隔超过 0.12 秒清除运动历史。超过 `max(1.5 × 飞盘框对角线, 0.008 × 画面对角线)` 的位移是移动候选；不足则标记静止或慢速。像素速度是这个窗口两端的平均二维中心位移，不是瞬时速度或真实米每秒。

狗与飞盘都必须在当前帧有实测框才输出框间距。距狗框不超过狗框对角线的 0.08 倍是近狗候选；运动窗口两端都观测到同一个狗 ID，且框间距下降至少 0.15 倍狗框对角线，才给出向狗靠近候选。整只狗的框不等于嘴部，二维框重叠可能只是投影重合。

连续移动至少 0.18 秒形成 `disc_motion_candidate`。固定镜头下，同一 ID 此前还存在至少 0.2 秒静止/慢速证据时，给出 `throw_candidate`；这是疑似投掷，移动的人手持飞盘等也可能产生误候选。手持一律保留移动候选，不升级为疑似投掷，因为尚未补偿镜头运动。

近狗观测至少 3 次并持续至少 0.08 秒，且与同一飞盘 ID 的移动候选相交或在移动结束后 0.5 秒内，才生成 `contact_candidate`。这里允许短缺失，缺失本身不增加实测样本；候选时间跨度可能包含这些缺失。接触后 0.3 秒内若有观测，记录是否出现同狗同盘的几何同向移动；没有观测则明确记录丢失。两者都不能自动确认狗叼住盘。已经叼盘返回的狗也可能反复触发近狗候选。

所有事件的 `review_status` 初始为 `unreviewed`，`outcome` 为 `uncertain`，`model_probability` 为空。运动与几何规则的通过不能解释为模型给出的事件概率。没有嘴部定位、人工真值、落地证据或经过确认的事件定义，不能将丢失判为接盘或失误。

不同飞盘 ID 不自动合并，漏检、交叉或误接可能切断/交换 ID；一个物理投掷可对应多个移动或接触候选。固定正面、侧面视频也可能是同一次投掷，候选不能跨视频相加或直接用于独立训练/测试划分。

## 输出

每个角度在 `outputs/joint-analysis/{front,side,handheld}-v1/` 内保存：

| 文件 | 用途 |
|---|---|
| `joint-states.jsonl` | 全部源帧，狗/盘观测与预测分开，距离、运动、阶段和来源 |
| `events.json` | 候选起止源帧、真实时间、前后回看范围、证据样本和不确定原因 |
| `manual-review-template.json` | 人工核查空模板，复制后填写，不自动写回算法结果 |
| `summary.json` | 来源、参数、哈希、运行指标和限制；确认次数及接盘率为空 |
| `index.html` | 独立视频回看，源帧滑块、逐帧按钮、候选跳转 |

`outputs/joint-analysis/index.html` 汇总入口；`audit/` 保存少量原视频抽查截图、缩放映射和验证记录。每角度只抽查 4 个源帧，不默认把全部图片给模型。中间页实验保留在 `joint-analysis-initial/`、`joint-analysis-before-clean-preview/`；正式入口使用 `joint-analysis/`。

人工核查：先复制模板，例如 `manual-review-user.json`，记录审核人、真实源帧、是否确认投掷、`catch/miss/uncertain/false_candidate` 和说明。该版只提供模板，不导入人工决定或自动统计，避免直接把候选当作已确认结果。下一步实现审核结果导入、关联完整投掷与可核查统计。

## 本次样本验证

| 视频 | 源帧数 | 狗/盘同帧观测 | 移动候选 | 疑似投掷 | 疑似接触 |
|---|---:|---:|---:|---:|---:|
| 正面 | 2200 | 1222 | 6 | 2 | 3 |
| 侧面 | 2163 | 1892 | 8 | 1 | 5 |
| 手持 | 179 | 92 | 4 | 0 | 0 |

合计对齐 4542 帧。上述是程序运行计数，不是精确率、召回率或比赛结果。手持没有接触候选不代表没有接盘：接近盘的阶段狗的检测已存在缺失。

正面第二次空中飞盘 `disc-015`：自动找到 10.650–12.733333 秒的移动窗口，124 次观测包括 74 次保存检测、48 次局部外观、2 次局部 YOLO，38 次向狗靠近证据。回看范围 9.650–13.733333 秒。它仍保留为移动候选，没有强制把没有看清的接盘结果填为成功。

本次回归测试覆盖真实变帧率、预测排除、狗缺失、退役 ID、身份切换、静止背景、接近后消失、外观观测来源、来源/时间/坐标错误、完整输出、缓存和页面保护。干净预览验证三角度全部帧数和显示尺寸；截图使用原视频真实帧，不能把缩图视觉判断当作定位真值。
