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
