import requests
import sys
from pathlib import Path
from save_path import get_local_version, save_local_version
import os
import stat


GITHUB_API = 'https://api.github.com/repos/hakushox/OralEnglishAI/releases/latest'

def get_latest_version():
    resp = requests.get(GITHUB_API, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    version = data['tag_name']

    download_url = None
    for asset in data['assets']:
        if 'launcher' not in asset['name'].lower():
            download_url = asset['browser_download_url']
            break

    return version, download_url

def check_and_update(exe_path):
    current_version = get_local_version()  # 内部自己查，不用外面传了
    latest_version, download_url = get_latest_version()
    print(f'当前版本{current_version} --> 最新版本{latest_version}')
    if current_version is None:
        save_local_version(latest_version)
        return False

    if latest_version == current_version:
        return False  # 已是最新

    print(f'发现新版本 {latest_version}，正在下载...')
    resp = requests.get(download_url, stream=True, timeout=30)
    new_file = exe_path.with_suffix('.new')
    with open(new_file, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    new_file.replace(exe_path)

        # 补上执行权限，不然新文件会因为权限不足无法运行
    if sys.platform != "win32":
        st = os.stat(exe_path)
        os.chmod(exe_path, st.st_mode | stat.S_IXUSR)

    save_local_version(latest_version)  # 更新完之后，记得写回本地版本记录
    return True