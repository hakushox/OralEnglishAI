"""
Groq TTS（Orpheus）独立模块。

设计原则：
- 不放进 review.py 的 PROVIDERS，因为那套结构和 switch_model()/should_skip()
  都是为"多个 LLM 互相轮询"设计的，TTS 目前只有一家供应商，语义不同，
  强行塞进去会导致轮询逻辑对不上、额度估算方式也不一样。
- 复用 review.py 里已经建好的 Groq client，不重复创建。
- 额度预判逻辑独立维护（tts_status），和 LLM 那边的 provider_status 互不干扰。
"""

from review import get_provider_by_name  # 复用 review.py 里已建好的 client 查找方式
import io

import time
import threading
import numpy as np
import sounddevice as sd



# TTS 专用的额度记录，字段名已通过实测确认，和 chat completion 那边完全一致
tts_status = {'tokens': None, 'requests': None}


def extract_tts_remaining(headers) -> dict:
    tokens = headers.get('x-ratelimit-remaining-tokens')
    requests = headers.get('x-ratelimit-remaining-requests')
    return {
        'tokens': int(tokens) if tokens is not None else None,
        'requests': int(requests) if requests is not None else None,
    }


def should_skip_tts(text: str) -> bool:
    """额度明显不够这次 TTS 请求时返回 True，调用方应退回 edge_tts"""
    remaining_requests = tts_status.get('requests')
    if remaining_requests is not None and remaining_requests < 1:
        return True

    remaining_tokens = tts_status.get('tokens')
    if remaining_tokens is not None:
        estimated = len(text)  # TTS 按字符计，直接用文本长度估算
        if remaining_tokens < estimated * 1.2:
            return True

    return False

#autumn、diana、hannah、austin、daniel、troy
def synthesize_with_groq_tts(text: str, voice: str = "troy"):
    """返回一个类文件对象（BytesIO），和 _speak() 的返回契约保持一致；失败返回 None"""
    if should_skip_tts(text):
        print("Groq TTS 额度可能不够，本次跳过")
        return None

    groq_client = get_provider_by_name('groq')
    try:
        raw_response = groq_client.audio.speech.with_raw_response.create(
            model="canopylabs/orpheus-v1-english",
            voice=voice,
            input=text,
            response_format="wav",
        )
        tts_status.update(extract_tts_remaining(raw_response.headers))

        response = raw_response.parse()
        audio_bytes = response.read()
        return io.BytesIO(audio_bytes)  # 关键：包装成 BytesIO，而不是返回元组
    except Exception as e:
        print(f"Groq TTS 生成失败: {e}")
        return None
    



def listen(model, stop_event:'keyboardlistener', waiting_input: 'threadingevent'):
    # while not stop_event.is_set():
    #     time.sleep(0.05)

    frames =[]
    display_text = ['']

    def transcribe_loop():
        start = time.time()
        while not stop_event.is_set() and not waiting_input.is_set():
            time.sleep(0.1)
            if not frames:
                continue
            
            audio = np.concatenate(frames).squeeze()
            segments, _ = model.transcribe(audio, language='zh', vad_filter=True,
                initial_prompt='E盘, 海豹, 网易云，百度, gmail, 桌面...')
            text = ''.join(seg.text for seg in segments)
            display_text[0] = text
            
            elapsed = time.time() - start
            print(f'\rRecording...{elapsed:.1f}秒。识别中：{text}', end='', flush=True)

            # 3. 内部语音触发停止：直接设置外部的 stop_event
            for keyword in ['发送', '完成']:
                pos = text.rfind(keyword)
                if pos != -1 and len(text) - pos <= 5:
                    stop_event.set()  # 核心：内部和外部共用同一个停止开关
                    break

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())
    
    # 启动后台识别线程
    t = threading.Thread(target=transcribe_loop, daemon=True)
    t.start()

    # 4. 主线程持续录音，只要 stop_event 没被设置，就一直录
    with sd.InputStream(samplerate=16000, channels=1, dtype='float32', callback=callback):
        print("test开始录音...")
        while not stop_event.is_set() and not waiting_input.is_set():
            time.sleep(0.05)

    # 5. 录音结束，通知子线程退出
    t.join(timeout=2)
    print()
    
    if not frames:
        return ''
    if waiting_input.is_set():
        print('正在切换为手动输入模式...')
        return ''
    
    # 6. 最终全量识别
    audio = np.concatenate(frames).squeeze()
    segments, _ = model.transcribe(audio, language='zh', vad_filter=True,
        initial_prompt='E盘, 海豹, 网易云，百度, baidu, gmail, 桌面...')
    text = ''.join(seg.text for seg in segments)

    # 7. 去掉结尾的停止关键词
    for keyword in ['发送', '完成']:
        pos = text.rfind(keyword)
        if pos != -1 and len(text) - pos <= 5:
            text = text[:pos].strip()
            break

    print(f'\n最终识别：{text}')
    return text

