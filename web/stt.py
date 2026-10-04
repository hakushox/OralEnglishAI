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

模型文件（约 1.5G）**不随包分发**，第一次运行要从 HuggingFace 下载。
所以这里除了「加载中」还要区分出「下载中」并给出百分比 —— 十几秒的加载可以
让用户干等，十几分钟的下载不行，不说清楚会被当成程序卡死。
"""

import sys
import threading
from pathlib import Path

MODEL_NAME = 'large-v3-turbo'
# faster-whisper 内部把 large-v3-turbo 映射到这个仓库（见 faster_whisper.utils._MODELS）
MODEL_REPO = 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'
# 仓库全部文件的字节数，用来算下载进度。实测值，模型换版本时要跟着改；
# 只用于显示百分比，偏一点不影响正确性。
MODEL_BYTES = 1_621_666_000

_model = None
_error = ''
_phase = 'idle'          # idle / downloading / loading / ready / error
_lock = threading.Lock()


# ---------- 模型文件 ----------

def _repo_dir():
    """HuggingFace 缓存里这个模型的目录（可能不存在）"""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        base = Path(HF_HUB_CACHE)
    except Exception:
        base = Path.home() / '.cache' / 'huggingface' / 'hub'
    return base / ('models--' + MODEL_REPO.replace('/', '--'))


def downloaded():
    """模型权重是否已经在本地。下载途中 model.bin 还只是个 .incomplete，不算数"""
    return any(_repo_dir().glob('snapshots/*/model.bin'))


def _downloaded_bytes():
    """已经落盘的字节数。下载中的 .incomplete 文件也算 —— 它就是进度本身"""
    total = 0
    for f in (_repo_dir() / 'blobs').glob('*'):
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


# ---------- 加载 ----------

def _plans():
    """按优先级返回 (device, compute_type) 候选。

    终端版在 Windows 上写死 `device='cuda'`（作者自己的机器有 N 卡），
    **打包分发不能这么写** —— 绝大多数 Windows 用户没有 NVIDIA 显卡，
    也没装 CUDA 运行库，这一行会让语音功能直接不可用。
    所以 Windows 先试 cuda，失败了退回 CPU；Mac 和 Linux 直接走 CPU
    （macOS 没有 CUDA，ctranslate2 也不支持 Metal）。
    """
    plans = []
    if sys.platform == 'win32':
        plans.append(('cuda', 'float16'))
    # 跟终端版 edgetts.py:770 保持一致的 CPU 参数
    plans.append(('cpu', 'int8'))
    return plans


def _load(WhisperModel):
    """按候选顺序加载，全失败就把最后一个异常抛出去交给上层记录"""
    last = None
    for device, compute_type in _plans():
        try:
            kwargs = {'cpu_threads': 6} if device == 'cpu' else {}
            model = WhisperModel(MODEL_NAME, device=device,
                                 compute_type=compute_type, **kwargs)
            print(f'[stt] 使用 {device}/{compute_type}')
            return model
        except Exception as e:
            print(f'[stt] {device}/{compute_type} 不可用: {str(e)[:120]}')
            last = e
    raise last


def get_model():
    """返回已加载的模型，失败返回 None（原因在 _error 里）"""
    global _model, _error, _phase
    if _model is not None:
        return _model
    with _lock:                      # 预热线程和首个请求可能同时进来，只加载一次
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
            if not downloaded():
                _phase = 'downloading'
                print(f'[stt] 本机还没有语音模型，正在下载 {MODEL_REPO}（约 1.5G，只需一次）…')
            else:
                _phase = 'loading'
                print('[stt] 正在加载 whisper 模型…')
            _model = _load(WhisperModel)
            _phase = 'ready'
            print('[stt] whisper 就绪')
        except Exception as e:
            _error = f'{type(e).__name__}: {e}'
            _phase = 'error'
            print(f'[stt] 加载失败: {_error}')
    return _model


def warm():
    """后台预热。守护线程，不拖慢服务启动，也不阻止退出。"""
    threading.Thread(target=get_model, daemon=True).start()


def ready():
    return _model is not None


def status():
    """给前端的状态。phase 决定提示条说什么，percent 只在下载时有意义。"""
    if _model is not None:
        return {'ready': True, 'phase': 'ready', 'percent': 100, 'msg': ''}
    if _phase == 'downloading':
        pct = min(99, int(_downloaded_bytes() * 100 / MODEL_BYTES))
        return {'ready': False, 'phase': 'downloading', 'percent': pct,
                'msg': f'正在下载语音模型（约 1.5G，只需一次）{pct}%，完成前录音不可用'}
    if _phase == 'error':
        # 最常见的失败是没联网又没有本地模型；别把原始异常摆给用户
        offline = not downloaded()
        return {'ready': False, 'phase': 'error', 'percent': 0,
                'msg': '语音模型没准备好，先联网让它下载完（约 1.5G）' if offline
                       else '语音模型加载失败，录音功能不可用'}
    return {'ready': False, 'phase': _phase, 'percent': 0,
            'msg': '语音模型正在加载，第一次要等十几秒'}


def transcribe(path, language='en'):
    """返回 (文本, 错误说明)。language 传 None 表示让模型自己判断。

    vad_filter 会切掉静音段 —— 浏览器录音前后往往有一两秒空白，
    不过滤的话模型容易在空白处产生幻觉输出。
    """
    model = get_model()
    if model is None:
        return '', status()['msg']
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
