from openai import OpenAI
from API_KEY import CEREBRAS_API_KEY, GROQ_API_KEY
import ollama
from prompt_toolkit import prompt
import random
import time
import json
import re
from save_path import update_word_proficiency
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
目标：让用户掌握
 
请充分利用你的知识给出详细、有深度的解答，包括：
- 要用通俗易懂的方式解答，考虑到用户可能有不同的文化习惯而不理解
- 讲清楚适合口语表达还是书面语的场景
- 可以举多个例句帮助理解
- 如果用户写了英文句子让你改，你尽量保持原句用词，改成语法正确的形式。并说明清楚为什么这样改！
- 如果是语法问题，可以简要说明背后的规则或语言习惯来源
 
你的解释主要使用中文，可以有部分英文运用。不要无意义地堆砌内容，内容精简，确保每一段都有实际信息量。
'''

SUMMARY_PROMPT = '''请用中文简要总结以上对话，根据以上对话的篇幅，控制在100字以内，
先检查对话中的assistant的回答是否存在问题，如果有问题并导致了对话发生误解，你需要先指出！
明确指出：用户最初的困惑是什么，最终的解答/结论是什么。
目标：
- 修正对话这中错误的回复和结论然后总结
- 让用户看到后能够领悟，能够掌握要点
不需要逐句复述过程，只保留核心结论。
'''

SUMMARY_PARSE = """请将以上关于这句英文长难句的分析对话总结成一份适合日后复习的学习笔记。
要求：
1. 开头必须完整写出【原句】，一字不改地引用用户最初提供的那句话。
2. 紧接着总结这句话的**核心结构**：主干是什么、有哪些从句/修饰成分、以及理解这句话的关键难点在哪里。这部分是笔记的重点，无论后续对话延伸了多少其他话题，这部分都不能省略或简化。
3. 如果对话过程中用户还问到了其他相关问题（比如某个语法点的用法、跟其他句型的对比、单词辨析等），在原句结构总结之后，另起一段简要记录这些延伸问题和结论，但不要喧宾夺主，篇幅不要超过原句结构总结部分。
4. 不要输出任何开场白（如"好的，以下是总结"），直接从【原句】开始输出。
5. 使用中文解释内容，但句子原文、语法术语的英文原词可以保留英文。
6. 篇幅不要超过100字。
请按照以下格式输出：

【原句】
（原文）

【结构解析】
（主干+从句+难点 + 用户困惑，这是重点）

【延伸讨论】（如果有的话，没有就不写这部分）
（简要记录）
"""

SAVE_NOTE_SUMMARY_PROMPT = '''请用中文总结以上关于这次修改的问答讨论，控制在80字以内。
明确指出：用户最初对哪里不理解，最终的核心结论是什么。
不要逐句复述过程，只保留最有价值的结论，方便以后回顾时能快速看懂当时讨论了什么。'''

CASUAL_CHAT_SYSTEM_PROMPT = '''你是一个地道美式的口语专家。
你可以对于任何关于英文使用的问题进行回答。
必须精简化回答，不要说废话，篇幅尽量短。
你的解释主要使用中文，可以有部分英文运用。'''

SENTENCE_PARSE_SYSTEM_PROMPT = """你是一个专业的英语长难句分析助手，帮助中文母语的英语学习者理解复杂句子结构。
用户会给你一句英文长难句，请按以下步骤分析：
1. **直译与自然**：给一个贴近原文结构的直译，帮助用户看清英文逻辑，而不是给一个已经本地化的意译。然后给一个流畅、符合中文表达习惯的整体翻译，作为对照。
2. **主干提取**：先指出这句话的主谓宾（或主系表）核心骨架是什么，用最简单的话说清楚"这句话到底在说什么"。
3. **结构拆解**：把句子拆分成若干个意群/成分（从句、插入语、分词短语、介词短语等），标出每一部分的语法角色（例如：定语从句修饰什么、状语说明什么条件/原因/时间）。
4. **难点提示**：如果句子里有容易造成理解偏差的地方（比如指代不清的代词、倒装、省略、双重否定、非常规语序），单独指出来提醒。
5. **句型举例**：用这个句子的特点结构，列举1-2个其他句子。目的是让用户彻底掌握这个句法句型。

要求：
- 语言简洁，不要长篇大论解释语法术语，遇到术语用一句话点出即可
- 不需要输出任何开场白或结束语，直接进入分析
"""

REVIEW_PARSE_SYSTEM_PROMPT = """你是一个英语学习分析助手，用户会给你若干条他过去做过的长难句结构分析笔记。

请你从这些笔记中总结出用户在理解英文长难句时，反复出现的困难模式，例如：
- 是否总是卡在某一类结构上（如定语从句嵌套、分词状语、倒装句、省略结构等）
- 是否有特定的从句类型经常被误判语法角色
- 长句子的哪个环节（找主干、判断修饰关系、处理指代）最容易出问题

要求：
- 不要逐条复述每句话的内容，重点是跨多条记录找出共性规律
- 如果样本数量太少、看不出明显规律，直接说明，不要牵强总结
- 给出1-2条具体、可执行的改进建议（比如"多留意由which引导的非限制性定语从句"）
- 使用中文回答，语法术语保留英文原词
"""

WORD_PARSE_SYSTEM_PROMPT = """你是一个专业的英语单词解析助手，帮助英语学习者深入掌握单词的用法。
用户会给你英文单词或短语搭配词组，请按以下步骤分析：

1. **单词**：给出单词的音标（英式/美式）和词性（如果有多个词性，都要列出），判断常用于书面语、口语或都可以。
高级程度，用★表示。高级程度标准判定根据雅思或剑桥词典单词以及地道程度，评级最高★★★★★。评级跟单词罕见度和难度无关。
**词组**： 不需要音标。判断常用于书面语、口语或都可以。高级程度，用★表示。高级程度标准判定根据雅思或剑桥词典单词以及地道程度，评级最高★★★★★。评级跟单词罕见度和难度无关
2. **释义**：给出该单词/词组的中文释义和英文释义，每个释义配一个英文例句。例句要体现单词在真实语境中的用法。
3. **常见搭配**：列出该单词最常见的搭配（介词搭配、固定短语、惯用组合等），用 → 连接说明用法。例如："depend on → 依赖；取决于"。
4. **用法提示**：指出使用该单词/词组时需要注意的地方（及物/不及物、正式/非正式、褒义/贬义、常见错误、特殊变形等）。用一句话说清楚即可。
5. **词汇拓展**：与同义词的用法区别，帮助用户真正理解如何准确使用

要求：
- 单词/词组释义要以Cambridge的为准。
- 语言简洁，例句要真实自然
- 不要长篇大论，每个板块控制在1-3行内
- 不需要输出任何开场白或结束语，直接进入分析
"""

REVIEW_WORDS_SYSTEM_PROMPT = """你是一个专业的英语单词解析助手，用户会给你学习某个单词的笔记。

从对话笔记中总结该单词的用法，例如：
- 该单词的中文释义和英文释义以及1-2句精品例句, 释义要以Cambridge这种权威词典为准。
- 最常见的搭配（介词搭配、固定短语、惯用组合等）及用法
- 与同义词的用法区别，帮助用户真正理解如何准确使用。

要求：
- 找出实质的讨论内容与成果
- 以最初讨论的单词为准，中间也许用户会引出其他单词的疑问，如果能融入到总结中则总结，不能则忽略。
- 不需要输出任何开场白或结束语，直接进入分析
- 100字以内
"""

QUESTION_GEN_SYSTEM_PROMPT = '''你是一个专业的英语老师，根据用户提供的单词和归纳的用法，出题帮助巩固记忆。

要求：
- 给出单词的英文解释，作为explanation，但不能显示该单词。 
- 出2-3道题，包含填空题（1-2题）、中译英（1-2题）
- 题目都以完整句子的形式呈现，不要给ABC选项，用户需要自己填写
- 填空题：给出英文句子，挖空该单词或固定搭配，可结合介词使用，时态、单复数、主动被动，固定搭配等语法点
- 中译英：给出含该词释义的中文句子，让用户翻译成英文
- 题目设置的目的，以及正确答案写进answer_hint里。
  不需要唯一固定答案，符合语法点/词形/搭配即可  

示例：
**explanation**: *phrase*: to perform or speak without having prepared what you are going to do or say
**type**: fill blank
**question**: You can tell that he's just _______ and isn't very good at it, either.

严格输出要求：
- 只输出JSON，不要任何开场白、解释、Markdown代码块标记
- 格式固定如下：

{"questions": [
  {"type": "fill_blank", "explanation": "...", "question": "...", "answer_hint": "..."},
  {"type": "translation",  "explanation": "...", "question": "...", "answer_hint": "..."}
]}
'''

GRADE_ANSWER_SYSTEM_PROMPT = '''你是一个英语测验批改助手。
你会收到一道题目、这道题的参考答案要点、以及用户的回答。
请你只判断这一次回答，不要考虑之前的作答历史。

判断标准：
- "correct"：回答正确，符合参考答案要点，语法用词无实质问题
- "close"：意思对、方向对，但有可以调整的小问题（比如时态、单复数、介词搭配）
- "wrong"：明显错误，或没有回答出参考答案要点

反馈要求：
- 如果是correct：反馈控制在10字以内，简单肯定即可
- 如果是close：明确指出该调整哪里，控制在30字以内
- 如果是wrong：只需指出错在哪个方向，不要直接给出正确答案，控制在30字以内

严格输出要求：
- 只输出JSON，不要任何开场白、解释、Markdown代码块标记
- 格式固定如下：

{"result": "correct/close/wrong", "feedback": "字符串", "correct_answer":"字符串"}
'''

PRACTICE_CONCLUSION_SYSTEM_PROMPT = '''你是一个专业的英语学习诊断分析师。
你会收到用户针对某个单词进行的完整练习测验对话记录（包含出题、用户作答、以及批改过程）。

你的任务不是继续出题或批改，而是回顾整个对话，找出用户在这次测验中暴露的真实问题所在，
帮助用户日后翻看时能一眼看懂自己当时错在哪、该注意什么。

分析要求：
- 逐题回顾用户的作答过程，而不是只看最后一轮的结论
- 重点找出错误背后的原因（例如：搭配记错、时态误用、词性混淆、中式直译思维等），
  不要只描述"答错了"这种表面结果
- 如果用户在多道题中反复出现同一类问题，要点明这是"重复出现"的问题，而不是孤立的一次失误
- 如果用户全程回答准确，如实说明"无明显问题"

熟练度打分标准（0-5分，允许小数如3.5）：
- 5分：全程一次性答对，没有需要提示或纠正的地方
- 3-4分：存在少量错误，但能在提示后迅速修正
- 1-2分：存在较多错误，或需要多次提示才能纠正
- 0分：完全没有掌握，多次错误且无法自行纠正

严格输出要求：
- 只输出JSON，不要任何开场白、解释、Markdown代码块标记（如```json）
- 问题点控制在50字以内，但必须具体、能让用户看懂自己错在哪，不要泛泛而谈
- 输出格式固定如下，键名必须是英文：

{"proficiency": 数字, "issue": "字符串"}
'''

# name 字段用来在下面路由逻辑里区分不同供应商的 header 命名规则
PROVIDERS = [
            {
        'name': 'groq',
        'client': OpenAI(api_key=GROQ_API_KEY, base_url='https://api.groq.com/openai/v1'),
        'models': ['qwen/qwen3.6-27b','openai/gpt-oss-120b']
    },

        {
        'name': 'cerebras',
        'client': OpenAI(api_key=CEREBRAS_API_KEY, base_url='https://api.cerebras.ai/v1'),
        'models': ['gpt-oss-120b']
    },
]

CLIENT_INDEX = 0
MODEL_INDEX = 0

# 记录每个 provider 上次调用后的剩余额度，供下次调用前预判是否值得尝试
# 结构: {'cerebras': {'tokens': int, 'requests': int}, 'groq': {...}}
provider_status = {p['name']: {'tokens': None, 'requests': None} for p in PROVIDERS}


def get_provider_by_name(name: str):
    for p in PROVIDERS:
        if p['name'] == name:
            return p['client']
    raise ValueError(f"没有找到名为 {name} 的 provider")

def get_current_provider():
    return PROVIDERS[CLIENT_INDEX]

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
    print(f'切换到：{PROVIDERS[CLIENT_INDEX]["client"].base_url} / {get_current_model()}')
    return True

def get_reasoning_kwargs(model: str) -> dict:
    if "qwen" in model:
        return {"extra_body": {"reasoning_effort": "none"}}
    return {}  # gpt-oss 系列不做任何调整，用默认 reasoning_effort（更好的输出质量）
# ============ 额度感知路由相关 ============

def estimate_tokens(messages) -> int:
    """粗略估算这次请求的总字符量对应的 token 数，不追求精确"""
    total_chars = sum(len(m.get('content', '')) for m in messages)
    return int(total_chars / 1.5)


def extract_remaining(name: str, headers) -> dict:
    """不同供应商 header 命名不一样，分别取出剩余 tokens 和 requests"""
    if name == 'cerebras':
        tokens = headers.get('x-ratelimit-remaining-tokens-minute')
        requests = headers.get('x-ratelimit-remaining-requests-minute')
    elif name == 'groq':
        tokens = headers.get('x-ratelimit-remaining-tokens')
        requests = headers.get('x-ratelimit-remaining-requests')  # Groq 这个是"每日"口径
    else:
        tokens = requests = None
    return {
        'tokens': int(tokens) if tokens is not None else None,
        'requests': int(requests) if requests is not None else None,
    }


def should_skip(name: str, messages) -> bool:
    """根据上次记录的剩余额度，判断这次要不要干脆别试这个 provider"""
    status = provider_status.get(name, {})
    remaining_tokens = status.get('tokens')
    remaining_requests = status.get('requests')

    # 请求数（尤其 Cerebras 每分钟只有 5 次）告急，直接跳过
    if remaining_requests is not None and remaining_requests < 1:
        return True

    # token 余量明显不够这次请求，跳过
    if remaining_tokens is not None:
        estimated = estimate_tokens(messages)
        if remaining_tokens < estimated * 1.2:
            return True

    return False


# ============ 云端调用（带额度预判 + 失败兜底） ============

def call_cloud_with_fallback(messages, stream_print=True, max_attempts=None, temperature=0.2):
    """
    通用云端调用，自动在多个 provider/model 之间轮询重试。
    调用前先检查上次记录的剩余额度，明显不够就直接跳过，减少无谓的失败等待；
    真正调用失败时依然走 except 兜底，逻辑不变。
    成功返回完整回复文本；全部尝试失败返回 None。
    """
    total_models = sum(len(p['models']) for p in PROVIDERS)
    if max_attempts is None:
        max_attempts = total_models  # 默认把所有 provider/model 组合都试一遍，别提前放弃

    for attempt in range(max_attempts):
        name = get_current_provider()['name']
        extra_kwargs = get_reasoning_kwargs(get_current_model())
        if should_skip(name, messages):
            print(f'[{name}] 额度可能不够，跳过')
            switch_model()
            continue

        try:
            raw_response = get_current_client().chat.completions.with_raw_response.create(
                model=get_current_model(),
                messages=messages,
                temperature=temperature,
                stream=True,
                **extra_kwargs,
            )

            # 记录这次调用后的剩余额度，供下次调用前参考
            remaining = extract_remaining(name, raw_response.headers)
            provider_status[name] = remaining

            stream = raw_response.parse()  # 拿到真正可迭代的流对象

            if stream_print:
                print(f"模型{get_current_provider()['name']} -> {get_current_model()}分析结果：")
                print()
                print('-'*50 + '\n')
            full_content = ''
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_content += delta
                    if stream_print:
                        print(delta, end='', flush=True)
            if stream_print:
                print()
                print('-'*50 + '\n')
            return full_content

        except Exception as e:
            print(f'{get_current_model()} 失败: {str(e)[:100]}...')
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
        print('-'*50 + '\n')
        full_content = ''
        for chunk in local_stream:
            content = chunk['message']['content']
            full_content += content
            print(content, end='', flush=True)
        print('-'*50 + '\n')
        return full_content
    except Exception as e2:
        print(f'本地分析也失败了: {e2}')
        return None


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

def analyze_sentence_structure(sentence, model_name):
    messages = [
        {'role': 'system', 'content': SENTENCE_PARSE_SYSTEM_PROMPT},
    ] + sentence
    print('-'*50+ '\n')
    result = call_cloud_with_fallback(messages, stream_print=True)
    if result is None:
        result = call_local_stream(messages, model_name)
        
    return result

def review_parse_summaries(md_log, model_name, n=10):
    """分析最近的长难句学习记录，找出反复出现的结构性理解难点"""
    content = md_log
    
    recent = content[-n:]
    joined = '\n\n'.join(recent)
    user_prompt = f'以下是用户最近{len(recent)}次长难句分析的学习笔记，请按要求分析:\n\n{joined}'
    messages = [
        {"role": "system", "content": REVIEW_PARSE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    result = call_cloud_with_fallback(messages, stream_print=True)
    if result is None:
        result = call_local_stream(messages, model_name)
    return result

def get_word_usage(context, model_name, first_round=False):
    system_prompt = {'role': 'system', 'content': WORD_PARSE_SYSTEM_PROMPT}
    if first_round:
         system_prompt['content'] += '''\n- 如果用户单词拼写有误或无法构成正确固定搭配短语时，请在回复的**第一行**单独输出 NEED_CONFIRM 这个词（不要加任何其他文字），
  然后换行给出2-3个用户可能想问的单词或短语，等待用户确认后再进行完整解析。
  这种情况下不要输出任何单词的完整解析内容。'''
         
    messages = [system_prompt] + context

    print('-'*50+ '\n')
    result = call_cloud_with_fallback(messages, stream_print=True)
    if result is None:
        result = call_local_stream(messages, model_name)
    return result

def review_words_summaries(word, context, model_name):
    user_prompt = f'以下是用户关于单词{word}的用法的学习笔记，请按要求分析:\n\n{context}'
    messages = [
        {"role": "system", "content": REVIEW_WORDS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    result = call_cloud_with_fallback(messages, stream_print=True)
    if result is None:
        result = call_local_stream(messages, model_name)
    return result

def words_practice(file, demand, model_name):
    if demand:
        if demand == 'random':
            numbers = max(1, len(file) // 3)
            word_item =[t for t in random.sample(file,numbers) if isinstance(t,dict) and t.get('word') is not None] 
            chosen_items = word_item
        elif not demand.isdigit():
            word_item = [t for t in file if isinstance(t, dict) and t.get('word') == demand]
            if not word_item:
                print('暂无历史记录')
                return
            chosen_items = word_item
        else:
            demand_n = int(demand)
            if 3 < demand_n < len(file):
                query = prompt('单次过多，可能影响保存记录，是否继续？（y/n）').strip()
                if query.lower() == 'n':
                    return
            elif demand_n >= len(file):
                query = prompt(f'{demand}套练习？总共才有{len(file)}个学习记录！是否继续？（y/n）').strip()
                if query.lower() == 'n':
                    return
                demand_n = len(file)
            chosen_items = random.sample(file, demand_n)    
    else:
        if not file:
            print('暂无历史记录')
            return
        chosen_items = [file[-1]]
        
    print(f'本次供选择了{len(chosen_items)}个单词来测试，共{3 * len(chosen_items)}道题\n\
（/practice+random ->随机数量抽题；+数字 ->指定数量抽题；+单词 ->指定训练特定单词; 直接/practice ->仅测试最近学习的一个单词）')

    for item in chosen_items:
        word, usage = item['word'], item['usage']
        transcript = run_practice_session(word, usage, model_name)
        if transcript is None:
            continue  # /back 退出了这个单词的练习，或出题失败

        result = practice_conclusion(word, transcript, model_name)
        if result is not None:
            update_word_proficiency(word, result['proficiency'], result['issue'])
            print(f'对于{word}的测验结束，熟练度：{result["proficiency"]} ->已保存')
        else:
            print(f'对于{word}的测验结束（本次未保存评估）')
        time.sleep(1.5)

def _parse_json_response(raw):
    """统一的JSON解析容错，所有结构化调用都走这里"""
    if raw is None:
        return None
    cleaned = re.sub(r'```json|```', '', raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f'解析失败: {e}')
        return None


def generate_questions(word, usage, model_name):
    user_prompt = f'单词：{word}\n用法：{usage}'
    messages = [
        {'role': 'system', 'content': QUESTION_GEN_SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]
    raw = call_cloud_with_fallback(messages, stream_print=False)
    if raw is None:
        raw = call_local_stream(messages, model_name)
    data = _parse_json_response(raw)
    if data is None or 'questions' not in data:
        print('出题失败，跳过该单词')
        return None
    return data['questions']


def grade_answer(question, answer_hint, user_answer, model_name):
    user_prompt = f'题目：{question}\n参考答案要点：{answer_hint}\n用户回答：{user_answer}'
    messages = [
        {'role': 'system', 'content': GRADE_ANSWER_SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]
    raw = call_cloud_with_fallback(messages, stream_print=False)
    if raw is None:
        raw = call_local_stream(messages, model_name)
    data = _parse_json_response(raw)
    if data is None or 'result' not in data:
        # 批改失败时的兜底：不判死，允许用户重答，而不是让流程卡死
        return {'result': 'wrong', 'feedback': '（批改暂时失败，请再试一次）'}
    return data


def run_practice_session(word, usage, model_name):
    """
    返回 transcript（代码自己维护的完整记录），供 practice_conclusion 使用。
    状态（第几题/错了几次/是否结束）全部由代码维护，不依赖模型。
    """
    questions = generate_questions(word, usage, model_name)
    if not questions:
        return None

    transcript = []

    for i, q in enumerate(questions):
        print(f'\n第{i+1}/{len(questions)}题：\n英文解释：{q['explanation']}\n类型：{q['type']}\n题目：{q["question"]}')
        wrong_count = 0

        while True:
            user_answer = prompt('请给出你的回答\n(/pass ->跳过此题；/back ->退出练习)====>：').strip()

            if user_answer.lower() == '/back':
                return transcript if transcript else None
            if user_answer.lower() == '/pass':
                transcript.append({
                    'question': q['question'], 'user_answer': None,
                    'result': 'skipped', 'feedback': None,
                })
                break

            grade = grade_answer(q['question'], q['answer_hint'], user_answer, model_name)
            transcript.append({
                'question': q['question'], 'user_answer': user_answer,
                'result': grade['result'], 'feedback': grade['feedback'],
            })

            if grade['result'] == 'correct':
                print(f'✅ 正确！答案为：{grade["correct_answer"]}。{grade["feedback"]}')
                break
            elif grade['result'] == 'close':
                print(f'⚠️ 接近正确：{grade["feedback"]}')
                # 视为通过，进入下一题，但保留反馈记录供总结参考
                break
            else:
                wrong_count += 1
                if wrong_count >= 3:
                    print(f'❌ 错误。参考答案要点：{q["answer_hint"]}')
                    break
                else:
                    print(f'❌ 错误：{grade["feedback"]}，请再试一次')
                    continue

    return transcript


def practice_conclusion(word, transcript, model_name):
    """transcript 是代码维护的结构化记录，不是原始多轮messages"""
    joined = '\n'.join(
        f'题目：{t["question"]} | 用户回答：{t["user_answer"]} | 判定：{t["result"]} | 反馈：{t["feedback"]}'
        for t in transcript
    )
    user_prompt = f'以下是用户练习单词"{word}"的完整测验记录：\n\n{joined}'
    messages = [
        {'role': 'system', 'content': PRACTICE_CONCLUSION_SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]
    raw = call_cloud_with_fallback(messages, stream_print=False)
    if raw is None:
        raw = call_local_stream(messages, model_name)
    data = _parse_json_response(raw)
    if data is None:
        print('评估生成失败，本次不保存熟练度')
        return None
    try:
        return {'proficiency': float(data['proficiency']), 'issue': data['issue']}
    except (KeyError, ValueError):
        print('评估结果字段异常，本次不保存熟练度')
        return None


