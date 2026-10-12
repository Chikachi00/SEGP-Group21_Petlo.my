# 飞盘犬视频资料工具

这套工具让 Codex 根据真实时间定位视频画面、放大狗和飞盘，并查看追踪算法的失败片段。视频解码、抽帧和画面变化计算都在本地完成。工具不会自动调用 GPT 或上传视频。

原视频目录和项目的 `sources/` 只作为只读输入。资料包、缓存、裁剪图和算法报告写入独立输出目录；输出目录不能放进原视频目录。首次运行建议保持默认设置，先让 Codex 看四张概览图集，再按需查看一个窗口。

## 运行准备

需要 Python 3.10 或以上、Pillow、NumPy，以及同一便携发行版的 `ffmpeg.exe` 和 `ffprobe.exe`。普通 Python 可以安装 Pillow 和 NumPy；Codex 本机 Python 环境已检查到这两个库。

在 SEGP GROUP21 仓库根目录运行 PowerShell。普通 Python 可直接使用 `python`；此电脑也可以使用 Python 启动器，先设置：

```powershell
$videoPython = '.\.venv\Scripts\python.exe'
$videoSource = '<sample-video-directory>'
$videoPack = Join-Path (Get-Location) 'outputs\video-analysis-pack'
$videoFfmpeg = Join-Path (Get-Location) 'tools\ffmpeg\ffmpeg-n8.1-latest-win64-gpl-shared-8.1\bin'
```

`$videoFfmpeg` 应指向同时包含两个可执行文件的目录，以实际安装位置为准。每条命令可以传 `--ffmpeg-dir`；也可以设置 `$env:VIDEO_TOOLS_FFMPEG_DIR = $videoFfmpeg`。缺少工具会报错，不会默默切换到不可靠的视频读取方式。FFmpeg 正规下载入口为 [FFmpeg 官方下载页](https://ffmpeg.org/download.html)，Windows 构建选择官方链接的 BtbN。保持 HTTPS 证书验证，不绕过下载错误。

## 三个入口

### 1. `prepare`：建立可追溯的资料包

```powershell
& $videoPython -m cv.video_tools prepare --source $videoSource --output $videoPack --ffmpeg-dir $videoFfmpeg
```

处理每段视频时，工具先记录编码、尺寸、旋转、帧率及时间信息，再完整解码，并建立逐帧时间索引。图片时间来自实际源帧时间戳，不用帧号除以平均帧率，也不插入合成帧。输出包括：

- 视频清单及各视频成功或失败状态，包含工具版本和原文件内容指纹。
- 每秒约一张的全片浏览索引，浏览图长边不超过 1280 像素。
- 每段一张概览图集：正面和侧面各六张源帧，手持和 Setup 各四张，覆盖首尾。
- 每段动作视频最多两个不重叠的高变化候选窗口，每个约两秒，浏览采样约 10 fps；Setup 默认只作环境参考。
- 图片、源帧、真实时间和坐标映射，以及按每批最多八张组织的阅读索引。

高变化候选用于导航，不能直接当作投掷、接盘或失败标签。手持视频中的相机移动可能触发候选。重复运行会复用有效缓存；源内容、参数或工具版本改变时重做相应视频，缺失的资料图片会修复。需要全部重做时使用 `--force`。

生成后打开资料包的 `index.html` 查看四段概览及候选片段。Codex 的入口是 `CODEX_GUIDE.md` 和 `reading-plan.json`，后者明确首轮最多四张图集、每个候选批次最多八张图片。在此电脑上也可以从工作区用 `run-video-tools.cmd` 代替 Python 启动命令，例如 `run-video-tools.cmd prepare --source "<sample-video-directory>" --output "outputs\video-analysis-pack"`。

### 2. `inspect-window`：查看一个具体时间窗口

从资料包清单复制 `video_id`。时间单位为秒，使用原视频时间索引中的时间，不使用浏览图片的序号。

```powershell
& $videoPython -m cv.video_tools inspect-window --pack $videoPack --video-id '<video_id>' --start 8 --end 10 --sampling source --ffmpeg-dir $videoFfmpeg
```

`--sampling source` 提取该区间内所有真实源帧，保留原始尺寸；`--sampling 10` 约每 0.1 秒选择一张真实源帧，供快速浏览。一个区间可以在本地产生很多图片，但给 Codex 的批次索引每组最多八张，不默认把全部图片送给模型。

小飞盘在概览中不清楚时，先选择一个源帧编号，再生成原分辨率的 4×4 网格局部图：

```powershell
& $videoPython -m cv.video_tools inspect-window --pack $videoPack --video-id '<video_id>' --start 8 --end 10 --frame-id 480 --tiles --ffmpeg-dir $videoFfmpeg
```

网格之间保留少量重叠，并保存局部图与全景帧的对应关系。网格要求使用 `--frame-id` 选择一个源帧，避免一次产生大量局部图。程序接口还支持检测框局部图，在框四周扩展 25% 上下文。所有坐标均能还原到方向统一后的原尺寸画面。`frame_id` 是源帧编号，不是抽帧后的图片编号；指定帧必须属于所选时间窗口，窗口按起点包含、终点不包含选帧。

有检测框时，也可以将下面的列表保存成 JSON 文件，然后通过 `--boxes '.\results\boxes.json'` 传给 `inspect-window`。每个框的源帧必须在本次窗口选出的帧中；`label` 可省略。

```json
[{"frame_id":480,"bbox":[1120,420,1160,455],"label":"disc"}]
```

### 3. `review-results`：生成失败候选和版本对比

让你的追踪程序输出 JSONL 文件，每行一个目标在一个源帧上的结果。接入格式如下：

```json
{"video_id":"<video_id>","frame_id":480,"t_sec":8.008,"label":"disc","track_id":"disc-1","bbox":[1120,420,1160,455],"confidence":0.73,"status":"detected"}
{"video_id":"<video_id>","frame_id":481,"t_sec":8.025,"label":"disc","track_id":"disc-1","bbox":null,"confidence":null,"status":"missing"}
```

- `label` 为 `dog` 或 `disc`，`status` 为 `detected` 或 `missing`，`track_id` 标识算法轨迹。
- `frame_id` 和 `t_sec` 必须对应资料包中的源帧。不可用平均帧率自行推算时间。
- `bbox` 是 `[x1,y1,x2,y2]`，单位为方向统一后的原画面像素，不能直接填缩图或裁剪图坐标。检测框应具有正宽度和正高度，并落在画面范围内。
- `confidence` 在 0 到 1 之间，或为 `null` 表示没有提供。`missing` 的框必须填 `null`，置信度建议也填 `null`；工具允许缺失记录保留合法置信度，但不会将其计入 detected 的低置信度统计。不要填零框或编造位置。
- 缺失目标需要显式输出 `missing` 行。没有输出的帧不等于经过检查后确认缺失，也不能用于推断识别率。

```powershell
& $videoPython -m cv.video_tools review-results --pack $videoPack --results '.\results\tracking-v1.jsonl' --processing-seconds 14.2 --ffmpeg-dir $videoFfmpeg
# 从上条命令的 output_dir 取得上一版报告路径；这里替换真实生成的目录名。
$previousReview = Join-Path $videoPack 'reviews\<上一版目录名>\report.json'
& $videoPython -m cv.video_tools review-results --pack $videoPack --results '.\results\tracking-v2.jsonl' --previous $previousReview --processing-seconds 12.4 --ffmpeg-dir $videoFfmpeg
```

首次运行省略 `--previous`；对比时传上一版的 `report.json` 或其所在目录，而不是追踪 JSONL，因为报告中保存了可验证的来源签名和覆盖信息。工具优先推荐显式目标丢失、低置信度及异常跳变窗口，不足时用画面变化候选补足，并生成叠加截图、连续源帧回放及运行指标。回放为可在浏览器打开的 `playback.html`，按源帧时间间隔展示并绘制检测框，不生成带框 MP4。`--processing-seconds` 只填写本次算法处理输入的实际耗时，不填写抽帧或 GPT 阅读耗时。

版本间只在相同来源，以及相同视频、帧、目标类别和记录数量覆盖上做有效比较。轨迹 ID 可以重编号；不能把只处理少量容易帧的结果与全片结果直接比较。没有人工核查标签时，这些是运行指标和待核查候选，不是准确率或确认误检。真实误检、漏检和身份错误仍需人工核查。

## 给 Codex 的读取方式

初次可直接复制下面这段提示，并替换资料包路径：

> 请读取这个本地视频资料包的清单、读取指南和四张概览图集，了解飞盘犬场景。先不要打开全部抽帧。提出算法需要处理的可见难点，并选一个候选窗口深入检查。每批最多读取八张独立图片；小飞盘不清楚时使用局部图。所有观察必须引用视频 ID、源帧编号和真实时间，不把视觉猜测当作精确真值。

修改算法时可使用：

> 请读取本次追踪报告，先查看最严重的一个失败候选窗口及对应全景和局部图。区分已证实错误与自动提示，说明支持修改的画面证据。修改后用相同输入与覆盖重跑，对比目标缺失、低置信度、轨迹中断和耗时，并保留改善及退步案例。

建议每轮流程为：概览 → 在本地用原视频逐帧运行算法 → 阅读一个失败窗口 → 修改 → 在相同视频上复测。低频浏览图只用于定位，不能替代追踪算法输入。GPT 不承担精确标注真值；像素距离也不直接代表真实距离或速度，实际测量需要场地或相机标定。

正面、侧面如果记录同一次投掷，训练、验证、测试数据划分时必须放在同一组。这四段短样本适合验证流程和暴露问题，不能代表完整场景分布。

## 验证

测试使用本地合成短片检查真实时间采样、旋转坐标、静止画面、缓存修复与追踪结果校验，不修改原样本。

```powershell
$env:VIDEO_TOOLS_FFMPEG_DIR = $videoFfmpeg
& $videoPython -m unittest discover -s tests -p test_video_tools.py -v
```

首次准备真实样本后，还应打开每段首、中、末画面并核对竖屏方向。侧面 HEVC 必须完整解码成功；若失败，资料包必须明确记录失败原因，不能省略该视频。静止画面可以相同；有动作的不同时间不得因定位错误反复返回同一帧。确认裁剪框回映射正确后，才用局部图结果接入追踪程序。

## 与原有 CV 原型的关系

代码位于 `cv/video_tools/`，兼容入口为 `python cv/video_packet.py`；模块入口为 `python -m cv.video_tools`。原来的 `video_info.py`、`extract_frames.py` 和 `detect_video.py` 继续可用。精确时间索引与 HEVC 样本阅读使用新入口。

当前 `detect_video.py` 只输出检测回放和计数，没有轨迹身份或此处的 JSONL 结果。下一轮需显式接入真实时间和结果导出，才能交给 `review-results`，不要用平均帧率补造时间或默认把检测框当作稳定轨迹。
