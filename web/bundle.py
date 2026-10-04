"""打包环境（PyInstaller）相关的路径判断。

开发时跑的是源码目录，打包后所有数据文件被解压到一个临时目录 `sys._MEIPASS`，
两边的相对路径不一样。凡是要读「跟着程序走的文件」（目前只有 web/static），
都从这里取路径，不要再写 `Path(__file__).parent / ...` —— frozen 环境下
`__file__` 指向的是 archive 里的虚拟路径，拼出来的目录并不存在。

注意用户数据不走这里：那些在仓库外的 SAVE_DIR，由 save_path.py 负责。
"""

import sys
from pathlib import Path


def frozen():
    """是否运行在 PyInstaller 打出来的包里"""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def resource(*parts):
    """取随包分发的资源路径。参数按仓库根目录的相对路径给，如 resource('web', 'static')"""
    base = Path(sys._MEIPASS) if frozen() else Path(__file__).resolve().parent.parent
    return base.joinpath(*parts)
