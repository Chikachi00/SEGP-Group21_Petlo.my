# 本地视频资料包与算法迭代

这次接入的是视频读取和复盘工具：四段视频均已完整解码校验，但没有把它们转换成四个新视频文件。每段都有真实源帧时间索引、浏览截图、概览图集；三段动作视频各有两个自动推荐窗口。所有原片仍保留在原目录，内容未变化。

## 项目里的位置

| 位置 | 用途 | Git |
|---|---|---|
| `cv/video_tools/` | `prepare`、`inspect-window`、`review-results` 实现 | 纳入代码管理 |
| `cv/video_packet.py` | 与原 CV 脚本一致的兼容入口 | 纳入代码管理 |
| `tests/test_video_tools.py` | 14 项媒体/契约验证 | 纳入代码管理 |
| `tools/ffmpeg/` | 同版本 FFmpeg/ffprobe、下载校验记录 | 本地忽略 |
| `outputs/video-analysis-pack/` | 清单、时间索引、图片、概览及候选 | 本地忽略 |
| `outputs/video-analysis-pack/inspections/` | 按需连续帧和局部图 | 本地忽略 |
| `outputs/video-analysis-pack/reviews/` | 算法结果、带框回放及前后对比 | 本地忽略 |

## 直接使用

在仓库根目录打开 PowerShell。已有本地资料包可以直接打开 `outputs/video-analysis-pack/index.html`，无需重新解码。

```powershell
.\run-video-tools.cmd prepare --source '<sample-video-directory>' --output outputs/video-analysis-pack
.\run-video-tools.cmd inspect-window --pack outputs/video-analysis-pack --video-id Portrait_Handheld --start 0 --end 1 --frame-id 0 --tiles
```

启动器优先用 `VIDEO_TOOLS_PYTHON` 指定的解释器，再用项目 `.venv`，然后检查系统 Python 启动器和 Python 是否可运行，最后尝试本机 Codex 附带 Python。需要 Python 3.10+、Pillow、NumPy。视频包不需要先安装 YOLO。完整 CV 环境依赖在 `cv/requirements.txt`，仅视频资料工具依赖在 `cv/video_tools/requirements.txt`。

如果在 Codex 的隔离环境里系统启动器找不到你安装的 Python，可先明确指定此电脑已验证的解释器：

```powershell
$env:VIDEO_TOOLS_PYTHON = '.\.venv\Scripts\python.exe'
```

FFmpeg 默认从仓库 `tools/ffmpeg/` 查找，换电脑需复制或按正规来源安装本地工具，也可以传 `--ffmpeg-dir` 或设置 `VIDEO_TOOLS_FFMPEG_DIR`。工具不自动下载、不绕过证书校验、不上传原视频。预处理不调用 GPT；模型读图、摘要和写代码仍会使用额度。

## 每轮工作

1. Codex 先读资料包 `manifest.json`、`CODEX_GUIDE.md` 和四张概览图集，共 20 个画面。
2. 用原视频连续帧运行算法。浏览低频图片只用来定位，不替代算法输入。
3. 按统一 JSONL 格式输出真实源帧时间、狗/飞盘类别、轨迹 ID、原尺寸显示方向边界框、置信度与 detected/missing 状态。
4. 用 `review-results` 汇总缺失、低置信度和跳变候选；每次只看一个窗口、每批最多八张独立图片。小飞盘按需用 4×4 重叠网格或扩展检测框的局部图。
5. 修改算法后用相同来源和覆盖重跑，传上一版 `report.json` 比较；保留改善与退步案例。

`cv/detect_video.py` 保留为基础检测演示，不输出逐帧轨迹 JSONL。当前样本事件流程另用增强检测与狗/飞盘联合分析结果；事件分类、双视角样本融合和候选统计见 [v3 事件与统计说明](throw-events-v3.md)。这些结果仍是样本级候选，不能当作普遍准确率。

没有人工标签时，只能报告运行指标和待核查错误候选，不能宣称准确率。高变化窗口不直接代表投掷或接盘。手持相机运动可能触发候选；Setup 默认只作环境参考。同一次投掷的正面、侧面视频必须归入同一数据划分组。实际距离和速度需要后续标定。

详细字段、命令和可复制提示见 [工具使用说明](../cv/video_tools/README.md)。

## 验证

```powershell
py -3 -m unittest discover -s tests -v
```

测试使用临时合成视频，检查 HEVC 完整读取、真实可变帧时间、静止帧、旋转、坐标回映射、独立失败状态、缓存和结果契约。原有 CV 工具测试需要 OpenCV；工具包测试需要本地 FFmpeg/ffprobe。没有这些依赖时应报告缺失，不把跳过当成成功。
