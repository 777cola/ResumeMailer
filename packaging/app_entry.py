"""ResumeMailer 打包入口（PyInstaller）——双击即用，不需要装 Python"""
import os
import sys
import threading
import time
import webbrowser


def _open_later(url: str) -> None:
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main() -> int:
    os.environ.setdefault("HOST", "127.0.0.1")
    port = int(os.environ.get("RESUMEMAILER_PORT") or os.environ.get("PORT") or 8765)
    os.environ["PORT"] = str(port)

    import uvicorn
    from server import app

    url = f"http://localhost:{port}"
    if not os.environ.get("RESUMEMAILER_NO_BROWSER"):
        threading.Thread(target=_open_later, args=(url,), daemon=True).start()
        print(f"ResumeMailer 已启动 → {url}")
        print("数据保存在 ~/.resumemailer ；关闭这个窗口即退出。")
    uvicorn.run(app, host=os.environ["HOST"], port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
