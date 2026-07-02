import os
import sys
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