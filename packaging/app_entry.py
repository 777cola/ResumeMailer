"""ResumeMailer 桌面入口（PyInstaller）——双击即用，不需要装 Python"""
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

# 源码方式直接跑（python packaging/app_entry.py）时也能 import server
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tidy_stdio() -> None:
    """Windows 控制台/重定向时避免中文和箭头符号报 UnicodeEncodeError"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False


def _free_port(start: int, span: int = 12) -> int:
    """端口被占（多半是已经开了一个）就往后找，别让用户面对一个闪退的图标"""
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def _open_later(url: str) -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    _tidy_stdio()
    os.environ.setdefault("HOST", "127.0.0.1")
    os.environ["RESUMEMAILER_PACKAGED"] = "1"
    requested = int(os.environ.get("RESUMEMAILER_PORT") or os.environ.get("PORT") or 8765)

    # 已经开着一个：把浏览器叫过来就好，别起第二个实例抢配置
    if _healthy(requested):
        if not os.environ.get("RESUMEMAILER_NO_BROWSER"):
            webbrowser.open(f"http://localhost:{requested}")
        print(f"ResumeMailer 已经在运行（{requested}），不重复启动。")
        return 0

    port = _free_port(requested)
    if not port:
        msg = f"端口 {requested}-{requested + 11} 都被占用了，关掉占用的程序再试。"
        print(msg)
        if sys.platform == "win32":
            try:
                input("按回车退出…")
            except Exception:
                pass
        return 1

    os.environ["PORT"] = str(port)
    url = f"http://localhost:{port}"

    import uvicorn
    from server import app

    if not os.environ.get("RESUMEMAILER_NO_BROWSER"):
        threading.Thread(target=_open_later, args=(url,), daemon=True).start()
        print(f"ResumeMailer 已启动 → {url}")
        if port != requested:
            print(f"（{requested} 被占用，换到了 {port}）")
        print("数据保存在 ~/.resumemailer ；退出请关掉这个窗口，或在 Dock 上按 Cmd+Q。")

    uvicorn.run(app, host=os.environ["HOST"], port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 打包后看不到报错最难受，兜一层
        print(f"启动失败：{exc}")
        if sys.platform == "win32":
            try:
                input("按回车退出…")
            except Exception:
                pass
        raise
