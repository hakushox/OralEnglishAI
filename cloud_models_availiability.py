"""
功能:
1. 列出 Cerebras / Groq 当前可用模型
2. 发一次最小测试请求，读取额度相关的响应头
3. 提供一个"智能路由"调用函数：调用前根据上次记录的剩余额度和
   本次请求的估算大小，判断要不要直接跳过某个 provider，减少无谓的失败重试

注意:
- Cerebras 的额度 header 命名规则和 Groq 不完全一样，下面 CEREBRAS 相关字段名
  是按常见命名习惯写的，请先跑一次 debug_print_headers() 核实真实字段名，
  如果对不上，回来改 get_remaining_cerebras() 里的字段名。
- with_raw_response 这次调用本身会真实消耗一点点额度，不建议频繁运行着玩。
"""

from openai import OpenAI
from API_KEY import CEREBRAS_API_KEY, GROQ_API_KEY


# ============ 第一部分：列出可用模型 ============

def list_available_models(name: str, client: OpenAI):
    print(f"\n=== {name} 当前可用模型 ===")
    try:
        models = client.models.list()
        for m in models.data:
            print(m.id)
    except Exception as e:
        print(f"查询失败: {e}")


# ============ 第二部分：查看额度相关的响应头 ============

def debug_print_headers(name: str, client: OpenAI, test_model: str):
    """
    先跑这个，把所有 header 打印出来，核对真实的额度字段名，
    确认后再去下面 get_remaining_xxx() 里改成正确的字段名。
    """
    print(f"\n=== {name} 原始响应头（用于核对字段名） ===")
    try:
        response = client.chat.completions.with_raw_response.create(
            model=test_model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        for key, value in response.headers.items():
            print(f"{key}: {value}")
    except Exception as e:
        print(f"查询失败: {e}")

def debug_print_tts_headers(client, test_text="hi"):
    print("\n=== TTS 原始响应头 ===")
    try:
        response = client.audio.speech.with_raw_response.create(
            model="canopylabs/orpheus-v1-english",
            voice="troy",
            input=test_text,
            response_format="wav",
        )
        for key, value in response.headers.items():
            print(f"{key}: {value}")
    except Exception as e:
        print(f"查询失败: {e}")

def get_remaining_groq(headers) -> int | None:
    value = headers.get("x-ratelimit-remaining-tokens")
    return int(value) if value else None


def get_remaining_cerebras(headers) -> int | None:
    # 字段名请以 debug_print_headers() 实际打印结果为准，这里先按常见命名写
    value = headers.get("x-ratelimit-remaining-tokens-minute")
    return int(value) if value else None


GETTERS = {
    "cerebras": get_remaining_cerebras,
    "groq": get_remaining_groq,
}


# ============ 第三部分：估算本次请求大小 + 判断要不要跳过 ============

def estimate_tokens(text: str) -> int:
    # 粗略估算，中英文混合场景下按字符数 / 1.5 估，不追求精确
    return int(len(text) / 1.5)


def should_switch(remaining_tokens: int, upcoming_text: str) -> bool:
    """剩余额度明显不够这次请求时返回 True，表示该跳过这个 provider"""
    estimated = estimate_tokens(upcoming_text)
    return remaining_tokens < estimated * 1.2  # 留一点余量，别卡得太死


# ============ 第四部分：智能路由调用 ============

# 记录每个 provider 上一次调用后的剩余 token 额度
last_remaining_tokens: dict[str, int] = {}


def call_with_smart_routing(prompt: str, providers: list[dict]):
    """
    providers 每项形如:
    {'name': 'groq', 'client': groq_client, 'model': 'openai/gpt-oss-120b'}
    """
    for provider in providers:
        name = provider["name"]
        remaining = last_remaining_tokens.get(name)

        if remaining is not None and should_switch(remaining, prompt):
            print(f"[{name}] 额度可能不够这次请求，跳过，尝试下一个 provider")
            continue

        try:
            response = provider["client"].chat.completions.with_raw_response.create(
                model=provider["model"],
                messages=[{"role": "user", "content": prompt}],
            )

            getter = GETTERS.get(name)
            if getter:
                new_remaining = getter(response.headers)
                if new_remaining is not None:
                    last_remaining_tokens[name] = new_remaining

            return response.parse()  # 拿到真正的返回内容

        except Exception as e:
            print(f"[{name}] 调用失败: {e}")
            continue

    raise RuntimeError("所有 provider 都不可用")


# ============ 使用示例 ============

if __name__ == "__main__":
    cerebras_client = OpenAI(api_key=CEREBRAS_API_KEY, base_url="https://api.cerebras.ai/v1")
    groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

    # # 1. 先看看两边现在有哪些模型
    # list_available_models("Cerebras", cerebras_client)
    # list_available_models("Groq", groq_client)

    # 2. 第一次用的时候，先跑这个，确认 Cerebras 的真实字段名
    #    确认无误后可以把这两行注释掉，避免每次运行都多消耗一点额度
    # print("开始查询 Cerebras...")
    # debug_print_headers("Cerebras", cerebras_client, test_model="gpt-oss-120b")
    # print("Cerebras 查询结束")

    print("开始查询 Groq...")
    # debug_print_headers("Groq", groq_client, test_model="qwen/qwen3.6-27b")
    debug_print_tts_headers(groq_client)
    print("Groq 查询结束")

    # # 3. 智能路由调用示例
    # providers = [
    #     {"name": "cerebras", "client": cerebras_client, "model": "gpt-oss-120b"},
    #     {"name": "groq", "client": groq_client, "model": "openai/gpt-oss-120b"},
    # ]

    # result = call_with_smart_routing("Hello, please help me correct: I are going to school.", providers)
    # print("\n=== 调用结果 ===")
    # print(result.choices[0].message.content)