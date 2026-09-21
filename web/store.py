"""
浏览器版的档案读写层。

路径常量全部复用 save_path.py（那是所有落盘的唯一真相），
但写入函数自己实现 —— save_path.py:save_word_summary() 里有 prompt_toolkit 的
交互式 prompt()，在服务进程里会把请求永久挂住。

数据跟终端版**共用同一份文件**，两边看到的记录是同一批。
"""

import json

from save_path import (
    RECORDS,
    CHAT_SUMMARY_LOG,
    PARSE_SUMMARY_LOG,
    WORDS_SUMMARY_LOG,
)


# ---------- 造句记录 ----------

def load_records():
    """RECORDS 的结构是 [{'draft':..., 'revised':..., 'notes':[...]}, ...]，没有时间戳"""
    if not RECORDS.exists():
        return []
    try:
        data = json.loads(RECORDS.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        print('[store] Oral_English_Exercise.json 解析失败，按空处理')
        return []
    # 跟 save_path.migrate_clean_invalid_records() 同样的防御：历史数据混过非字典元素
    return [i for i in data if isinstance(i, dict)]


def _write_records(records):
    RECORDS.write_text(
        json.dumps(records, ensure_ascii=False, indent=4), encoding='utf-8')


def append_record(draft, revised, notes=None):
    """新增一条，对应终端版的 write_json()"""
    records = load_records()
    records.append({'draft': draft, 'revised': revised, 'notes': notes or []})
    _write_records(records)
    return len(records)


def add_note(revised, note, draft=''):
    """把一段「为什么这么改」的分析挂到对应记录上。

    按 revised 匹配（跟终端版一致）。找不到就新建一条，避免分析白写 ——
    新建时必须带上 draft，否则用户没先点「存进档案」就直接存分析的话，
    档案里会多出一条原句为空的残缺记录。
    """
    records = load_records()
    for item in records:
        if item.get('revised') == revised:
            item.setdefault('notes', []).append(note)
            _write_records(records)
            return True
    records.append({'draft': draft, 'revised': revised, 'notes': [note]})
    _write_records(records)
    return False


# ---------- 单词本 ----------

def load_words():
    if not WORDS_SUMMARY_LOG.exists():
        return []
    try:
        data = json.loads(WORDS_SUMMARY_LOG.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return []
    return [i for i in data if isinstance(i, dict)]


# ---------- markdown 日志 ----------

def _load_md_entries(path):
    """两个 summary 日志的格式都是反复追加的 '\n## 时间戳\n正文'，按这个切开"""
    if not path.exists():
        return []
    raw = path.read_text(encoding='utf-8')
    entries = []
    for block in raw.split('\n## '):
        block = block.strip()
        if not block:
            continue
        block = block.lstrip('# ').strip()
        head, _, body = block.partition('\n')
        entries.append({'when': head.strip(), 'body': body.strip()})
    return entries


# ---------- 档案页 ----------

def _first_line(text, limit=60):
    line = (text or '').strip().split('\n')[0].lstrip('# ').strip()
    return line[:limit]


# 正文一律发全文，截断交给前端（CSS 收起 + 点击展开）。
# 之前在这里截成 90/120 字，前端连全文都拿不到，用户点开也只有节选。
# 数据量很小（几 KB），没有分页的必要。


def archive_items(kind='all'):
    """把四类记录合成前端要的卡片列表。

    造句记录没有时间戳（RECORDS 的结构里就没存），所以显示序号而不是时间，
    并且统一排在最前面 —— 没有时间就没法跟其它三类按时间混排。
    要改成时间排序得给 RECORDS 加字段，涉及老用户存量数据迁移，暂不动。
    """
    items = []

    records = load_records()
    for idx, r in enumerate(reversed(records), start=1):
        note = (r.get('notes') or [None])[-1]
        items.append({
            'kind': 'draft', 'kindLabel': '造句',
            'when': f'第 {len(records) - idx + 1} 条',
            'old': r.get('draft') or '',
            'title': r.get('revised') or '',
            'note': note or '',
        })

    timed = []
    for w in load_words():
        detail = w.get('usage') or ''
        if w.get('proficiency') is not None:
            detail = f"熟练度 {w['proficiency']}/4 · " + detail
        timed.append({
            'kind': 'word', 'kindLabel': '单词',
            'when': w.get('time', ''),
            'title': w.get('word', ''),
            'body': detail,
        })

    for e in _load_md_entries(PARSE_SUMMARY_LOG):
        head = _first_line(e['body'])
        timed.append({
            'kind': 'parse', 'kindLabel': '句型',
            'when': e['when'],
            'title': head,
            'body': e['body'][len(head):].lstrip(),
        })

    for e in _load_md_entries(CHAT_SUMMARY_LOG):
        timed.append({
            'kind': 'chat', 'kindLabel': '对话',
            'when': e['when'],
            'body': e['body'],
        })

    timed.sort(key=lambda x: x['when'], reverse=True)   # 时间戳是 'YYYY-MM-DD HH:MM'，字典序即时间序
    items.extend(timed)

    if kind != 'all':
        items = [i for i in items if i['kind'] == kind]
    return items
