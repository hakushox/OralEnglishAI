"""
SpeakNatural 浏览器版后端。

已接真实逻辑：练习主流程（纠正 / 为什么这么改 / 存档）、语音合成、档案页。
仍是假数据（标了 MOCK）：单词、长难句、随便问、查词浮层、语音转写。

流式接口统一按行返回 JSON（NDJSON），事件类型见 web/engine.py 的说明。
"""

import asyncio
import base64
import json
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from web import engine, store, tts

STATIC_DIR = Path(__file__).parent / 'static'

app = FastAPI(title='SpeakNatural')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


@app.get('/')
async def index():
    return FileResponse(STATIC_DIR / 'index.html')


# ==================== 流式辅助 ====================

def ndjson(events, remember=None):
    """把 engine 的事件流转成 NDJSON 响应。

    remember 是可选的回调，流结束后把完整正文交给它 —— 用于多轮对话把
    assistant 的回复追加回 thread。
    """
    def gen():
        full = []
        for ev in events:
            if ev.get('delta'):
                full.append(ev['delta'])
            yield json.dumps(ev, ensure_ascii=False) + '\n'
        if remember is not None:
            remember(''.join(full))

    return StreamingResponse(gen(), media_type='application/x-ndjson')


async def mock_ndjson(chunks, delay=0.02):
    """还没接真实逻辑的接口用这个模拟流式节奏"""
    async def gen():
        for c in chunks:
            yield json.dumps({'delta': c}, ensure_ascii=False) + '\n'
            await asyncio.sleep(delay)
    return StreamingResponse(gen(), media_type='application/x-ndjson')


# ==================== 练习 ====================

@app.post('/api/practice/correct')
def correct(payload: dict = Body(...)):
    text = (payload.get('text') or '').strip()
    if not text:
        return ndjson(iter([{'error': '（没有收到内容）'}]))
    return ndjson(engine.stream_correction(text))


# 「为什么这么改」是多轮追问，需要记住上下文。
# 本地单用户程序，一个全局 thread 就够，不做 session 管理。
_why_thread = []


@app.post('/api/practice/why')
def why(payload: dict = Body(...)):
    global _why_thread
    draft = payload.get('draft', '')
    revised = payload.get('revised', '')
    _why_thread = engine.build_why_messages(draft, revised)

    def remember(full):
        if full:
            _why_thread.append({'role': 'assistant', 'content': full})

    return ndjson(engine.stream_answer(_why_thread, temperature=0.3), remember)


@app.post('/api/practice/why/followup')
def why_followup(payload: dict = Body(...)):
    question = (payload.get('question') or '').strip()
    if not question:
        return ndjson(iter([{'error': '（没有收到问题）'}]))
    if not _why_thread:
        return ndjson(iter([{'error': '（还没有开始分析，先点「为什么这么改」）'}]))

    _why_thread.append({'role': 'user', 'content': question})

    def remember(full):
        if full:
            _why_thread.append({'role': 'assistant', 'content': full})

    return ndjson(engine.stream_answer(_why_thread, temperature=0.3), remember)


@app.post('/api/practice/save')
async def save(payload: dict = Body(...)):
    draft = (payload.get('draft') or '').strip()
    revised = (payload.get('revised') or '').strip()
    if not revised:
        return {'ok': False, 'msg': '没有可保存的内容'}
    total = store.append_record(draft, revised)
    return {'ok': True, 'total': total}


@app.post('/api/practice/save-note')
async def save_note(payload: dict = Body(...)):
    """把「为什么这么改」的最后一轮回答挂到对应记录上"""
    revised = (payload.get('revised') or '').strip()
    notes = [m['content'] for m in _why_thread if m['role'] == 'assistant']
    if not revised or not notes:
        return {'ok': False, 'msg': '没有可保存的分析'}
    matched = store.add_note(revised, notes[-1])
    return {'ok': True, 'matched': matched}


@app.post('/api/practice/transcribe')
async def transcribe():
    """MOCK：真实版本接收浏览器上传的音频，走 faster-whisper 转写"""
    await asyncio.sleep(0.8)
    return {'text': 'I very like this movie because it have good story'}


# ==================== 语音合成 ====================

@app.post('/api/tts')
async def speak(payload: dict = Body(...)):
    """返回 base64 的 mp3 + 词级时间戳。

    音频和时间戳要一起给前端（跟读高亮需要对齐），所以走 JSON 而不是裸 bytes。
    句子都很短，base64 撑大 1/3 可以接受。
    """
    text = (payload.get('text') or '').strip()
    rate = payload.get('rate') or tts.DEFAULT_RATE
    data, marks = await tts.synthesize(text, rate=rate)
    if data is None:
        return {'ok': False, 'msg': '语音合成失败（通常是网络问题）'}
    return {
        'ok': True,
        'audio': base64.b64encode(data).decode('ascii'),
        'marks': marks,
    }


# ==================== 档案 ====================

@app.get('/api/archive')
async def archive(filter: str = 'all'):
    return store.archive_items(filter)


# ==================== 以下仍是 MOCK ====================

@app.get('/api/words')
async def words():
    """MOCK：真实版本读 WORDS_SUMMARY_LOG（store.load_words 已就绪，等界面对接）"""
    return MOCK_WORDS


@app.get('/api/words/{word}')
async def word_detail(word: str):
    """MOCK：真实版本走 review.get_word_usage()"""
    return MOCK_WORD_DETAIL.get(word, {
        'word': word,
        'ipa': '/—/',
        'usage': '（这个词还没有假数据，接真实模型后会现查。）',
        'examples': ['Example sentence goes here.'],
    })


@app.post('/api/parse')
async def parse(payload: dict = Body(...)):
    """MOCK：真实版本走 review.analyze_sentence_structure()"""
    text = (
        'What matters 是主语从句，整句骨架是 A is not B but C。'
        '后半句 how well 省略了 you live，靠平行结构补全'
        '——这是英文里很常见的省略，说的时候记得在 but 前稍作停顿。'
    )

    async def gen():
        yield json.dumps({'tags': '主语从句 + not…but 平行结构'}, ensure_ascii=False) + '\n'
        await asyncio.sleep(0.3)
        for c in text:
            yield json.dumps({'delta': c}, ensure_ascii=False) + '\n'
            await asyncio.sleep(0.018)

    return StreamingResponse(gen(), media_type='application/x-ndjson')


@app.post('/api/chat')
async def chat(payload: dict = Body(...)):
    """MOCK：真实版本按 mode 选 engine.stream_local() 或 engine.stream_cloud()"""
    deep = payload.get('mode') == 'deep'
    text = (
        '这两个在口语里基本通用，但语感有别。a bit 更随意、偏英式，'
        '带一点"就一点点"的轻描淡写；a little 更中性，书面口语都自然。'
        '语法上的硬区别在修饰名词时：a little water 可以直接跟，'
        'a bit 必须加 of，说 a bit of water。'
    ) if deep else (
        '口语里基本通用。差别在 a bit 更随意、偏英式，a little 更中性。'
        '修饰名词时 a little 可以直接跟，a bit 要加 of——'
        'a little water / a bit of water。'
    )
    return await mock_ndjson(list(text), delay=0.02 if deep else 0.012)


@app.get('/api/lookup/{word}')
async def lookup(word: str):
    """MOCK：真实版本打算用本地 ollama 快速出一句释义"""
    await asyncio.sleep(0.35)
    return MOCK_LOOKUP.get(word.lower(), {
        'word': word,
        'ipa': '/—/',
        'def': '（占位释义。接真实模型后，这里用本地模型一句话解释。）',
    })


MOCK_WORDS = [
    {'word': 'subtle', 'proficiency': 3},
    {'word': 'bound to', 'proficiency': 2},
    {'word': 'hold up', 'proficiency': 1},
    {'word': 'rather', 'proficiency': 4},
]

MOCK_WORD_DETAIL = {
    'subtle': {
        'word': 'subtle', 'ipa': '/ˈsʌtl/',
        'usage': '不易察觉的、微妙的。常修饰 difference、change、hint。注意 b 不发音。',
        'examples': ["There's a subtle difference between the two.",
                     'She gave me a subtle hint that it was time to leave.'],
    },
    'bound to': {
        'word': 'bound to', 'ipa': '/baʊnd tuː/',
        'usage': '注定会、必然会。语气比 will 强，带"拦不住"的意味。',
        'examples': ["You practice every day — you're bound to get better."],
    },
    'hold up': {
        'word': 'hold up', 'ipa': '/hoʊld ʌp/',
        'usage': '多义：①拖延、耽搁 ②撑住、站得住脚 ③抢劫。口语里①最常见。',
        'examples': ["Sorry I'm late — traffic held me up."],
    },
    'rather': {
        'word': 'rather', 'ipa': '/ˈræðər/',
        'usage': '①相当、颇（程度副词，比 quite 更含蓄）②宁愿（would rather）。',
        'examples': ['It was rather cold for June.'],
    },
}

MOCK_LOOKUP = {
    'subtle': {'word': 'subtle', 'ipa': '/ˈsʌtl/', 'def': '不易察觉的、微妙的。b 不发音。'},
    'story': {'word': 'story', 'ipa': '/ˈstɔːri/', 'def': '故事、情节。这里指电影的剧情。'},
    'really': {'word': 'really', 'ipa': '/ˈriːəli/', 'def': '真的、非常。可以直接修饰动词，very 不行。'},
    'bit': {'word': 'bit', 'ipa': '/bɪt/', 'def': '一点点。a bit 偏英式、更随意；修饰名词要加 of。'},
}
