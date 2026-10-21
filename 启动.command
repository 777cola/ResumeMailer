#!/bin/bash
# ResumeMailer 一键启动（macOS）— 双击运行
# 首次会自动建虚拟环境并安装依赖，之后直接启动。
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "没有找到 Python 3。"
  echo "请先安装：https://www.python.org/downloads/  然后重新双击本文件。"
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi

PYVER=$(python3 -c 'import sys; print("%d%d" % sys.version_info[:2])')
if [ "$PYVER" -lt 310 ]; then
  echo "Python 版本太旧（需要 3.10+，当前 $PYVER）。请先升级 Python。"
  read -n 1 -s -r -p "按任意键关闭…"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "首次运行：正在安装依赖（约 1 分钟，只做一次）…"
  python3 -m venv .venv || { echo "创建虚拟环境失败"; read -n 1 -s -r; exit 1; }
  .venv/bin/pip install --quiet --upgrade pip
  if ! .venv/bin/pip install --quiet -r requirements.txt; then
    echo "依赖安装失败。若是网络问题，可换国内镜像重试："
    echo ".venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
    read -n 1 -s -r -p "按任意键关闭…"
    exit 1
  fi
fi

echo "启动中…浏览器会自动打开 http://localhost:8765"
echo "用完直接关闭这个窗口即可。"
exec .venv/bin/python main.py
