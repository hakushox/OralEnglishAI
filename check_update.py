import requests
import sys
from pathlib import Path
from save_path import get_local_version, save_local_version
import os
import stat
import zipfile
import shutil


GITHUB_API = 'https://api.github.com/repos/hakushox/OralEnglishAI/releases/latest'

def get_platform_tag():
    # ← 新增：把 sys.platform 映射成 release 文件名里约定的平台标识
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    else:
        raise RuntimeError(f"不支持的平台: {sys.platform}")
    
def get_latest_version():
    resp = requests.get(GITHUB_API, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    version = data['tag_name']

    platform_tag = get_platform_tag()
    download_url = None
    for asset in data['assets']:
        name_lower = asset['name'].lower()
        if 'launcher' in name_lower:
            continue
        if any(name_lower.endswith(k) for k in ('.exe', '.app', '.dmg')):
            continue
        if platform_tag in name_lower and '.zip' in name_lower:
            download_url = asset['browser_download_url']
            break

    if download_url is None:
        raise RuntimeError(f"未在 release 中找到匹配 {platform_tag} 平台的安装包")

    return version, download_url


def check_and_update(app_dir):
    # ← 改动：参数名从 exe_path 改成 app_dir，语义上更准确（这是个文件夹）
    current_version = get_local_version()
    latest_version, download_url = get_latest_version()
    print(f'当前版本{current_version} --> 最新版本{latest_version}')

    if current_version is None:
        save_local_version(latest_version)
        return False

    if latest_version == current_version:
        return False

    print(f'发现新版本 {latest_version}，正在下载...')
    resp = requests.get(download_url, stream=True, timeout=30)

    # ← 改动：原来是直接下载成"要替换的那一个文件"，现在下载的是 zip 压缩包
    zip_path = app_dir.parent / 'update.zip'
    with open(zip_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    # ← 新增：解压这一步，onefile版本完全没有这个步骤
    print('正在解压...')
    temp_extract_dir = app_dir.parent / 'update_temp'
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(temp_extract_dir)

    # ← 新增：原来是 new_file.replace(exe_path) 替换单个文件
    #        现在要先删除整个旧文件夹，再用新文件夹整体替换
    shutil.rmtree(app_dir)
    new_app_dir = temp_extract_dir / 'SpeakNatural'  # 假设zip解压后顶层文件夹叫这个名字
    new_app_dir.replace(app_dir)

    # ← 新增：清理下载/解压过程中产生的临时文件
    zip_path.unlink()
    shutil.rmtree(temp_extract_dir, ignore_errors=True)

    # ← 改动：原来直接对 exe_path 加权限，现在要先定位到文件夹内部的可执行文件
    exe_name = 'SpeakNatural.exe' if sys.platform == "win32" else 'SpeakNatural'
    exe_file = app_dir / exe_name
    if sys.platform != "win32":
        st = os.stat(exe_file)
        os.chmod(exe_file, st.st_mode | stat.S_IXUSR)

    save_local_version(latest_version)
    return True