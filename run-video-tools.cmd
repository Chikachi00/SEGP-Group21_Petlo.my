@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
if defined VIDEO_TOOLS_PYTHON goto configured
if exist ".venv\Scripts\python.exe" goto venv
py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 goto launcher
python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 goto systempython
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" goto codex
echo Python 3.10 or newer is required. See cv/video_tools/README.md.
exit /b 1
:configured
"%VIDEO_TOOLS_PYTHON%" -m cv.video_tools %*
exit /b %ERRORLEVEL%
:venv
".venv\Scripts\python.exe" -m cv.video_tools %*
exit /b %ERRORLEVEL%
:launcher
py -3 -m cv.video_tools %*
exit /b %ERRORLEVEL%
:systempython
python -m cv.video_tools %*
exit /b %ERRORLEVEL%
:codex
"%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m cv.video_tools %*
exit /b %ERRORLEVEL%
