import os
import sys
import json
from pathlib import Path

def get_save_dir():
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA"))
    elif sys.platform == "darwin":  # Mac
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux
        base = Path.home() / ".config"
    
    save_dir = base / "OralEnglish"
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir

SAVE_DIR = get_save_dir()
RECORDS = SAVE_DIR / 'Oral_English_Exercise.json'

VERSION_FILE = SAVE_DIR / 'version.json'

def get_local_version():
    if not VERSION_FILE.exists():
        return None
    return json.loads(VERSION_FILE.read_text(encoding='utf-8')).get('version')

def save_local_version(version):
    VERSION_FILE.write_text(json.dumps({'version': version}, ensure_ascii=False, indent=4), 
                            encoding='utf-8')

MIGRATION_FLAG = SAVE_DIR / ".migration_v1_done"

def migrate_clean_invalid_records():
    """一次性清理历史数据中混入的非字典元素，只会执行一次"""
    if MIGRATION_FLAG.exists():
        return   # 已经清理过，直接跳过

    if not RECORDS.exists():
        MIGRATION_FLAG.touch()   # 文件都不存在，没什么好清理的，直接标记完成
        return

    try:
        data = json.loads(RECORDS.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        MIGRATION_FLAG.touch()
        return

    cleaned = [item for item in data if isinstance(item, dict)]

    if len(cleaned) != len(data):
        RECORDS.write_text(json.dumps(cleaned, ensure_ascii=False, indent=4), encoding='utf-8')
        print(f'检测到历史数据异常，已自动清理（原始 {len(data)} 条，清理后 {len(cleaned)} 条）')

    MIGRATION_FLAG.touch()   # 不管有没有清理到东西，都标记为"已处理过"