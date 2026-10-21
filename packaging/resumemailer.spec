# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：macOS 出 .app，Windows 出文件夹

用法：pyinstaller packaging/resumemailer.spec --noconfirm
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
try:
    APP_VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
except OSError:
    APP_VERSION = "0.0.0"

hiddenimports = [
    "multipart",
    "python_multipart",
    "email.mime.multipart",
    "email.mime.base",
]
for pkg in ("uvicorn", "fastapi", "starlette", "engine"):
    hiddenimports += collect_submodules(pkg)

datas = [(os.path.join(ROOT, "static"), "static"),
         (os.path.join(ROOT, "VERSION"), ".")]
try:
    datas += collect_data_files("certifi")
except Exception:
    pass

a = Analysis(
    [os.path.join(ROOT, "packaging", "app_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "setuptools", "pip"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ResumeMailer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=sys.platform == "win32",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ResumeMailer",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ResumeMailer.app",
        icon=None,
        bundle_identifier="xyz.qijunhao.resumemailer",
        info_plist={
            "CFBundleName": "ResumeMailer",
            "CFBundleDisplayName": "ResumeMailer",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
