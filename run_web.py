"""
浏览器版入口：起本地服务 + 自动打开浏览器。

    python run_web.py

只监听 127.0.0.1，不对外网暴露。
打包时 pyinstaller 的入口换成这个文件（终端版入口 edgetts.py 保持不动）。
"""

import threading
import webbrowser

import uvicorn

HOST = '127.0.0.1'
PORT = 8765

if __name__ == '__main__':
    threading.Timer(1.0, lambda: webbrowser.open(f'http://{HOST}:{PORT}')).start()
    print(f'SpeakNatural 已启动 → http://{HOST}:{PORT}  (Ctrl+C 退出)')
    uvicorn.run('web.server:app', host=HOST, port=PORT, log_level='warning')
