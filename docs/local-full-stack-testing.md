# 本地前后端与算法联调

这次新增了真实后端和可切换的 API 页面。原有 `cv/` 算法、原 MySQL SQL 文件和原演示页面保留。

## 1. 安装并启动后端

在 PowerShell 中运行：

```powershell
Set-Location 'D:\Nottingham\Year 2\SEGP GROUP21'
.\.venv\Scripts\python.exe -m pip install -r cv\requirements.txt -r backend\requirements-dev.txt
# 仅首次复制；如果已经配置过，不要覆盖。
Copy-Item backend\.env.example backend\.env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --env-file backend/.env
```

保持这个终端打开。接口文档：`http://127.0.0.1:8000/docs`。

默认使用 `backend/data/petlo.sqlite3`，不会改原来的 MySQL 数据库。数据库内有明确标记的本地开发用户和狗记录；可以在上传页面添加你要测试的狗。MySQL 连接方式见 [backend/README.md](../backend/README.md)，需要队友实际数据库地址及有效用户 ID；当前没有代替队友连接真实 MySQL 服务。

## 2. 启动前端

打开第二个 PowerShell：

```powershell
Set-Location 'D:\Nottingham\Year 2\SEGP GROUP21'
# 仅首次复制；已有 .env.local 时手动调整其中两项。
Copy-Item .env.example .env.local
npm ci
npm run dev
```

`.env.local` 应包含：

```dotenv
VITE_USE_API=true
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

浏览器打开 `http://localhost:5173`。改配置后重启前端；将 `VITE_USE_API` 改为 `false` 并重启，可以恢复原演示页面。真实接口模式出错时不会自动改用假数据。

## 3. 人工核对流程

1. 打开 Upload video，选择数据库中的狗，或展开 Add a dog 新增记录。
2. 选择 Single fixed view，选择 Front/Side，上传相应固定镜头视频。要复查原样本双角度融合，选 Matching supplied sample pair，并同时选择原始正面与侧面视频。其他视频对会明确拒绝。
3. 点击 Upload and analyze。上传与分析为不同步骤；没有测量到的进度显示 Progress not measured，后台显示实际阶段。
4. 完成后点击 Review saved session，查看候选事件、统计和对应视频；不同视角按各自的时间跳转。
5. 返回列表与历史页面，刷新网页，再重启后端后检查记录仍然存在。
6. 核对空中接盘、落地捡盘、uncertain 的分类；零分母的比率应显示未知，而不是 0%。候选统计不等于识别准确率。

Stop waiting 只停止浏览器等待/请求，不能保证已提交的后台任务取消。如果任务已接受，去列表或保存的 session 查看。任务失败会显示 failed；修正环境后可开始新的分析尝试，原输出保留。首次缺少模型或 FFmpeg 会明确报错；原有 `tools/ffmpeg` 与 `yolo11n.pt` 可以复用。

## 4. 自动检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm run test:api
npm run build
```

真实短片链路测试（生成独立短片，不改原视频，也不评价准确率）：

```powershell
.\.venv\Scripts\python.exe -m backend.smoke `
  --video 'D:\Nottingham\Year 2\SEGP\General\0_Data\0_SampleVideo\Landscape_Tripod_FrontView.mp4' `
  --view front --seconds 0.5
```

报告位于新的 `outputs/backend-smoke-*/smoke-report.json`。各任务的原始逐帧记录、证据图与日志保存在对应的 `storage/jobs/<job_id>/`。网页播放使用真实相对源时间；算法内部仍使用原工具验证过的逐帧证据预览。

## 5. 手动上传 GitHub

上传新增 `backend/` 源码/依赖说明/测试、`src/` API 文件和 Live 页面、新数据库扩展迁移文件、文档、`.env.example`、更新的 `.gitignore` 与 `package.json`。保持目录路径，通过本地 Git/GitHub Desktop 提交更容易完整处理这些文件。先检查 `git status --short`。

不要上传 `backend/.env`、`.env.local`、`backend/data/`、`outputs/`、模型、私有视频或 `node_modules/`。本次不自动提交、推送或更新 Cloudflare。原 Pages 仍是演示站；即使上传后端代码，它也不会自动部署 Python 算法。当前服务仅接受本机请求，真正公开部署前还需要登录权限、远端运行环境和视频存储配置。
