#!/usr/bin/env python3
"""
SpeakNatural 浏览器版打包脚本（macOS / Windows 通用）。

    python build_web.py          只打包，产物在 dist/SpeakNatural/
    python build_web.py --app    打包并塞进 SpeakNaturalLauncher.app（仅 macOS）

为什么是 .py 而不是直接写在 build_web.sh 或 workflow 里：Windows 跑不了 shell 脚本，
而 pyinstaller 的参数（尤其那串 --collect-all）一旦抄成两份，迟早会对不上。
这里是唯一的事实来源，build_web.sh 和 .github/workflows/build.yml 都只是调它。

终端版（edgetts.py）的打包命令在 notes 里，产物同名，别混着用。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'SpeakNatural'

# --add-data 的分隔符：Windows 是分号，其它是冒号。抄错了静态文件就进不去包，
# 表现成打开是白页
SEP = ';' if os.name == 'nt' else ':'

ICON = 'images/icon.ico' if os.name == 'nt' else 'images/icon.icns'

# 这些包有 pyinstaller 静态分析看不见的东西：
#   faster_whisper / ctranslate2 / onnxruntime —— 二进制扩展 + 数据文件
#   huggingface_hub —— 首次运行要下模型
#   uvicorn / fastapi —— 大量动态 import 的协议实现
#   edge_tts / ollama —— 走 aiohttp / httpx
COLLECT = [
    'faster_whisper', 'ctranslate2', 'onnxruntime', 'huggingface_hub',
    'uvicorn', 'fastapi', 'edge_tts', 'ollama',
]

# jedi 是 ipython 的依赖（28M），顺着 import 链被卷进来，浏览器版一行都用不到。
# 排掉它包能小一成多。IPython 本身同理。
EXCLUDE = ['jedi', 'IPython', 'parso']


def build():
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean', '--noconfirm',
        '--name', NAME,
        '--console',                       # 保留终端窗口：模型下载进度和报错都靠它
        '--icon', ICON,
        '--add-data', f'web/static{SEP}web/static',
        'run_web.py',
    ]
    for pkg in COLLECT:
        cmd[-1:-1] = ['--collect-all', pkg]
    for mod in EXCLUDE:
        cmd[-1:-1] = ['--exclude-module', mod]

    print('$ ' + ' '.join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)

    out = ROOT / 'dist' / NAME
    size = sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    print(f'\n✅ 产物：{out}  ({size / 1024 / 1024:.0f}M，按文件字节数算，du 看会小一些）')
    return out


def into_app(built):
    """把产物塞进 macOS 的 .app 壳里。壳本身是手工做的 AppleScript applet，
    它只认死路径 Contents/Resources/SpeakNatural/SpeakNatural，所以名字不能改。"""
    res = ROOT / 'SpeakNaturalLauncher.app' / 'Contents' / 'Resources'
    if not res.is_dir():
        sys.exit(f'没找到 {res}')
    target = res / NAME
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(built, target)
    (target / NAME).chmod(0o755)
    print(f'✅ 已写入 {res.parent.parent.name}（双击即启动浏览器版）')


if __name__ == '__main__':
    built = build()
    if '--app' in sys.argv:
        if sys.platform != 'darwin':
            sys.exit('--app 只在 macOS 上有意义')
        into_app(built)
