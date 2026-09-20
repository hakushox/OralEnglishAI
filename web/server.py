"""
SpeakNatural 浏览器版 —— 骨架阶段。

当前所有接口返回写死的假数据，**不接任何真实模型、不读用户档案**，
目的只是把界面、跳转、流式输出这条链路跑通。

接真逻辑时，把每个标了 MOCK 的函数体换掉即可，接口形状保持不变：
  - 流式接口统一按行返回 JSON（NDJSON），每行形如 {"delta": "..."}；
  - 非流式接口直接返回 JSON。

注意：本文件不 import edgetts.py / review.py 等既有模块，
迁移期间那些文件保持原样不动。
"""

import asyncio
import json
from pathlib import Path

from fastapi import Body, FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / 'static'

app = FastAPI(title='SpeakNatural')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


@app.get('/')
async def index():
    return FileResponse(STATIC_DIR / 'index.html')


async def ndjson(chunks, delay=0.035):
    """把一串文本片段按 NDJSON 逐行吐出去，模拟模型流式输出的节奏"""
    async def gen():
        for c in chunks:
            yield json.dumps({'delta': c}, ensure_ascii=False) + '\n'
            await asyncio.sleep(delay)
    return StreamingResponse(gen(), media_type='application/x-ndjson')


def by_word(text):
    """按词切，保留空格，让前端看起来像真的在逐词生成"""
    parts = text.split(' ')
    return [p + (' ' if i < len(parts) - 1 else '') for i, p in enumerate(parts)]


# ==================== 练习 ====================

@app.post('/api/practice/correct')
async def correct(payload: dict = Body(...)):
    """MOCK：真实版本走 correct_text() + call_cloud_with_fallback()"""
    draft = payload.get('text', '')
    revised = MOCK_CORRECTIONS.get(
        draft.strip().lower(),
        'I really liked this movie — the story was great',
    )
    return await ndjson(by_word(revised), delay=0.06)


@app.post('/api/practice/why')
async def why(payload: dict = Body(...)):
    """MOCK：真实版本走 ask_why_fixed_thread() 的多轮 thread"""
    text = (
        'very 不能直接修饰动词 like，要用 really。'
        'because it have 里主语是第三人称单数 it，动词该是 has；'
        '不过这句更地道的写法是干脆拆成破折号后接一个短句，'
        '口语里比堆 because 从句自然得多。'
    )
    return await ndjson(list(text), delay=0.018)


@app.post('/api/practice/transcribe')
async def transcribe():
    """MOCK：真实版本走 faster-whisper，接收前端上传的音频"""
    await asyncio.sleep(0.8)
    return {'text': 'I very like this movie because it have good story'}


# ==================== 单词 ====================

@app.get('/api/words')
async def words():
    """MOCK：真实版本读 WORDS_SUMMARY_LOG"""
    return MOCK_WORDS


@app.get('/api/words/{word}')
async def word_detail(word: str):
    """MOCK：真实版本走 get_word_usage()"""
    return MOCK_WORD_DETAIL.get(word, {
        'word': word,
        'ipa': '/—/',
        'usage': '（骨架阶段没有这个词的假数据，接真实模型后会现查。）',
        'examples': ['Example sentence goes here.'],
    })


# ==================== 长难句 ====================

@app.post('/api/parse')
async def parse(payload: dict = Body(...)):
    """MOCK：真实版本走 analyze_sentence_structure()"""
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


# ==================== 随便问 ====================

@app.post('/api/chat')
async def chat(payload: dict = Body(...)):
    """MOCK：真实版本按 mode 选 call_local_stream() 或 call_cloud_with_fallback()"""
    deep = payload.get('mode') == 'deep'
    if deep:
        text = (
            '这两个在口语里基本通用，但语感有别。a bit 更随意、偏英式，'
            '带一点"就一点点"的轻描淡写；a little 更中性，书面口语都自然。'
            '语法上的硬区别在修饰名词时：a little water 可以直接跟，'
            'a bit 必须加 of，说 a bit of water。'
        )
    else:
        text = (
            '口语里基本通用。差别在 a bit 更随意、偏英式，a little 更中性。'
            '修饰名词时 a little 可以直接跟，a bit 要加 of——'
            'a little water / a bit of water。'
        )
    return await ndjson(list(text), delay=0.02 if deep else 0.012)


# ==================== 档案 ====================

@app.get('/api/archive')
async def archive(filter: str = 'all'):
    """MOCK：真实版本合并 RECORDS / CHAT_SUMMARY_LOG / PARSE_SUMMARY_LOG / WORDS_SUMMARY_LOG"""
    if filter == 'all':
        return MOCK_ARCHIVE
    return [i for i in MOCK_ARCHIVE if i['kind'] == filter]


# ==================== 查词浮层 ====================

@app.get('/api/lookup/{word}')
async def lookup(word: str):
    """MOCK：真实版本打算用本地 ollama 快速出一句释义（比抓词典网页稳）"""
    await asyncio.sleep(0.35)
    return MOCK_LOOKUP.get(word.lower(), {
        'word': word,
        'ipa': '/—/',
        'def': '（骨架阶段的占位释义。接真实模型后，这里用本地模型一句话解释。）',
    })


# ==================== 假数据 ====================

MOCK_CORRECTIONS = {
    'i very like this movie because it have good story':
        'I really liked this movie — the story was great',
    'yesterday i go to shop and buy some things':
        'Yesterday I went to the shop and picked up a few things',
}

MOCK_WORDS = [
    {'word': 'subtle', 'proficiency': 3},
    {'word': 'bound to', 'proficiency': 2},
    {'word': 'hold up', 'proficiency': 1},
    {'word': 'rather', 'proficiency': 4},
]

MOCK_WORD_DETAIL = {
    'subtle': {
        'word': 'subtle',
        'ipa': '/ˈsʌtl/',
        'usage': '不易察觉的、微妙的。常修饰 difference、change、hint。注意 b 不发音。',
        'examples': [
            "There's a subtle difference between the two.",
            'She gave me a subtle hint that it was time to leave.',
        ],
    },
    'bound to': {
        'word': 'bound to',
        'ipa': '/baʊnd tuː/',
        'usage': '注定会、必然会。语气比 will 强，带"拦不住"的意味。',
        'examples': ['You practice every day — you\'re bound to get better.'],
    },
    'hold up': {
        'word': 'hold up',
        'ipa': '/hoʊld ʌp/',
        'usage': '多义：①拖延、耽搁 ②撑住、站得住脚 ③抢劫。口语里①最常见。',
        'examples': ['Sorry I\'m late — traffic held me up.'],
    },
    'rather': {
        'word': 'rather',
        'ipa': '/ˈræðər/',
        'usage': '①相当、颇（程度副词，比 quite 更含蓄）②宁愿（would rather）。',
        'examples': ['It was rather cold for June.'],
    },
}

MOCK_ARCHIVE = [
    {
        'kind': 'draft', 'kindLabel': '造句', 'when': '今天 14:02',
        'old': 'I very like this movie because it have good story',
        'title': 'I really liked this movie — the story was great',
        'note': 'very 不能直接修饰动词，用 really',
    },
    {
        'kind': 'parse', 'kindLabel': '句型', 'when': '昨天 21:40',
        'title': 'not…but 平行结构与省略',
        'body': '后半句可省略与前半句重复的成分，靠结构对称补全。',
    },
    {
        'kind': 'word', 'kindLabel': '单词', 'when': '昨天 19:15',
        'title': 'subtle',
        'body': '不易察觉的、微妙的。练习 4 题对 3 题，b 不发音这点还会读错。',
    },
    {
        'kind': 'chat', 'kindLabel': '对话', 'when': '3 天前',
        'body': '讨论了 a bit / a little 的区别，以及修饰名词时 of 的有无。',
    },
    {
        'kind': 'draft', 'kindLabel': '造句', 'when': '4 天前',
        'old': 'Yesterday I go to shop and buy some things',
        'title': 'Yesterday I went to the shop and picked up a few things',
        'note': '时间状语是过去就要用过去式；buy some things 偏生硬',
    },
]

MOCK_LOOKUP = {
    'subtle': {'word': 'subtle', 'ipa': '/ˈsʌtl/', 'def': '不易察觉的、微妙的。b 不发音。'},
    'story': {'word': 'story', 'ipa': '/ˈstɔːri/', 'def': '故事、情节。这里指电影的剧情。'},
    'really': {'word': 'really', 'ipa': '/ˈriːəli/', 'def': '真的、非常。可以直接修饰动词，very 不行。'},
    'matters': {'word': 'matter', 'ipa': '/ˈmætər/', 'def': '要紧、有关系。What matters 常作主语从句。'},
    'bit': {'word': 'bit', 'ipa': '/bɪt/', 'def': '一点点。a bit 偏英式、更随意；修饰名词要加 of。'},
}
