"""
语音合成 —— 把 edge-tts 的音频作为 mp3 bytes 返回给浏览器。

跟终端版的区别：终端版 edgetts.py:_speak() 合成后用 sounddevice 在本机播放，
浏览器版不碰音频设备，直接把字节流交给前端 <audio> 播。
少了 sounddevice / soundfile 这两个依赖，打包也更轻。
"""

import io

import edge_tts

DEFAULT_VOICE = 'en-US-AriaNeural'
DEFAULT_RATE = '+1%'


async def synthesize(text, voice=DEFAULT_VOICE, rate=DEFAULT_RATE):
    """返回 (mp3_bytes, marks)。

    marks 是词级时间戳 [{'word':..., 'offset_ms':..., 'duration_ms':...}, ...]，
    来自 edge-tts 的 WordBoundary 事件，给前端做跟读高亮用。
    终端版没用上这个事件，是浏览器版新加的。
    合成失败返回 (None, [])，由调用方决定怎么提示。
    """
    if not text or not text.strip():
        return None, []
    try:
        # boundary 默认是 'SentenceBoundary'（整句一个时间戳），跟读高亮要词级，必须显式指定
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary='WordBoundary')
        buf = io.BytesIO()
        marks = []
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                buf.write(chunk['data'])
            elif chunk['type'] == 'WordBoundary':
                marks.append({
                    'word': chunk.get('text', ''),
                    # edge-tts 的单位是 100 纳秒，换算成毫秒
                    'offset_ms': chunk['offset'] // 10000,
                    'duration_ms': chunk['duration'] // 10000,
                })
        data = buf.getvalue()
        if not data:
            return None, []
        return data, marks
    except Exception as e:
        print(f'[tts] 合成失败: {str(e)[:120]}')
        return None, []
