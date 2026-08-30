import os
import sys
import json
import datetime
from pathlib import Path
from prompt_toolkit import prompt

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


CHAT_SUMMARY_LOG = SAVE_DIR / "chat_summaries.md"
 
def save_chat_summary(summary_text):
    """把一次深度对话的总结，追加写入到独立的 markdown 文件里"""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    entry = f"\n## {timestamp}\n{summary_text}\n"
    with open(CHAT_SUMMARY_LOG, 'a', encoding='utf-8') as f:
        f.write(entry)

PARSE_SUMMARY_LOG = SAVE_DIR / "parse_summaries.md"
 
def save_parse_summary(summary_text):
    """写入到独立的 markdown 文件里"""
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    entry = f"\n## {timestamp}\n{summary_text}\n"
    with open(PARSE_SUMMARY_LOG, 'a', encoding='utf-8') as f:
        f.write(entry)

WORDS_SUMMARY_LOG = SAVE_DIR / "words_summaries.json"
 
def save_word_summary(word, usage):
    """把一次单词学习写入到独立的 json 文件里"""
    if WORDS_SUMMARY_LOG.exists():
        with open(WORDS_SUMMARY_LOG, 'r', encoding='utf-8') as f:
            datas = json.load(f)
    else:
        datas = []

    # latest = {}
    # for item in datas:
    #     sample = item['word']
    #     if sample not in latest or item['time'] > latest[sample]['time']:
    #         latest[sample] = item 
    # renewed = list(latest.values())

    if word in (keyword['word'] for keyword in datas if datas):
        confirm = prompt(f'发现{word}已有记录,是否先查看\n(y ->查看；n ->直接覆盖) ===>：').strip()
        if confirm.lower() == 'y':
            for item in datas:
                if item['word'] == word:
                    print(item)
            reconfirm = prompt('是否覆盖？(y/n): ').strip()
            if reconfirm.lower() == 'y':
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
                for item in datas:
                    if item['word'] == word:
                        item['usage'] = usage
                        item['time'] = timestamp
                        WORDS_SUMMARY_LOG.write_text(json.dumps(datas,ensure_ascii=False,
                                                                indent=4),encoding='utf-8')
                        return
        else:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            for item in datas:
                if item['word'] == word:
                    item['usage'] = usage
                    item['time'] = timestamp
                    WORDS_SUMMARY_LOG.write_text(json.dumps(datas,ensure_ascii=False,
                                                            indent=4),encoding='utf-8')
                    print(f'已覆盖关于{word}的旧纪录')   
                    return
         
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    data = {'word': word, 'usage': usage, 'time': timestamp}
    datas.append(data)

    with open(WORDS_SUMMARY_LOG, 'w', encoding='utf-8') as f:
        json.dump(datas, f, ensure_ascii=False, indent=4)

def update_word_proficiency(word, proficiency, issue):
    """测验结束后，把某个单词的熟练度和问题点写回单词本"""
    if not WORDS_SUMMARY_LOG.exists():
        return
    with open(WORDS_SUMMARY_LOG, 'r', encoding='utf-8') as f:
        datas = json.load(f)

    for item in datas:
        if item.get('word') == word:
            item['proficiency'] = proficiency
            item['issue'] = issue
            break

    with open(WORDS_SUMMARY_LOG, 'w', encoding='utf-8') as f:
        json.dump(datas, f, ensure_ascii=False, indent=4)

# os.startfile(SAVE_DIR)

def get_pending_version():
    """读取"待确认"的版本号（文件已替换，但还没验证能正常启动）"""
    if not VERSION_FILE.exists():
        return None
    return json.loads(VERSION_FILE.read_text(encoding='utf-8')).get('pending_version')

def save_pending_version(version):
    """更新流程替换完文件后调用：只标记"待确认"，不动正式版本号"""
    data = {}
    if VERSION_FILE.exists():
        data = json.loads(VERSION_FILE.read_text(encoding='utf-8'))
    data['pending_version'] = version
    VERSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=4),
                            encoding='utf-8')

def confirm_pending_version():
    """新版本自己确认启动成功后调用：把 pending_version 转正为正式 version"""
    if not VERSION_FILE.exists():
        return
    data = json.loads(VERSION_FILE.read_text(encoding='utf-8'))
    pending = data.get('pending_version')
    if pending:
        data['version'] = pending
        data.pop('pending_version', None)
        VERSION_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=4),
                                encoding='utf-8')