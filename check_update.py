import requests
import sys
from pathlib import Path
from save_path import get_local_version, save_local_version,save_pending_version  
import os
import stat
import zipfile
import shutil
import subprocess


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
    zip_path = app_dir.parent / 'update.zip'
    with open(zip_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    if sys.platform == 'win32':
        updater_path = app_dir.parent / 'SpeakNatural_Updater' / 'updater.exe'
        exe_name = 'SpeakNatural.exe'
        subprocess.Popen([str(updater_path), str(app_dir), str(zip_path), exe_name])
        save_pending_version(latest_version)
        return True
    else:
        print('正在解压...')
        temp_extract_dir = app_dir.parent / 'update_temp'
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(temp_extract_dir)

        new_app_dir = temp_extract_dir / 'SpeakNatural'
        if not new_app_dir.exists():
            raise RuntimeError(f'解压结果异常，未找到 {new_app_dir}，更新已中止，未影响当前版本')

        # 校验通过后，再做替换：先把旧版本挪到备份位，再放新版本，最后清理备份
        backup_dir = app_dir.parent / 'SpeakNatural_backup'
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        app_dir.replace(backup_dir)      # 旧版本改名（几乎瞬间完成，不是删除）
        try:
            new_app_dir.replace(app_dir) # 新版本就位
        except Exception:
            backup_dir.replace(app_dir)  # 失败就把旧版本挪回来
            raise
        else:
            shutil.rmtree(backup_dir, ignore_errors=True)  # 确认成功后再删旧版本

        zip_path.unlink()
        shutil.rmtree(temp_extract_dir, ignore_errors=True)

        exe_file = app_dir / 'SpeakNatural'
        st = os.stat(exe_file)
        os.chmod(exe_file, st.st_mode | stat.S_IXUSR)
        save_pending_version(latest_version)
        return True