@echo off
chcp 65001 >nul
rem ResumeMailer 一键启动（Windows）— 双击运行
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 没有找到 Python。
  echo 请先安装 https://www.python.org/downloads/  （安装时勾选 Add Python to PATH）
  pause
  exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)"
if errorlevel 1 (
  echo Python 版本太旧，需要 3.10 或更高。
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo 首次运行：正在安装依赖，约 1 分钟，只做一次...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\pip.exe" install --quiet -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败。若是网络问题，可换国内镜像：
    echo .venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
  )
)

echo 启动中...浏览器会自动打开 http://localhost:8765
echo 用完直接关闭这个窗口即可。
".venv\Scripts\python.exe" main.py
pause
