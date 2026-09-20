"""
浏览器版的模型调用层 —— 流式（生成器）版本。

跟终端版 review.py:call_cloud_with_fallback() 是两份独立实现，故意不复用：
那个函数返回完整字符串、内部直接 console.print，改成生成器会破坏它 17 个调用点，
而且重试语义会出错（见下面「为什么吐字之后就不再换供应商」）。

这里只**只读**地用 review.py 的 PROVIDERS 配置和几个纯函数，
不调用它有状态的 switch_model()，免得跟终端版共享全局下标。

事件协议（统一 yield dict，由 server.py 转成 NDJSON）：
    {'source': 'groq/qwen...'}  本次实际用的供应商，前端可显示也可忽略
    {'delta':  '片段文本'}       正文，逐块累加
    {'warn':   '提示'}           中途出问题但已有部分内容
    {'error':  '提示'}           彻底失败，没有任何正文
"""

import ollama

import review
from ollama_setup import check_model_installed
from web.prompts import CORRECT_SINGLE_SYSTEM_PROMPT, CORRECTION_SYSTEM_PROMPT

# ---------- 本地模型 ----------

_local_model = None
_local_checked = False


def get_local_model():
    """返回可用的本地 ollama 模型名，没有就返回 None。

    不能用 ollama_setup.ensure_ollama_ready() —— 它有 input() 和 sys.exit()，
    在服务进程里会直接把服务搞挂。check_model_installed() 是纯 subprocess，安全。
    """
    global _local_model, _local_checked
    if not _local_checked:
        try:
            _local_model = check_model_installed()
        except Exception:
            _local_model = None
        _local_checked = True
        print(f'[engine] 本地模型: {_local_model or "不可用"}')
    return _local_model


# ---------- 云端 ----------

def _combos():
    """把 PROVIDERS 拍平成 [(供应商名, client, 模型名), ...]，按配置顺序轮询"""
    return [(p['name'], p['client'], m) for p in review.PROVIDERS for m in p['models']]


_start = 0   # 上次成功的位置，下次从这儿开始，避免每次都从挂掉的那家试起


def _deltas(stream):
    for chunk in stream:
        try:
            piece = chunk.choices[0].delta.content
        except (IndexError, AttributeError):
            continue
        if piece:
            yield piece


def stream_cloud(messages, temperature=0.2):
    """按顺序尝试每个供应商/模型，第一个能吐出内容的就用它。

    **为什么吐字之后就不再换供应商**：内容一旦 yield 给前端就收不回来了。
    如果 groq 吐了半句再挂，这时切 cloudflare 重来，用户屏幕上会变成
    「半句 groq + 一整句 cloudflare」。所以这里的策略是：
    先把第一个 chunk 取到手（这个阶段失败可以静默换下一家），
    一旦开始 yield 就锁定这家，中途断了只补一条 warn。
    """
    global _start
    combos = _combos()
    if not combos:
        return

    for i in range(len(combos)):
        pos = (_start + i) % len(combos)
        name, client, model = combos[pos]
        try:
            raw = client.chat.completions.with_raw_response.create(
                model=model,
                messages=messages,
                temperature=temperature,
                stream=True,
                **review.get_reasoning_kwargs(model),
            )
            gen = _deltas(raw.parse())
            first = next(gen, None)          # 还没吐给前端，这里失败可以安全换下一家
        except Exception as e:
            print(f'[engine] {name}/{model} 失败: {str(e)[:120]}')
            continue

        if first is None:
            print(f'[engine] {name}/{model} 返回空内容，换下一家')
            continue

        _start = pos
        yield {'source': f'{name} / {model}'}
        yield {'delta': first}
        try:
            for piece in gen:
                yield {'delta': piece}
        except Exception as e:
            # 已经吐出去内容了，不能重来，只能告诉用户这次被截断了
            yield {'warn': f'（{name} 中途断流，内容可能不完整：{str(e)[:60]}）'}
        return


# ---------- 本地流式 ----------

def stream_local(messages, temperature=0.2):
    model = get_local_model()
    if model is None:
        return
    try:
        stream = ollama.chat(
            model=model,
            messages=messages,
            think=False,
            options={'temperature': temperature},
            stream=True,
        )
        started = False
        for chunk in stream:
            piece = chunk['message']['content']
            if not piece:
                continue
            if not started:
                started = True
                yield {'source': f'本地 / {model}'}
            yield {'delta': piece}
    except Exception as e:
        print(f'[engine] 本地模型失败: {str(e)[:120]}')
        return


# ---------- 组合：优先 + 兜底 ----------

def _with_fallback(*factories):
    """依次尝试若干个来源，谁先吐出正文就用谁；全都没内容才报错。

    注意 factories 传的是「无参函数」不是生成器对象 —— 生成器一旦创建就开始占资源，
    而且只能消费一次，必须等轮到它了再现造。
    """
    for factory in factories:
        produced = False
        for event in factory():
            if event.get('delta'):
                produced = True
            yield event
        if produced:
            return
    yield {'error': '（生成失败，云端和本地模型均不可用）'}


def stream_answer(messages, temperature=0.2):
    """通用问答：云端优先 + 本地兜底（CLAUDE.md 的硬约定）"""
    return _with_fallback(
        lambda: stream_cloud(messages, temperature),
        lambda: stream_local(messages, temperature),
    )


# ---------- 具体业务 ----------

def stream_correction(text):
    """单句纠正。

    这里是**本地优先**，跟其它场景反过来 —— 终端版 edgetts.py:correct_text()
    就是只走本地的：单句改写任务小、本地够快也免费，不值得占云端额度。
    但本地没装 ollama 时要能顶上，所以后面挂了云端兜底。
    """
    messages = [
        {'role': 'system', 'content': CORRECT_SINGLE_SYSTEM_PROMPT},
        {'role': 'user', 'content': text},
    ]
    return _with_fallback(
        lambda: stream_local(messages, 0.2),
        lambda: stream_cloud(messages, 0.2),
    )


def build_why_messages(draft, revised):
    """开一条「为什么这么改」的独立对话线索，对应终端版的 ask_why_fixed_thread()"""
    import json
    return [
        {'role': 'system', 'content': CORRECTION_SYSTEM_PROMPT},
        {'role': 'user', 'content': json.dumps(
            {'draft': draft, 'revised': revised}, ensure_ascii=False)},
    ]
