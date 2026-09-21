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


def _write_md_entries(path, entries):
    """按 save_chat_summary() 的格式重建整个文件。

    格式很简单（反复追加 '\n## 时间戳\n正文\n'），所以解析-重建是无损的，
    但这是终端版也在追加的文件，改之前跑过往返一致性检查。
    """
    path.write_text(
        ''.join(f'\n## {e["when"]}\n{e["body"]}\n' for e in entries),
        encoding='utf-8')


def _write_words(words):
    WORDS_SUMMARY_LOG.write_text(
        json.dumps(words, ensure_ascii=False, indent=4), encoding='utf-8')


# ---------- 删除 / 撤销 ----------

# 只留最近一次删除，供撤销用。本地单用户程序，放内存够了；
# 进程重启后撤销不了，但那时用户早就离开这个界面了。
_last_deleted = None


def _source(kind):
    """返回 (读函数, 写函数)，把四类记录各自的存储差异收在这里"""
    if kind == 'draft':
        return load_records, _write_records
    if kind == 'word':
        return load_words, _write_words
    if kind in ('parse', 'chat'):
        path = PARSE_SUMMARY_LOG if kind == 'parse' else CHAT_SUMMARY_LOG
        return (lambda: _load_md_entries(path),
                lambda items: _write_md_entries(path, items))
    return None, None


def delete_item(kind, index):
    read, write = _source(kind)
    if read is None:
        return False
    items = read()
    if not 0 <= index < len(items):
        return False
    global _last_deleted
    _last_deleted = (kind, index, items.pop(index))
    write(items)
    return True


def restore_last():
    global _last_deleted
    if _last_deleted is None:
        return False
    kind, index, payload = _last_deleted
    read, write = _source(kind)
    items = read()
    items.insert(min(index, len(items)), payload)      # 插回原位，不是追加到末尾
    write(items)
    _last_deleted = None
    return True


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
    total = len(records)
    for pos, r in enumerate(reversed(records)):
        real = total - 1 - pos                  # 在 RECORDS 里的真实下标，删除时要用
        note = (r.get('notes') or [None])[-1]
        items.append({
            'kind': 'draft', 'kindLabel': '造句', 'id': real,
            'when': f'第 {real + 1} 条',
            'old': r.get('draft') or '',
            'title': r.get('revised') or '',
            'note': note or '',
        })

    timed = []
    for wi, w in enumerate(load_words()):
        detail = w.get('usage') or ''
        if w.get('proficiency') is not None:
            detail = f"熟练度 {w['proficiency']}/4 · " + detail
        timed.append({
            'kind': 'word', 'kindLabel': '单词', 'id': wi,
            'when': w.get('time', ''),
            'title': w.get('word', ''),
            'body': detail,
        })

    for ei, e in enumerate(_load_md_entries(PARSE_SUMMARY_LOG)):
        head = _first_line(e['body'])
        timed.append({
            'kind': 'parse', 'kindLabel': '句型', 'id': ei,
            'when': e['when'],
            'title': head,
            'body': e['body'][len(head):].lstrip(),
        })

    for ei, e in enumerate(_load_md_entries(CHAT_SUMMARY_LOG)):
        timed.append({
            'kind': 'chat', 'kindLabel': '对话', 'id': ei,
            'when': e['when'],
            'body': e['body'],
        })

    timed.sort(key=lambda x: x['when'], reverse=True)   # 时间戳是 'YYYY-MM-DD HH:MM'，字典序即时间序
    items.extend(timed)

    if kind != 'all':
        items = [i for i in items if i['kind'] == kind]
    return items
