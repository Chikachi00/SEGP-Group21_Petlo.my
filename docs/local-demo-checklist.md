# 周四本地演示检查清单（2026-10-22）

目标：用真实本地接口演示上传、后台分析、刷新恢复、候选事件报告、回放和历史。英文页面沿用原有视觉风格；原 `cv/` 算法与演示模式保留。演示结束仍然不能据此宣称泛化准确率。

## 演示前一天

1. 从项目根目录运行 `powershell -ExecutionPolicy Bypass -File scripts/start-local-demo.ps1 -CheckOnly`。缺依赖时按 `local-full-stack-testing.md` 安装，不要在汇报前临时升级依赖或模型。
2. 启动：`powershell -ExecutionPolicy Bypass -File scripts/start-local-demo.ps1 -OpenBrowser`。只监听本机；已有服务会尝试复用，不会强占端口或覆盖已有环境配置。
3. 用原始两个样本完整运行一次。侧面原文件约 271 MiB，本地默认上限 1024 MiB；不要为演示压成低分辨率。网页先检查服务器配置的每文件大小上限，服务端仍做最终验证。
4. 保存完整任务的 session ID、报告 JSON、事件 CSV 和实测耗时。保留数据库、原上传与对应 jobs 输出；不要清空 `backend/data/` 或 `outputs/backend-storage/`。
5. 打开已完成的报告，检查两个视角均可播放；点击每个事件检查对应视角时间。已保存报告用于现场快速展示，需说明它是提前运行的真实结果。
6. 重启服务，确认同一报告仍可打开。把笔记本接电，关闭自动睡眠；避免同时运行多个算法任务。

## 现场建议流程（5–8 分钟，不含完整算法等待）

1. Video Management：说明已有真实分析记录，状态区分 queued/running/completed/failed。
2. Upload video：选择数据库中的狗，说明单固定视角和原样本双视角两种模式。需要现场启动时上传正面样本，或明确标为“流程检查”的短片；短片不能作为完整事件表现的证据。
3. 上传成功自动打开 Analysis status：展示实际阶段、任务 ID、提交后耗时和最近查询时间。没有精确百分比或预计剩余时间，转圈动画不是算法进度证明。
4. 刷新状态页，或回列表点击 View progress：同一个任务 ID 继续查询，没有重复 POST 或重新上传。
5. 如果完整任务尚未结束，切换到提前完成的原样本报告。不要声称现场任务已经完成。
6. Analysis report：展示候选次数、空中接盘与落地捡盘的区别、uncertain 和零分母 Unknown。切换 Front/Side，点事件回放，下载 JSON/CSV。
7. Historical Trend：说明它展示候选接盘率趋势，不是模型识别准确率。

## 样本位置

```text
D:\Nottingham\Year 2\SEGP\General\0_Data\0_SampleVideo\Landscape_Tripod_FrontView.mp4
D:\Nottingham\Year 2\SEGP\General\0_Data\0_SampleVideo\Landscape_Tripod_SideView.mp4
```

网页可直接选择原文件，不必移动。双视角模式仅接受已知原始样本；任意其他视频对仍不支持。原视频内容不变，后台按任务复制并处理。

## 常见故障

- Backend unavailable：检查后端终端或 `outputs/local-demo/` 日志；点 Retry backend connection。真实接口错误不会静默回退为演示数据。
- Status connection interrupted：点 Resume status checks，仅恢复查询，不创建新任务。
- 长时间停留在一个阶段：先查看该任务 `pipeline.log` 是否有新的逐帧输出；最近状态查询成功只证明接口可访问，不能证明推理持续前进。
- failed：查看错误码和对应 job 日志；修正后点 Start a new analysis attempt。之前的输出保留。
- 后端重启：未结束的任务会明确标记失败；完成报告保留。当前不会自动续算断点。
- 端口占用：脚本不会杀已有服务。先确认是同一项目，不要为了启动重复打开多个后台。
- Stop waiting 或关闭网页只停止浏览器等待，不等于取消服务器算法。

## 可复用的完整原样本核验命令

后端启动后，在另一个终端运行（会创建新的真实任务，不是只查询）：

```powershell
Set-Location 'D:\Nottingham\Year 2\SEGP GROUP21'
.\.venv\Scripts\python.exe -m backend.demo_check --sample-dir 'D:\Nottingham\Year 2\SEGP\General\0_Data\0_SampleVideo'
```

它通过实际上传 API 提交原始双视角、观察任务、验证 HTTP 206 回放，并将阶段耗时和报告保存在 `outputs/demo-check-*/report.json`。结果同时保存在默认本地数据库，网页可直接查看。不能在算法运行中关闭后端。

停止由启动脚本创建的服务：`powershell -ExecutionPolicy Bypass -File scripts/stop-local-demo.ps1`。脚本会检查未结束任务并拒绝中断它们；不会关闭用户手动启动的服务。

## 明确的演示边界

仅本机单用户、默认 SQLite；真实 MySQL、公网登录授权、服务器部署未在此次本地演示中验收。缺少场地标定时不报告真实米数或物理速度。人工审核标签不作为机器推理输入；报告是算法候选结果。

## 本机本次完整实测与已保存报告

- 原始正面＋侧面联合任务：约 **41.1 分钟**（CPU 推理，包含上传、预处理、轨迹与回放生成；不是处理时间保证）。
- Session：`3271e8cf8e794e2f945b51dab6143581`。
- 后端和前端启动后，直接打开：`http://localhost:5173/sessions/3271e8cf8e794e2f945b51dab6143581`。
- 实际机器候选：4 次投掷，3 次空中接盘、1 次落地捡盘，0 uncertain。75% 是候选空中接盘率，不是识别准确率。人工标签未用于此次推理。
- 已验证正面第二次事件跳到约 10.633 秒，侧面跳到约 10.978 秒；两视角不能混用一个源时间。
- 实际下载 JSON 有 4 个事件；CSV 有 8 行事件/视角记录，不是 8 次投掷。已完成报告及视频在后端重启后仍可访问。
- 验证记录：`outputs/local-demo-validation-20261021.json`；完整阶段记录：`outputs/demo-check-18b29962f4/report.json`。
- 页面截图：`outputs/local-demo/local-demo-report.png`。这些运行输出均被 Git 忽略，留在本机作为演示证据。

现场建议先展示该真实已完成报告，再启动一个新任务展示上传与等待。不要等待 41 分钟才开始讲结果，也不要把提前运行的结果称为现场任务结果。
