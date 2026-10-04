"""
SpeakNatural 浏览器版后端。

已接真实逻辑：练习主流程、语音合成、档案页（含分析语法习惯 / 删除）、
单词模块、长难句、随便问。
仍是假数据（标了 MOCK）：选词浮层、单词的「出题练一练」。

流式接口统一按行返回 JSON（NDJSON），事件类型见 web/engine.py 的说明。
"""

import asyncio
import base64
import json
import os
import tempfile
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import review

from web import bundle, engine, prompts, stt, store, tts

# 不能写 Path(__file__).parent —— 打包后 __file__ 在 archive 里，目录并不存在
STATIC_DIR = bundle.resource('web', 'static')

app = FastAPI(title='SpeakNatural')


class NoCacheStatic(StaticFiles):
    """前端文件一律不许浏览器缓存。

    本地程序，文件就在硬盘上，重读的代价是零；而缓存的代价很大 ——
    改完前端后页面还在跑旧 JS，表现成"功能没生效"，极难和"后端没重启"区分开。
    """
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers['Cache-Control'] = 'no-store, must-revalidate'
        return response


app.mount('/static', NoCacheStatic(directory=STATIC_DIR), name='static')

# 后台预热 whisper：模型加载要十几秒，等用户第一次录音才加载体验很差
stt.warm()


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

    # 追加约束，避免模型每轮都把第一轮那套三段式分析重跑一遍。
    # 存进 thread 的是原问题，发给模型的才带约束 —— 否则约束会污染后续上下文，
    # 也会让「总结存档」把这段指令当成用户说的话。
    _why_thread.append({'role': 'user', 'content': question})
    messages = _why_thread[:-1] + [
        {'role': 'user', 'content': question + prompts.FOLLOWUP_GUARD}
    ]

    def remember(full):
        if full:
            _why_thread.append({'role': 'assistant', 'content': full})

    return ndjson(engine.stream_answer(messages, temperature=0.3), remember)


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
    """把「为什么这么改」的讨论挂到对应记录上。

    只要追问过就先总结再存。

    终端版 edgetts.py:944 的阈值是"追问超过 3 次"，太高了：
    只追问一轮时它存最后一条回复，而第一轮的语法分析（真正的重点）就丢了。
    这里改成只有"从没追问过"才直接存那一条，否则一律总结。
    """
    revised = (payload.get('revised') or '').strip()
    draft = (payload.get('draft') or '').strip()
    answers = [m['content'] for m in _why_thread if m['role'] == 'assistant']
    if not revised or not answers:
        return {'ok': False, 'msg': '没有可保存的分析'}

    if len(answers) > 1:
        note = engine.collect(engine.stream_answer(
            _why_thread + [{'role': 'user', 'content': prompts.SAVE_NOTE_SUMMARY_PROMPT}],
            temperature=0.2))
        note = note or answers[-1]          # 总结失败就退回最后一条，别让用户白存
    else:
        note = answers[-1]

    matched = store.add_note(revised, note, draft)
    return {'ok': True, 'matched': matched, 'summarized': len(answers) > 1, 'note': note}


@app.get('/api/env')
def env():
    """运行环境自检，前端进页面就问一次、语音模型没就绪时接着轮询。

    两件事用户必须知道，否则会把「缺东西」当成「程序坏了」：
    语音模型是否还在下载（约 1.5G，不随包分发），本机有没有 ollama
    （没有的话纠正会走云端，要联网）。写成 def 走线程池 ——
    get_local_model() 第一次会 subprocess 跑 ollama list。
    """
    return {'stt': stt.status(), 'local_model': engine.get_local_model()}


@app.post('/api/transcribe')
def transcribe(audio: UploadFile = File(...), lang: str = Form('en')):
    """接收浏览器录的音频，转成文字。

    lang 由前端按输入框传：造句/句子/查词框传 en，追问框和随便问传 zh，
    传 auto 则让模型自己判断。写成 def（非 async）是有意的 ——
    转写是 CPU 密集且阻塞的，FastAPI 会把同步端点放进线程池，不会卡住事件循环。
    """
    suffix = Path(audio.filename or 'rec.webm').suffix or '.webm'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio.file.read())
        tmp = f.name
    try:
        text, err = stt.transcribe(tmp, None if lang == 'auto' else lang)
    finally:
        os.unlink(tmp)
    if err:
        return {'ok': False, 'msg': err}
    if not text:
        return {'ok': False, 'msg': '没听清，再说一次？'}
    return {'ok': True, 'text': text}


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


@app.post('/api/archive/delete')
async def delete_record(payload: dict = Body(...)):
    """删一条记录。删掉的内容在内存里留一份，可以撤销 ——
    这是用户攒了很久的学习档案，误删不该没救。"""
    kind = payload.get('kind') or ''
    index = payload.get('id')
    if not isinstance(index, int):
        return {'ok': False, 'msg': '缺少记录编号'}
    ok = store.delete_item(kind, index)
    return {'ok': ok, 'msg': '' if ok else '这条记录已经不在了，刷新一下看看'}


@app.post('/api/archive/undo')
async def undo_delete():
    ok = store.restore_last()
    return {'ok': ok, 'msg': '' if ok else '没有可撤销的删除'}


@app.post('/api/archive/analyze')
def analyze_patterns():
    """分析语法习惯。复用 review.py:REVIEW_SYSTEM_PROMPT，
    取法跟终端版 review_patterns() 一致：最近 30 条 draft。"""
    drafts = [r['draft'] for r in store.load_records()[-30:] if r.get('draft')]
    if len(drafts) < 3:
        return ndjson(iter([{'error': f'记录太少（{len(drafts)} 条），攒到 3 条以上再分析'}]))
    numbered = '\n'.join(f'{i + 1}. {d}' for i, d in enumerate(drafts))
    messages = [
        {'role': 'system', 'content': review.REVIEW_SYSTEM_PROMPT},
        {'role': 'user', 'content': f'以下是用户最近{len(drafts)}句英语练习原句，请按要求分析:\n\n{numbered}'},
    ]
    return ndjson(engine.stream_answer(messages, temperature=0.3))


# ==================== 以下仍是 MOCK ====================

@app.get('/api/words')
async def words():
    """生词本列表。已经是真实数据（store.load_words 读 WORDS_SUMMARY_LOG）。

    proficiency 可能不存在 —— 只有做过「出题练一练」的词才有，前端要有"未测过"态。
    """
    # 带上 usage，生词本抽屉里点开就能就地看笔记，不用再发一次请求。
    # 数据量小（几十条 × 几百字），一次给完最省事。
    raw = store.load_words()
    total = len(raw)
    return [
        {
            # id 是在 WORDS_SUMMARY_LOG 里的真实下标 —— 下面 reversed 过，
            # 显示顺序跟存储顺序相反，删除必须按真实下标走
            'id': total - 1 - i,
            'word': w.get('word', ''),
            'time': w.get('time', ''),
            'proficiency': w.get('proficiency'),
            'issue': w.get('issue', ''),
            'usage': w.get('usage', ''),
            # 老记录没有 stars 字段，退回从正文里现抽，免得需要数据迁移
            'stars': w.get('stars') or store.extract_stars(w.get('usage', '')),
        }
        for i, w in enumerate(reversed(raw))       # 最近存的排前面
    ]


@app.get('/api/words/{word}')
async def word_note(word: str):
    """读某个词**已经存下来的笔记**（不是重新解析）。真实数据。"""
    for w in store.load_words():
        if w.get('word', '').lower() == word.lower():
            return {'ok': True, **w}
    return {'ok': False, 'msg': '生词本里没有这个词'}


# 单词解析也是多轮的（查完可以追问），跟 _why_thread 一个道理：
# 本地单用户程序，一个全局 thread 就够，不做 session 管理。
_word_thread = []


def _remember_word(full):
    if full:
        _word_thread.append({'role': 'assistant', 'content': full})


@app.post('/api/word/analyze')
def word_analyze(payload: dict = Body(...)):
    """查词解析。复用 review.WORD_PARSE_SYSTEM_PROMPT，输出是一整段六段式 markdown。

    云端优先（走 stream_answer）—— 这活要词典知识和推理，
    本地 4B 给不出可靠的音标、搭配和同义词辨析。
    """
    global _word_thread
    word = (payload.get('word') or '').strip()
    if not word:
        return ndjson(iter([{'error': '（没有收到要查的词）'}]))
    _word_thread = [
        {'role': 'system', 'content': review.WORD_PARSE_SYSTEM_PROMPT},
        {'role': 'user', 'content': word},
    ]
    return ndjson(engine.stream_answer(_word_thread, temperature=0.3), _remember_word)


@app.post('/api/word/followup')
def word_followup(payload: dict = Body(...)):
    question = (payload.get('question') or '').strip()
    if not question:
        return ndjson(iter([{'error': '（没有收到问题）'}]))
    if not _word_thread:
        return ndjson(iter([{'error': '（先查一个词）'}]))
    # 跟练习页同样的处理：thread 里存原话，发给模型的那份才带约束，
    # 否则约束会污染上下文，也会被"总结存生词本"当成用户说的话
    _word_thread.append({'role': 'user', 'content': question})
    messages = _word_thread[:-1] + [
        {'role': 'user', 'content': question + prompts.FOLLOWUP_GUARD}
    ]
    return ndjson(engine.stream_answer(messages, temperature=0.3), _remember_word)


@app.post('/api/word/open')
async def word_open(payload: dict = Body(...)):
    """打开生词本里已存的词。

    **必须重置服务端的 _word_thread**，把这个词和它的笔记塞进去当上下文。
    不这么做的话：查了 A 词再打开已存的 B 词，追问会在 A 的上下文里作答，
    点「总结」更糟 —— 会把 A 的讨论总结后存到 B 的名下。
    """
    global _word_thread
    word = (payload.get('word') or '').strip()
    for w in store.load_words():
        if w.get('word', '').lower() == word.lower():
            _word_thread = [
                {'role': 'system', 'content': review.WORD_PARSE_SYSTEM_PROMPT},
                {'role': 'user', 'content': w.get('word', '')},
                {'role': 'assistant', 'content': w.get('usage', '')},
            ]
            return {'ok': True, **w,
                    'stars': w.get('stars') or store.extract_stars(w.get('usage', ''))}
    _word_thread = []
    return {'ok': False, 'msg': '生词本里没有这个词'}


# ==================== 单词：出题练一练 ====================
#
# 状态全部由**代码**维护（第几题、错了几次、完整记录），不依赖模型记住上下文 ——
# 终端版 run_practice_session() 就是这个思路，模型只负责出题和判单题。
#
# 关键的安全点：answer_hint（答案要点）**绝不发给前端**。
# 终端版不存在这问题（答案在同一个进程里），浏览器版如果发过去，
# 用户在开发者工具里就能直接看到答案，测验就没意义了。判题必须留在后端。
_quiz = {'word': '', 'usage': '', 'questions': [], 'i': 0, 'wrong': 0, 'transcript': []}

MAX_WRONG = 3        # 同一题错满 3 次就给答案要点、进下一题（跟终端版一致）


def _quiz_active():
    """这轮还有没有在等作答的题。

    不能只判断 questions 非空 —— 答完最后一题后 i 已越界而 questions 还在，
    直接取 questions[i] 会 IndexError，接口返回空响应。
    """
    return bool(_quiz['questions']) and _quiz['i'] < len(_quiz['questions'])


def _quiz_view():
    """当前题目对外的样子 —— 只给题面，不给答案"""
    q = _quiz['questions'][_quiz['i']]
    return {
        'index': _quiz['i'] + 1,
        'total': len(_quiz['questions']),
        'type': q.get('type', ''),
        'explanation': q.get('explanation', ''),
        'question': q.get('question', ''),
        'tries': _quiz['wrong'],
        'max_tries': MAX_WRONG,
    }


@app.post('/api/word/quiz/start')
def quiz_start(payload: dict = Body(...)):
    word = (payload.get('word') or '').strip()
    entry = next((w for w in store.load_words()
                  if w.get('word', '').lower() == word.lower()), None)
    if entry is None:
        return {'ok': False, 'msg': '生词本里没有这个词，先存进来再测'}

    data = engine.collect_json(engine.stream_answer([
        {'role': 'system', 'content': review.QUESTION_GEN_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"单词：{entry['word']}\n用法：{entry.get('usage', '')}"},
    ], temperature=0.6))
    questions = (data or {}).get('questions') or []
    if not questions:
        return {'ok': False, 'msg': '出题失败了，再试一次'}

    _quiz.update(word=entry['word'], usage=entry.get('usage', ''),
                 questions=questions, i=0, wrong=0, transcript=[])
    return {'ok': True, 'q': _quiz_view()}


@app.post('/api/word/quiz/answer')
def quiz_answer(payload: dict = Body(...)):
    if not _quiz_active():
        return {'ok': False, 'msg': '这轮测验已经答完了，点「完成」看评估'}
    answer = (payload.get('answer') or '').strip()
    if not answer:
        return {'ok': False, 'msg': '先写点什么再提交'}

    q = _quiz['questions'][_quiz['i']]
    data = engine.collect_json(engine.stream_answer([
        {'role': 'system', 'content': review.GRADE_ANSWER_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"题目：{q.get('question')}\n"
                                    f"参考答案要点：{q.get('answer_hint')}\n"
                                    f"用户回答：{answer}"},
    ], temperature=0.1))
    # 批改抽风时不判死 —— 让用户重答，而不是卡住整个流程（跟终端版一致）
    grade = data if data and 'result' in data else {
        'result': 'retry', 'feedback': '批改暂时失败，再提交一次'}

    result = grade.get('result')
    if result == 'retry':
        return {'ok': True, 'result': 'retry', 'feedback': grade.get('feedback', '')}

    _quiz['transcript'].append({
        'question': q.get('question'), 'user_answer': answer,
        'result': result, 'feedback': grade.get('feedback'),
    })

    # correct / close 都算过；wrong 允许重试，错满 MAX_WRONG 次才放行
    if result == 'wrong':
        _quiz['wrong'] += 1
        if _quiz['wrong'] < MAX_WRONG:
            return {'ok': True, 'result': 'wrong', 'feedback': grade.get('feedback', ''),
                    'retry': True, 'tries': _quiz['wrong'], 'max_tries': MAX_WRONG}
        # 错满了，把答案要点给出来（这时候才给，不提前泄露）
        return _quiz_advance({'result': 'wrong', 'feedback': grade.get('feedback', ''),
                              'answer': q.get('answer_hint', '')})

    return _quiz_advance({'result': result, 'feedback': grade.get('feedback', ''),
                          'answer': grade.get('correct_answer', '')})


def _quiz_advance(extra):
    _quiz['wrong'] = 0
    _quiz['i'] += 1
    out = {'ok': True, **extra}
    if _quiz['i'] >= len(_quiz['questions']):
        out['done'] = True
    else:
        out['q'] = _quiz_view()
    return out


@app.post('/api/word/quiz/skip')
async def quiz_skip():
    if not _quiz_active():
        return {'ok': False, 'msg': '这轮测验已经答完了，点「完成」看评估'}
    q = _quiz['questions'][_quiz['i']]
    _quiz['transcript'].append({
        'question': q.get('question'), 'user_answer': None,
        'result': 'skipped', 'feedback': None,
    })
    return _quiz_advance({'result': 'skipped', 'feedback': '已跳过',
                          'answer': q.get('answer_hint', '')})


@app.post('/api/word/quiz/finish')
def quiz_finish():
    """诊断这轮测验、打熟练度分并写回生词本"""
    if not _quiz['transcript']:
        return {'ok': False, 'msg': '这轮没有作答记录，不打分'}
    joined = '\n'.join(
        f"题目：{t['question']} | 用户回答：{t['user_answer']} | "
        f"判定：{t['result']} | 反馈：{t['feedback']}"
        for t in _quiz['transcript'])
    data = engine.collect_json(engine.stream_answer([
        {'role': 'system', 'content': review.PRACTICE_CONCLUSION_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"以下是用户练习单词\"{_quiz['word']}\"的完整测验记录：\n\n{joined}"},
    ], temperature=0.2))
    try:
        prof = round(float(data['proficiency']), 1)
        issue = str(data['issue'])
    except (TypeError, KeyError, ValueError):
        return {'ok': False, 'msg': '评估生成失败，这次不记熟练度'}

    saved = store.set_proficiency(_quiz['word'], prof, issue)
    word = _quiz['word']
    _quiz.update(questions=[], i=0, wrong=0, transcript=[])
    return {'ok': True, 'word': word, 'proficiency': prof, 'issue': issue, 'saved': saved}


@app.post('/api/word/save')
async def word_save(payload: dict = Body(...)):
    """把当前解析原样存进生词本（没追问过时用这个）"""
    word = (payload.get('word') or '').strip()
    usage = (payload.get('usage') or '').strip()
    if not word or not usage:
        return {'ok': False, 'msg': '没有可保存的内容'}
    action = store.save_word(word, usage)
    return {'ok': True, 'action': action, 'note': usage,
            'stars': store.extract_stars(usage)}


@app.post('/api/word/save-note')
async def word_save_note(payload: dict = Body(...)):
    """追问过之后存：先用 REVIEW_WORDS_SYSTEM_PROMPT 把整段讨论总结成笔记。

    跟练习页一样，只要追问过就总结 —— 不然存进去的只是最后一条回复，
    前面问出来的东西全丢了。
    """
    word = (payload.get('word') or '').strip()
    answers = [m['content'] for m in _word_thread if m['role'] == 'assistant']
    if not word or not answers:
        return {'ok': False, 'msg': '没有可保存的内容'}

    if len(answers) > 1:
        note = engine.collect(engine.stream_answer(
            _word_thread + [{'role': 'user', 'content': review.REVIEW_WORDS_SYSTEM_PROMPT}],
            temperature=0.2))
        note = note or answers[-1]
    else:
        note = answers[-1]

    # 星级从**第一轮解析**里抽（answers[0]），不是从总结里抽 ——
    # REVIEW_WORDS_SYSTEM_PROMPT 不要求保留星级，总结完就没了
    stars = store.extract_stars(note) or store.extract_stars(answers[0])
    action = store.save_word(word, note, stars)
    return {'ok': True, 'action': action, 'summarized': len(answers) > 1,
            'note': note, 'stars': stars}


# ==================== 长难句 ====================

_parse_thread = []
_parse_sentence = ''


def _remember_parse(full):
    if full:
        _parse_thread.append({'role': 'assistant', 'content': full})


@app.post('/api/parse/analyze')
def parse_analyze(payload: dict = Body(...)):
    """句子结构分析。云端优先 —— 拆从句、判语法角色，本地 4B 不够可靠。"""
    global _parse_thread, _parse_sentence
    sentence = (payload.get('sentence') or '').strip()
    if not sentence:
        return ndjson(iter([{'error': '（没有收到句子）'}]))
    _parse_sentence = sentence
    _parse_thread = [
        {'role': 'system', 'content': review.SENTENCE_PARSE_SYSTEM_PROMPT},
        {'role': 'user', 'content': sentence},
    ]
    return ndjson(engine.stream_answer(_parse_thread, temperature=0.3), _remember_parse)


@app.post('/api/parse/followup')
def parse_followup(payload: dict = Body(...)):
    question = (payload.get('question') or '').strip()
    if not question:
        return ndjson(iter([{'error': '（没有收到问题）'}]))
    if not _parse_thread:
        return ndjson(iter([{'error': '（先分析一个句子）'}]))
    # 同练习/单词模块：thread 存原话，发给模型的那份才带约束
    _parse_thread.append({'role': 'user', 'content': question})
    messages = _parse_thread[:-1] + [
        {'role': 'user', 'content': question + prompts.FOLLOWUP_GUARD}
    ]
    return ndjson(engine.stream_answer(messages, temperature=0.3), _remember_parse)


@app.post('/api/parse/save')
async def parse_save():
    """用 SUMMARY_PARSE 总结成复习笔记再存。

    那个 prompt 明确要求开头一字不改地引用原句，所以总结里自带原文，
    不需要额外拼接。
    """
    if not _parse_thread:
        return {'ok': False, 'msg': '还没有可保存的分析'}
    note = engine.collect(engine.stream_answer(
        _parse_thread + [{'role': 'user', 'content': review.SUMMARY_PARSE}],
        temperature=0.2))
    if not note:
        return {'ok': False, 'msg': '总结生成失败'}
    store.save_parse_note(note)
    return {'ok': True, 'note': note}


@app.post('/api/parse/review')
def parse_review():
    """跨多条笔记找共性困难，对应终端版 review_parse_summaries()"""
    notes = store.recent_md('parse', 10)
    if len(notes) < 2:
        return ndjson(iter([{'error': f'笔记太少（{len(notes)} 条），攒几条再复习'}]))
    joined = '\n\n---\n\n'.join(notes)
    messages = [
        {'role': 'system', 'content': review.REVIEW_PARSE_SYSTEM_PROMPT},
        {'role': 'user', 'content': f'以下是我过去的 {len(notes)} 条长难句分析笔记：\n\n{joined}'},
    ]
    return ndjson(engine.stream_answer(messages, temperature=0.3))


# ==================== 随便问 ====================

# 不含 system 消息 —— 快速/深度两档用的 system prompt 不同，每次请求现拼
_chat_thread = []


def _remember_chat(full):
    if full:
        _chat_thread.append({'role': 'assistant', 'content': full})


@app.post('/api/chat/send')
def chat_send(payload: dict = Body(...)):
    """快速 = 本地优先（CASUAL_CHAT_SYSTEM_PROMPT，短平快）
       深度 = 云端优先（DEEP_ASK_SYSTEM_PROMPT，讲透）"""
    message = (payload.get('message') or '').strip()
    if not message:
        return ndjson(iter([{'error': '（没有收到内容）'}]))
    deep = payload.get('mode') == 'deep'
    _chat_thread.append({'role': 'user', 'content': message})

    # 对话太长会拖垮质量也烧额度，只带最近若干轮
    history = _chat_thread[-12:]
    system = review.DEEP_ASK_SYSTEM_PROMPT if deep else review.CASUAL_CHAT_SYSTEM_PROMPT
    messages = [{'role': 'system', 'content': system}] + history

    if deep:
        events = engine.stream_answer(messages, temperature=0.5)
    else:
        events = engine._with_fallback(
            lambda: engine.stream_local(messages, 0.4),
            lambda: engine.stream_cloud(messages, 0.4),
        )
    return ndjson(events, _remember_chat)


@app.post('/api/chat/save')
async def chat_save():
    """用 SUMMARY_PROMPT 总结整段对话再存。

    那个 prompt 会先检查 assistant 的回答有没有问题、有错先纠正再总结 ——
    所以存下来的是修正过的结论，不是原样复述。
    """
    if not _chat_thread:
        return {'ok': False, 'msg': '还没有可保存的对话'}
    note = engine.collect(engine.stream_answer(
        _chat_thread + [{'role': 'user', 'content': review.SUMMARY_PROMPT}],
        temperature=0.2))
    if not note:
        return {'ok': False, 'msg': '总结生成失败'}
    store.save_chat_note(note)
    return {'ok': True, 'note': note}


@app.post('/api/chat/clear')
async def chat_clear():
    _chat_thread.clear()
    return {'ok': True}


@app.get('/api/lookup/{word}')
async def lookup(word: str):
    """MOCK：真实版本打算用本地 ollama 快速出一句释义"""
    await asyncio.sleep(0.35)
    return MOCK_LOOKUP.get(word.lower(), {
        'word': word,
        'ipa': '/—/',
        'def': '（占位释义。接真实模型后，这里用本地模型一句话解释。）',
    })


MOCK_LOOKUP = {
    'subtle': {'word': 'subtle', 'ipa': '/ˈsʌtl/', 'def': '不易察觉的、微妙的。b 不发音。'},
    'story': {'word': 'story', 'ipa': '/ˈstɔːri/', 'def': '故事、情节。这里指电影的剧情。'},
    'really': {'word': 'really', 'ipa': '/ˈriːəli/', 'def': '真的、非常。可以直接修饰动词，very 不行。'},
    'bit': {'word': 'bit', 'ipa': '/bɪt/', 'def': '一点点。a bit 偏英式、更随意；修饰名词要加 of。'},
}
