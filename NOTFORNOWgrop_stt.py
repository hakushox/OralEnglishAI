"""
语音转文字（STT）模块，使用 Groq 的 Whisper Large v3。

包含两种录音方式：
1. record_audio_fixed()：固定时长录音，简单直接
2. record_audio_until_enter()：按回车键停止，更贴近"说一句话"的自然交互

用法见文件底部的 __main__ 示例。
"""

import io
import time
import threading

import sounddevice as sd
import soundfile as sf

from review import get_provider_by_name  # 复用已建好的 Groq client


SAMPLE_RATE = 16000  # 16kHz 对语音识别足够，文件比 44.1kHz 小很多，上传更快


def record_audio_fixed(duration: int = 5, samplerate: int = SAMPLE_RATE) -> io.BytesIO:
    """固定时长录音，duration 秒后自动停止"""
    print(f"录音开始，请说话...（{duration} 秒）")
    audio_data = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1, dtype='int16')
    sd.wait()
    print("录音结束")
    return _to_wav_buffer(audio_data, samplerate)


def record_audio_until_enter(samplerate: int = SAMPLE_RATE) -> io.BytesIO:
    """开始录音，用户按回车键停止，适合"说一句话"这种不确定时长的场景"""
    print("按回车开始录音...")
    input()
    print("录音中，说完请按回车停止...")

    frames = []
    stop_flag = threading.Event()

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    stream = sd.InputStream(samplerate=samplerate, channels=1, dtype='int16', callback=callback)
    with stream:
        input()  # 用户按下回车，停止录音
    stop_flag.set()
    print("录音结束")

    import numpy as np
    audio_data = np.concatenate(frames, axis=0)
    return _to_wav_buffer(audio_data, samplerate)


def _to_wav_buffer(audio_data, samplerate: int) -> io.BytesIO:
    """把录到的音频数据打包成内存中的 wav 文件（不落盘）"""
    buffer = io.BytesIO()
    sf.write(buffer, audio_data, samplerate, format='WAV')
    buffer.seek(0)
    buffer.name = "recording.wav"  # SDK 需要文件名后缀来判断格式
    return buffer


def transcribe_with_groq(audio_buffer: io.BytesIO, client) -> str | None:
    """调用 Groq Whisper 转写，返回识别出的文字；失败返回 None"""
    try:
        start = time.time()
        response = client.audio.transcriptions.with_raw_response.create(
            model="whisper-large-v3",
            file=audio_buffer,
        )
        elapsed = time.time() - start
        print(f"转写耗时: {elapsed:.2f} 秒")
        print(f"剩余请求数: {response.headers.get('x-ratelimit-remaining-requests')}")
        result = response.parse()
        return result.text
    except Exception as e:
        print(f"转写失败: {e}")
        return None


if __name__ == "__main__":
    groq_client = get_provider_by_name('groq')

    # 方式一：固定时长
    # buffer = record_audio_fixed(duration=5)

    # 方式二：按回车停止，更贴近实际使用场景
    buffer = record_audio_until_enter()
    print(f"录音文件大小: {len(buffer.getvalue()):,} 字节")
    start = time.time()
    text = transcribe_with_groq(buffer, groq_client)
    print(f"实际网络+转写耗时: {time.time() - start:.2f} 秒")
    if text:
        print(f"识别结果: {text}")