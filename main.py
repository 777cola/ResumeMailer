#!/usr/bin/env python3
"""ResumeMailer · 简历投递助手 — 启动入口"""
import sys
from pathlib import Path

# 确保项目目录在路径中
sys.path.insert(0, str(Path(__file__).parent))

from server import start

if __name__ == "__main__":
    start()
