from openai import OpenAI
from API_KEY import CEREBRAS_API_KEY, GROQ_API_KEY
import ollama

REVIEW_SYSTEM_PROMPT = '''你是一个专业的英语表达习惯分析师。任务：分析用户提供的一组原始造句（draft），
找出反复出现的结构单一的表达习惯问题，并给出具体的改进建议，帮助用户以后主动避免这些习惯。

请依次分析以下三个维度，每个维度必须输出一条结论：

1. 句式结构相似性：不要求句子开头文字完全一致，只要多个句子在【结构层面】相同即算重复，
   例如 "I like to play football" 和 "I like to swim" 虽然用词不同，
   但结构都是"主语+like to+动词"，应判定为同一种重复模式。
   常见重复结构包括：主语+情态动词/实义动词开头（I want to.../I like to.../I need to...）、
   简单主谓宾、缺少从句/动名词开头/倒装等更丰富句式。

2. 语法/时态：是否反复出现同一类语法错误（例如反复漏掉第三人称单数的 s、反复用错时态）

3. 用词重复：是否反复依赖少数几个简单、笼统的词汇（例如 good/nice/very/happy/a lot）。
   注意：is/are/am/the/a/an/in/on/at 等语法功能词的重复使用是正常且必要的，
   不属于本项分析范围，只关注【可以被替换为更精确表达】的实义词。

判断标准（每个维度都必须遵守）：
- 只有当同一问题在给定句子中出现3次或以上时，才能判定为"存在模式"
- 如果某个维度未达到这个次数标准，必须明确回答"未发现明显问题"，不要牵强附会
- 判定为"存在模式"时，必须从给定的原句中原文摘录至少2个例子作为证据，不能改写、不能编造

改进建议要求（判定为"存在模式"时必须提供）：
- 针对该问题，给出一条具体、可操作的改进方法（不要泛泛地说"多用不同句式"，
  而要具体到"可以尝试用什么结构替换"）
- 从用户提供的原句中挑1个例子，给出改写后的版本，让用户直接看到"同样的意思还能怎么表达"

注意事项：
- 要关注语法准确度，帮助用户理解为什么
- 不要分析拼写错误或明显的偶发笔误
- 要关注是否存在"重复出现"的模式
- 少说废话

输出格式（严格按此结构，用中文，不要额外的开场白或总结）：
1. 句式结构：[存在模式的描述，或"未发现明显问题"]
   例句：[原句1]、[原句2]
   建议：[具体改进方法和原因]
   改写示范：[原句] → [改写后的句子]

2. 语法/时态：[存在模式的描述，或"未发现明显问题"]
   例句：[原句1]、[原句2]
   建议：[具体改进方法和原因]

3. 用词：[存在模式的描述，或"未发现明显问题"]
   例句：[原句1]、[原句2]
   建议：[具体改进方法和原因]
   改写示范：[原句] → [改写后的句子]

（如果某维度"未发现明显问题"，则不需要输出例句/建议/改写示范）
'''

DEEP_ASK_SYSTEM_PROMPT = '''你是一位资深的英语语言学专家和口语教练。
用户会向你提出关于英语表达、语法、地道用法等方面的深入问题。
目标：让用户掌握。
 
请充分利用你的知识给出详细、有深度的解答，包括：
- 要用通俗易懂的方式解答，用户可能有不同的文化习惯，因而不理解
- 必要时说明不同表达方式之间的细微差异（语气、正式程度、使用场景）
- 可以举多个例句帮助理解
- 如果是语法问题，可以简要说明背后的规则或语言习惯来源
 
回答用中文，不要无意义地堆砌内容，确保每一段都有实际信息量。
'''

SUMMARY_PROMPT = '''请用中文简要总结以上对话，根据以上对话的篇幅，控制在100字以内，
明确指出：用户最初的困惑是什么，最终的解答/结论是什么。
目标：让用户看到后能够领悟，能够掌握要点。
不需要逐句复述过程，只保留核心结论。'''

SAVE_NOTE_SUMMARY_PROMPT = '''请用中文总结以上关于这次修改的问答讨论，控制在80字以内。
明确指出：用户最初对哪里不理解，最终的核心结论是什么。
不要逐句复述过程，只保留最有价值的结论，方便以后回顾时能快速看懂当时讨论了什么。'''

CASUAL_CHAT_SYSTEM_PROMPT = '''你是一个地道美式的口语专家。
你可以对于任何关于英文使用的问题进行回答。
必须精简化回答，不要说废话，篇幅尽量短。
你的解释需要中文。'''
 

PROVIDERS = [
        {
        'client': OpenAI(api_key=CEREBRAS_API_KEY, base_url='https://api.cerebras.ai/v1'),
        'models': ['gpt-oss-120b']
    },
    {
        'client': OpenAI(api_key=GROQ_API_KEY, base_url='https://api.groq.com/openai/v1'),
        'models': ['llama-3.3-70b-versatile', 'qwen-qwen3-32b']
    },
]

CLIENT_INDEX = 0
MODEL_INDEX = 0

def get_current_client():
    return PROVIDERS[CLIENT_INDEX]['client']

def get_current_model():
    return PROVIDERS[CLIENT_INDEX]['models'][MODEL_INDEX]

def switch_model():
    global CLIENT_INDEX, MODEL_INDEX
    current_models = PROVIDERS[CLIENT_INDEX]['models']
    if MODEL_INDEX < len(current_models) - 1:
        MODEL_INDEX += 1
    elif CLIENT_INDEX < len(PROVIDERS) - 1:
        CLIENT_INDEX += 1
        MODEL_INDEX = 0
    else:
        CLIENT_INDEX = 0
        MODEL_INDEX = 0
        print('已到达模型列表末尾，回到开头')
        return False
        # raise Exception('所有模型已耗尽')
    print(f'切换到：{PROVIDERS[CLIENT_INDEX]["client"].base_url} / {get_current_model()}')
    return True

def review_patterns(texts_list, model_name):
    """分析用户最近的练习记录，找出反复出现的表达习惯问题"""
    drafts = [t['draft'] for t in texts_list[-30:] if isinstance(t, dict) and 'draft' in t]
    if not drafts:
        print('暂无历史记录')
        return
    print(f'本次调取学习档案中的最近{len(drafts)} / {len(texts_list)}条记录')
    numbered = '\n'.join(f'{i+1}. {d}' for i, d in enumerate(drafts))
    user_prompt = f'以下是用户最近{len(drafts)}句英语练习原句，请按要求分析:\n\n{numbered}'
    messages = [
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    
    result = call_cloud_with_fallback(messages, stream_print=True)
    if result is not None:
        return result

    print('所有云端模型均不可用，切换到本地模型...')
    print('[本地分析结果，准确度可能有限]')
    return call_local_stream(messages, model_name)


def call_cloud_with_fallback(messages, stream_print=True, max_attempts=2, temperature=0.2):
    """
    通用云端调用，自动在多个 provider/model 之间轮询重试。
    记住上次成功的位置：下次调用从该位置继续尝试，失败则自动往后轮询。
    成功返回完整回复文本；全部尝试失败返回 None。
    """
    for attempt in range(max_attempts):
        try:
            response = get_current_client().chat.completions.create(
                model=get_current_model(),
                messages=messages,
                temperature=temperature,
                stream=True,
            )
            if stream_print:
                print(f'模型{get_current_model()}分析结果：')
            full_content = ''
            for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_content += delta
                    if stream_print:
                        print(delta, end='', flush=True)
            if stream_print:
                print()
            return full_content
        except Exception as e:
            print(f'{get_current_model()} 失败: {str(e)[:30]}...')
            switch_model()
    return None
 

def call_local_stream(messages, model_name, temperature=0.2):
    try:
        local_stream = ollama.chat(
            model=model_name,
            messages=messages,
            think=False,
            options={'temperature': temperature},
            stream=True,
        )
        full_content = ''
        for chunk in local_stream:
            content = chunk['message']['content']
            full_content += content
            print(content, end='', flush=True)
        print()
        return full_content
    except Exception as e2:
        print(f'本地分析也失败了: {e2}')
        return None
 
 