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


def synthesize_with_groq_tts(text: str, voice: str = "autumn"):
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