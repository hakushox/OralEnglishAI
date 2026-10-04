"""
浏览器版入口：起本地服务 + 自动打开浏览器。

    python run_web.py

只监听 127.0.0.1，不对外网暴露。
这个文件也是 pyinstaller 的打包入口（终端版入口 edgetts.py 保持不动），
所以里面有两处是专门为打包写的，改的时候别顺手"简化"掉：

- `from web.server import app` 必须是真的 import，不能用 uvicorn 的
  'web.server:app' 字符串形式 —— pyinstaller 靠静态分析收集依赖，
  字符串里的模块它看不见，打出来的包一启动就 ModuleNotFoundError。
- 端口不写死：8765 被占用时自动往后找，打包版不能因为端口冲突就崩给用户看。
"""

import multiprocessing
import os
import socket
import sys
import threading
import webbrowser

import uvicorn

# Windows 控制台默认是系统代码页（中文系统是 cp936），印不出 ⚠ 这类字符，
# 直接抛 UnicodeEncodeError 把程序干掉 —— 而这个程序所有提示都是中文。
# 打包后的 exe 不受 PYTHONUTF8 环境变量影响，只能进程自己改。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass          # 没有控制台时 stdout 可能是 None 或不可重配，忽略即可


HOST = '127.0.0.1'
# 8765 是默认端口，被占用会自动顺延；SPEAKNATURAL_PORT 可以指定别的起点
# （同时开两份、或者验证用的实例不想抢用户的端口时用得上）
PORT = int(os.environ.get('SPEAKNATURAL_PORT') or 8765)


def pick_port(preferred=PORT, tries=20):
    """返回一个能用的端口：先试 preferred，被占用就往后顺延，都不行就让系统随便给一个。

    这里 bind 完就关掉，到 uvicorn 真正 bind 之间有极小的空窗，
    本机单用户场景下可以接受，换来的是"双击就能开"。
    """
    for port in range(preferred, preferred + tries):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def main():
    from web.server import app          # 见文件头：必须真 import

    port = pick_port()
    url = f'http://{HOST}:{port}'
    if port != PORT:
        print(f'[!] {PORT} 端口被占用了，改用 {port}')
    print(f'SpeakNatural 已启动 → {url}  (Ctrl+C 退出)')
    print('这个窗口是程序本体，关掉它程序就停了。')

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=HOST, port=port, log_level='warning')
    except KeyboardInterrupt:
        pass
    print('已退出。')


if __name__ == '__main__':
    # 打包后的可执行文件如果 fork 子进程，没有这行会反复重启整个程序
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as e:
        # 打包版是双击启动的，异常直接退出的话窗口一闪就没了，什么也看不到
        print(f'\n启动失败：{type(e).__name__}: {e}')
        if getattr(sys, 'frozen', False):
            input('按回车关闭…')
        raise
