"""
语音转写 —— 接收浏览器上传的音频，用 faster-whisper 转成文字。

跟终端版的区别：
- 终端版 `groq_tts.py:listen()` 自己用 sounddevice 开麦、边录边转写，
  绑死了本机音频设备；浏览器版只负责「收到一个音频文件 → 出文字」。
- 终端版写死 `language='zh'` 还带一串中文 initial_prompt，但练习模块是让用户
  **说英文**的，强制中文会把英文转写成中文字。这里改成按输入框传语言：
  造句/句子/查词框传 `en`，各处追问框和随便问传 `zh`。

模型是懒加载 + 常驻内存的：large-v3-turbo 在 CPU 上加载要十几秒，
既不能放模块顶层（会把服务启动拖成十几秒），也不能每次请求重载。
服务起来后会在后台线程预热，所以用户第一次录音时通常已经就绪。
"""

import sys
import threading

_model = None
_error = ''
_lock = threading.Lock()


def get_model():
    """返回已加载的模型，失败返回 None（原因在 _error 里）"""
    global _model, _error
    if _model is not None:
        return _model
    with _lock:                      # 预热线程和首个请求可能同时进来，只加载一次
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
            print('[stt] 正在加载 whisper 模型…')
            if sys.platform == 'win32':
                _model = WhisperModel('large-v3-turbo', device='cuda', compute_type='float16')
            else:
                # 跟终端版 edgetts.py:770 保持一致的参数
                _model = WhisperModel('large-v3-turbo', device='cpu',
                                      compute_type='int8', cpu_threads=6)
            print('[stt] whisper 就绪')
        except Exception as e:
            _error = f'{type(e).__name__}: {e}'
            print(f'[stt] 加载失败: {_error}')
    return _model


def warm():
    """后台预热。守护线程，不拖慢服务启动，也不阻止退出。"""
    threading.Thread(target=get_model, daemon=True).start()


def ready():
    return _model is not None


def status():
    if _model is not None:
        return {'ready': True, 'msg': ''}
    return {'ready': False, 'msg': _error or '模型正在加载，第一次可能要等十几秒'}


def transcribe(path, language='en'):
    """返回 (文本, 错误说明)。language 传 None 表示让模型自己判断。

    vad_filter 会切掉静音段 —— 浏览器录音前后往往有一两秒空白，
    不过滤的话模型容易在空白处产生幻觉输出。
    """
    model = get_model()
    if model is None:
        return '', _error or '语音模型不可用'
    try:
        segments, _info = model.transcribe(
            path,
            language=language or None,
            vad_filter=True,
            beam_size=5,
        )
        return ''.join(seg.text for seg in segments).strip(), ''
    except Exception as e:
        # 不要把原始异常和临时文件路径吐给用户。最常见的失败就是音频解不开
        # （录了 0 秒、浏览器给的格式坏了），说人话即可；细节留在服务端日志里。
        print(f'[stt] 转写失败: {type(e).__name__}: {e}')
        name = type(e).__name__
        if 'InvalidData' in name or 'Error' in name and 'ffmpeg' in str(e).lower():
            return '', '这段录音读不出来，可能太短或没录上，再试一次'
        return '', '转写出错了，换个说法再试一次'
