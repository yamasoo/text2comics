"""啟動 文字轉漫畫：python run.py [--port 8000] [--no-open]"""
import argparse
import socket
import threading
import webbrowser

import uvicorn

from app import app


def free_port(start):
    for port in range(start, start + 20):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit("找不到可用的埠（試了 %d–%d）" % (start, start + 19))


def main():
    ap = argparse.ArgumentParser(description="文字轉漫畫")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-open", action="store_true", help="不自動開瀏覽器")
    args = ap.parse_args()
    port = free_port(args.port)
    url = "http://127.0.0.1:%d/" % port
    print("文字轉漫畫：%s（Ctrl+C 結束）" % url)
    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # 只綁本機；timeout_graceful_shutdown 讓開著 SSE 的瀏覽器不會拖住 Ctrl+C。
    uvicorn.run(app, host="127.0.0.1", port=port, timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
