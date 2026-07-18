import edge_tts
import sounddevice as sd
import threading
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
import asyncio
import io
import soundfile as sf
import sys
import os


import ollama
import time
import json
from pathlib import Path
from ollama_setup import ensure_ollama_ready
from save_path import (SAVE_DIR, RECORDS, migrate_clean_invalid_records, save_chat_summary,
                       save_parse_summary, save_word_summary, PARSE_SUMMARY_LOG, CHAT_SUMMARY_LOG, WORDS_SUMMARY_LOG)
from check_update import check_and_update

print('正在启动SpeakNatural, 检查更新...')

if getattr(sys, 'frozen', False):
    exe_path = Path(sys.executable)
    app_dir = exe_path.parent
    try:
        updated = check_and_update(app_dir)
        if updated:
            if sys.platform == 'win32':
                print('已启动更新程序，即将退出...')
                sys.exit(0)   # Windows: 交给updater重启，自己只需退出
            else:
                print('更新完成，即将重启...')
                os.execv(str(exe_path), [str(exe_path)])   # macOS: 保持原来的自己重启
    except Exception as e:
        print(f'更新失败，原因{e}\n直接使用当前版本')
        

import subprocess
from review import (
    review_patterns, call_cloud_with_fallback, analyze_sentence_structure, review_parse_summaries, words_practice,
    DEEP_ASK_SYSTEM_PROMPT, SUMMARY_PROMPT, call_local_stream, get_word_usage, review_words_summaries,
    SAVE_NOTE_SUMMARY_PROMPT, CASUAL_CHAT_SYSTEM_PROMPT, SUMMARY_PARSE,
    )
import webbrowser
from urllib.parse import quote
import random
import hashlib

from groq_tts import synthesize_with_groq_tts



MODEL_NAME = ensure_ollama_ready()
time.sleep(1.5) 
os.system('cls' if os.name == 'nt' else 'clear')

def load_json():
    if RECORDS.exists():
        try:
            return json.loads(RECORDS.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            print('json解码错误')
            return []
    return []

migrate_clean_invalid_records()
texts_list = load_json() 

def save_all():
    """把当前内存里的 texts_list 整体写入文件，唯一的写文件出口"""
    RECORDS.write_text(
        json.dumps(texts_list, ensure_ascii=False, indent=4),
        encoding='utf-8'
    )

def write_json(draft, revised, note=None):
    """新增一条记录"""
    if note is None:
        note = []
    texts_list.append({
        'draft': draft,
        'revised': revised,
        'notes': note,
    })
    save_all()

async def _speak(text, rate='+1%', voice='en-US-AriaNeural'):
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                buffer.write(chunk['data'])
        buffer.seek(0)
        return buffer
    except Exception as e:
        print(f'语音生成失败（可能网络连接问题）：{str(e)[:20]}')
        return None

def tts(text, rate='+1%'):
    # text = text.replace('*','~')
    def _run():
        sd.stop()
        buffer = asyncio.run(_speak(text, rate=rate))
        if buffer is None:
            return
        data, samplerate = sf.read(buffer)
        sd.play(data, samplerate)
        sd.wait()
    t1 = threading.Thread(target=_run, daemon=False)
    t1.start()
    t1.join()

GREETINGS = [
    "[excited]Hey, ready to practice some English?",
    "[excited]Let's get that English flowing today!",
    "[excited]Welcome back! Time to sound more natural",
    "[excited]Alright, let's polish up your English",
    "[dramatically]Good to see you. Let's dive in",
]
PARSE_GREETINGS = [
    "[excited]Alright, drop that sentence you want to break down",
    "[dramatically]Ready when you are — throw me a tricky sentence",
    "[sarcastic]Take your time, paste the sentence you're stuck on",
]

WORDS_GREETINGS = [
    "[excited]Got a word in mind? Let's dig into it",
    "[passionate]Which word are we exploring today?",
    "[encouraging]Give me a word, and I'll break it down for you",
]

CHAT_GREETINGS = [
    "[excited]What's on your mind? Let's talk it through",
    "[friendly]Ask me anything about English, I'm all ears",
    "[calm]Go ahead, no question is too small here",
]

GREETING_DIR = SAVE_DIR / 'greetings'

def switch_greetings(trigger_word):
    if trigger_word == 'parse':
        greetings = PARSE_GREETINGS
    elif trigger_word == 'word':
        greetings = WORDS_GREETINGS
    elif trigger_word == 'chat':
        greetings = CHAT_GREETINGS
    elif trigger_word == 'entry':
        greetings = GREETINGS
    else:
        greetings = GREETINGS
    return greetings

def _pregenerate_greetings(trigger_word):
    """依次把剩余的问候语补全，跑在后台线程里，不阻塞主程序"""
    valid_names = set()
    greetings = switch_greetings(trigger_word)
    for text in greetings:
        h = hashlib.md5(text.encode()).hexdigest()[:8]
        filename = f'{trigger_word}_greeting_{h}.wav'
        valid_names.add(filename)
        path = GREETING_DIR / filename
        if path.exists():
            continue
 
        buffer = synthesize_with_groq_tts(text)
        if buffer is None:
            continue
        path.write_bytes(buffer.read())
 
    for f in GREETING_DIR.glob(f'{trigger_word}_greeting_*.wav'):
        if f.name not in valid_names:
            f.unlink()
 
 
def start_greeting(trigger_word):
    """启动时调用：立即生成并播放一条问候语，其余在后台线程慢慢补全"""
    GREETING_DIR.mkdir(parents=True, exist_ok=True)
    greetings = switch_greetings(trigger_word)
    text = random.choice(greetings)
    h = hashlib.md5(text.encode()).hexdigest()[:8]
    path = GREETING_DIR / f'{trigger_word}_greeting_{h}.wav'
 
    if not path.exists():
        buffer = synthesize_with_groq_tts(text)
        if buffer is None:
            return
        path.write_bytes(buffer.read())

    def _play():
        data, samplerate = sf.read(path)
        sd.stop()
        sd.play(data, samplerate)
        sd.wait()
    threading.Thread(target=_play, daemon=True).start()
    # 剩下的在后台线程里慢慢生成，不阻塞主程序
    threading.Thread(target=_pregenerate_greetings, args=(trigger_word,), daemon=True).start()

start_greeting('entry')

def groq_tts(text):
    buffer = synthesize_with_groq_tts(text)
    if buffer is None:
        return None
    data, samplerate = sf.read(buffer)
    sd.stop()
    sd.play(data, samplerate)
    sd.wait()
    buffer.seek(0)
    return buffer


async def list_voices():
    voices = await edge_tts.list_voices()
    for voice in voices:
        if voice['Locale'].startswith('en'):
            print(f"Name: {voice['Name']}, Gender: {voice['Gender']}")


CORRECT_SINGLE_SYSTEM_PROMPT = '''你是一个地道的英文语法纠正器，你需要将语句转换为更为地道的口语
口语需要符合美剧的生活化，或者适合生活对话，要求非常美式的地道口语
如果已经语句很完美了，则不需要变化。
除了最终语句，不要输出任何其他内容！'''
 
def correct_text(text):
    """单句纠正，不带任何上下文，本地模型调用"""
    now = time.time()
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {'role': 'system', 'content': CORRECT_SINGLE_SYSTEM_PROMPT},
            {'role': 'user', 'content': text},
        ],
        options={'temperature': 0.2}, think=False
    )
    elapsed = time.time() - now
    print(f'耗时{elapsed:.2f}...' + '=' * 20 + f'当前模型:{response.model}' + '=' * 20)
    return response.message.content.strip()
 

def open_cambridge(word: str) -> str:
    """在浏览器中打开剑桥词典查询指定单词"""
    word = word.strip().lower()
    if not word:
        return "请输入要查询的单词,示例：/lookup apple"
    encoded = quote(word)
    url = f"https://dictionary.cambridge.org/dictionary/english/{encoded}"
    try:
        webbrowser.open(url)
        return f"已在浏览器打开剑桥词典查询: {word}"
    except Exception as e:
        return f"打开浏览器失败: {e}"
    
CORRECTION_SYSTEM_PROMPT = '''你是一个地道的英文语法纠正器，你需要将语句转换为更为地道的口语
口语需要符合美剧的生活化，或者适合生活对话，要求非常美式的地道口语
你将接收到改动前（draft）和改动后(revised)的两个句子，你来分析改动的原因！
你的主要工作是针对改动前的draft句子来分析：
改动前的句子可能有语法，拼写，句子结构，短语等等问题，你需要指出！

具体要求：
- 如果draft语法没问题，你需要告知。
- 重要：你要先在draft基础上，尽量保持原句用词，改成语法正确的形式。并说明清楚为什么这样改！
- 然后分析为什么revised句子的合理性。如果revised的句意脱离了draft,你也需要指出,但这部分只需超精简，因为这不是重点
- 解释需要中文，必须精简化回答，不要说废话，篇幅尽量短！'''
 
def ask_why_fixed_thread(draft, revised):
    """开启一条针对本次修改的独立对话线索（不使用全局 chat_history）
    返回 (messages, first_answer)，messages 之后可以继续追加、继续追问"""
    context = json.dumps({'draft': draft, 'revised': revised}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": CORRECTION_SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]
    answer = call_cloud_with_fallback(messages, stream_print=True)
    if answer is None:
        print('云端不可用，使用本地模型分析...')
        answer = call_local_stream(messages, MODEL_NAME)
    if answer is None:
        answer = '（分析生成失败，云端和本地模型均不可用）'
    messages.append({'role': 'assistant', 'content': answer})
    return messages, answer

def check_global_jump(user_input):
    """如果是全局跳转命令，直接执行对应模式并返回 True；否则返回 False"""
    cmd = user_input.lower()
    if cmd == '/word':
        word_usage_mode()
        return True
    elif cmd == '/parse':
        parse_sentence_mode()
        return True
    elif cmd == '/chat':
        chat_mode()
        return True
    return False

def chat_mode():
    slash_commands2 = SlashCommandCompleter(['/deep', '/local', '/review','/word', '/parse', '/doc','/back', '/help'])
    session_log = []
    used_cloud = False
    use_cloud_mode = False
    start_greeting('chat')
    while True:
        mode_hint = '[DEEP]' if use_cloud_mode else '[LOCAL]'
        text_inquiry = prompt(f'\n*{mode_hint}* 你想聊什么？\n(/back ->返回; /help ->查看快捷指令):',
                                completer=slash_commands2).strip()
        if text_inquiry.lower() == '/back' or text_inquiry.lower() in ('/word', '/parse','/chat'):
            if used_cloud and len(session_log) > 5:
                summary = call_cloud_with_fallback(
                    session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                    stream_print=False
                )
                if summary is not None:
                    save_chat_summary(summary)
                    print(f'\n[本次对话已总结保存]\n{summary}\n'+ '-' * 20)
                else:
                    summary = call_local_stream(session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                                                MODEL_NAME)
                    save_chat_summary(summary)
                    print(f'\n>本地模型<：[本次对话已总结保存]\n{summary}\n'+ '-' * 20)
            if text_inquiry.lower() != '/back':
                check_global_jump(text_inquiry)
            break
        elif text_inquiry.lower() == '/review':
            if session_log:
                review_session = call_cloud_with_fallback(session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                                                          stream_print=False)
                if review_session is None:
                    review_session = call_local_stream(session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                                                MODEL_NAME)
                session_log.append({'role': 'assistant', 'content': review_session})
            else:
                print('对话尚未产生！')
            continue

        elif text_inquiry.lower() == '/doc':
            if CHAT_SUMMARY_LOG.exists():
                content = CHAT_SUMMARY_LOG.read_text(encoding='utf-8')
                print(content)
                warning = prompt('是否打开文件夹查看(注意：*不要移动，编辑文件内容，否则可能造成不可逆损失*)\n ===>(y/n?):')
                if warning.strip().lower() == 'y':
                    if sys.platform == 'darwin':
                        subprocess.Popen(['open', '-R', str(CHAT_SUMMARY_LOG)])
                    elif sys.platform == 'win32':
                        subprocess.Popen(['explorer', '/select,', str(CHAT_SUMMARY_LOG)])
                    else:
                        subprocess.Popen(['xdg-open', str(CHAT_SUMMARY_LOG)])

            else:
                print('无记录')
            continue

        elif text_inquiry.lower() == '/help':
            print(f'''**本模块为英文知识随便问，问题结束后你可以保存从而形成学习档案**，
            你可以输入:
            
                /doc ->查看自己存储的学习记录
                /review ->让深度模型检查本次对话是否有问题，并保存总结。
                /lookup 单词 ->打开权威词典查单词
                /word -> 跳转到单词解析模块
                /parse -> 跳转到长难句型模块
                ''')
            continue
        elif text_inquiry.lower().startswith('/lookup '):
            word = text_inquiry[len('/lookup '):].strip()
            print(open_cambridge(word))
            continue
        elif text_inquiry.lower() == '/deep':
            if mode_hint == '[DEEP]':
                print('请直接输入你的问题！')
                continue
            use_cloud_mode = True
            print('已切换deep模式，请说出你的困惑')
            continue
        elif text_inquiry.lower().strip() == '/local':
            if mode_hint == '[LOCAL]':
                print('请直接输入你的问题！')
                continue
            use_cloud_mode = False
            print('已切回快速模式，请说出你的问题')
            continue

        session_log.append({'role': 'user', 'content': text_inquiry})

        if len(session_log) > 12:
            print('本次对话历史过长，可能影响对话质量...')       
            sifted_log = call_cloud_with_fallback(session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                                                        stream_print=False)
            if sifted_log is None:
                sifted_log = call_local_stream(session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                                            MODEL_NAME)
            session_log.clear()
            session_log.extend([{'role': 'assistant', 'content': sifted_log},
                                {'role': 'user', 'content': text_inquiry}])

        if use_cloud_mode:
            cloud_messages = [{"role": "system", "content": DEEP_ASK_SYSTEM_PROMPT}] + session_log
            answer = call_cloud_with_fallback(cloud_messages, temperature=0.5)
            if answer is None:
                print('云端不可用，本次改用本地模型回答')
                local_messages = [{"role": "system", "content": CASUAL_CHAT_SYSTEM_PROMPT}] + session_log
                answer = call_local_stream(local_messages, MODEL_NAME)                
            else:
                used_cloud = True
        else:
            local_messages = [{"role": "system", "content": CASUAL_CHAT_SYSTEM_PROMPT}] + session_log
            answer = call_local_stream(local_messages, MODEL_NAME)
        if answer is None:
            answer = '（回答生成失败，云端和本地模型均不可用）'

        session_log.append({'role': 'assistant', 'content': answer})

def word_usage_mode():
    slash_commands = SlashCommandCompleter(['/parse','/chat', '/doc','/practice', '/review', '/lookup','/help'])
    if WORDS_SUMMARY_LOG.exists():
        my_dictionary = json.loads(WORDS_SUMMARY_LOG.read_text(encoding='utf-8'))
    else:
        my_dictionary = []
    session_log = []
    first_round = True
    auto_lookup = None
    current_word = None
    has_new_content = False
    while True:
        if auto_lookup is not None:
            word_input = auto_lookup
            auto_lookup = None
            current_word = word_input
        else:
            if first_round:
                start_greeting('word')
                word_input = prompt('\n>>>>>请输入想学习的单词\n(/back ->返回；/help ->命令查询)====>：', 
                                    completer=slash_commands).strip()
            else:
                word_input = prompt('是否有其他疑问？\n(/save ->保存并查询新单词; /back->返回；/help ->命令查询) ===>: ',
                                    completer=slash_commands).strip()

        if word_input.lower() == '/back' or word_input.lower() in ('/parse', '/chat','/word'):
            if has_new_content:
                tts(current_word)
                usage = review_words_summaries(current_word, session_log, MODEL_NAME)
                save_word_summary(current_word, usage)
                print('-' * 10 + f'{current_word}已保存' + '-' * 10)
            if word_input.lower() != '/back':
                check_global_jump(word_input)
            break
        elif word_input.lower() == '/save':
            if has_new_content:
                tts(current_word)
                usage = review_words_summaries(current_word, session_log, MODEL_NAME)
                save_word_summary(current_word, usage)
                print('-' * 10 + f'{current_word}已保存' + '-' * 10)
            session_log.clear()
            first_round = True
            has_new_content = False
            my_dictionary = json.loads(WORDS_SUMMARY_LOG.read_text(encoding='utf-8'))
            continue
        elif word_input.lower() == '/help':
            print(f'''**本模块会自动保存你的学习记录，当累计一段时间后后，可以复习自己的学习轨迹**，
            你可以输入:
                           
                /save ->保存学习记录
                /doc ->查看自己存储的单词表,精确查找则输入/doc 你要查的单词
                /lookup 单词 ->打开权威词典查单词
                /practice ->练习单词 (需较长的存储记录),希望随机练习则输入/practice random
                /parse -> 跳转到单词解析模块
                /chat -> 跳转到闲聊英文模块
                  
                ''')
            continue
        elif word_input.lower().startswith('/practice'):
            demand = word_input[len('/practice'):].strip()
            if WORDS_SUMMARY_LOG.exists():
                with open(WORDS_SUMMARY_LOG, 'r', encoding='utf-8') as f:
                    word_file = json.load(f)
                if word_file:
                    words_practice(word_file, demand, MODEL_NAME)                    
                else:
                    print('尚无可练习项')
                continue
            else:
                print('尚无可练习项')
                continue

        elif word_input.lower().startswith('/lookup '):
            word = word_input[len('/lookup '):].strip()
            print(open_cambridge(word))
            continue
        elif word_input.lower().startswith('/doc'):
            if not WORDS_SUMMARY_LOG.exists():
                print('尚未有已保存的单词记录')
                continue
            with open(WORDS_SUMMARY_LOG, 'r', encoding='utf-8') as f:
                content = json.load(f)
            if content:
                demand_word = word_input[len('/doc '):].strip()
                if demand_word:
                    for item in content:
                        if item['word'] == demand_word:
                            print("=" * 40)
                            print(f"📖 单词: {item['word']}")
                            print(f"💡 用法: {item['usage']}")
                            print(f"🕐 时间: {item['time']}")
                            print("=" * 40)
                            break
                    else:
                        ask_lookup = prompt(f'尚未收录{demand_word}, 是否查询？（y/n）:')
                        if ask_lookup == 'y':
                            if has_new_content:
                                usage = review_words_summaries(current_word, session_log, MODEL_NAME)
                                save_word_summary(current_word, usage)
                                print('-' * 10 + f'{current_word}已保存' + '-' * 10)
                            session_log.clear()
                            has_new_content = False
                            first_round = True 
                            auto_lookup = demand_word
                        continue
                else:
                    last_five = content[-5:]
                    print(json.dumps(last_five, ensure_ascii=False, indent=4))
                    warning = prompt('是否打开文件夹查看(注意：*不要移动，编辑文件内容，否则可能造成不可逆损失*)\n ====>y/n?:')
                    if warning.strip().lower() == 'y':
                        if sys.platform == 'darwin':
                            subprocess.Popen(['open', '-R', str(WORDS_SUMMARY_LOG)])
                        elif sys.platform == 'win32':
                            subprocess.Popen(['explorer', '/select,', str(WORDS_SUMMARY_LOG)])
                        else:
                            subprocess.Popen(['xdg-open', str(WORDS_SUMMARY_LOG)])
            else:
                print('无记录')
            continue
        if first_round:
            tts(word_input)
            recorded_item = next((item for item in my_dictionary if item['word'] == word_input), None)
            if recorded_item:
                current_word = word_input
                session_log.append({'role': 'user', 'content': word_input})
                print(f'查询你曾学过{current_word},以下是学习记录:')
                answer = recorded_item['usage']
                print(answer)
                session_log.append({'role': 'assistant', 'content': answer})
                first_round = False
                continue
            session_log.append({'role': 'user', 'content': word_input})
            answer = get_word_usage(session_log, MODEL_NAME,first_round=True)
            if any(k in answer.strip() for k in ('need confirm','need_confirm','NEED_CONFIRM' )): 
                session_log.clear()
                first_round = True
                continue
            session_log.append({'role': 'assistant', 'content': answer})
        else:
            session_log.append({'role': 'user', 'content': word_input})
            answer = get_word_usage(session_log, MODEL_NAME)
            session_log.append({'role': 'assistant', 'content': answer})

        if first_round:
            current_word = word_input
        first_round = False
        has_new_content = True

def parse_sentence_mode():
    slash_commands = SlashCommandCompleter(['/word','/chat', '/r','/save' ,'/doc', '/review', '/lookup','/back','/help'])
    session_log = []
    first_round = True
    pro_audio_buffer = None
    while True:
        if first_round:
            start_greeting('parse')
            sentence = prompt('\n>>>>>请输入你想分析并学习的句子\n(/back->返回；/help ->查看快捷指令)===>:',
                              completer=slash_commands).strip()
        else:
            sentence = prompt('是否有其他疑问？(/back->返回；/help ->查看快捷指令)\n ===>: ',
                              completer=slash_commands).strip()

        if sentence.lower() == '/back' or sentence.lower() in ('/word', '/chat','/parse'):
            if session_log:
                print('正在分析本次对话，并保持...')
                session_log.append({'role': 'user', 'content': SUMMARY_PARSE})
                summary = call_cloud_with_fallback(
                    session_log, stream_print=False)
                if summary is not None:
                    save_parse_summary(summary)
                else:
                    summary = call_local_stream(session_log, MODEL_NAME)
                    save_parse_summary(summary)
                print('-' * 10 + '已保存本次完整记录'+ 10* '-')
            if sentence.lower() != '/back':
                check_global_jump(sentence)
            break
        elif sentence.lower() == '/save':
            if session_log:
                print('正在分析本次对话，并保持...')
                session_log.append({'role': 'user', 'content': SUMMARY_PARSE})
                summary = call_cloud_with_fallback(
                    session_log, stream_print=False)
                if summary is not None:
                    save_parse_summary(summary)
                else:
                    summary = call_local_stream(session_log, MODEL_NAME)
                    save_parse_summary(summary)
                print('-' * 10 + '已保存本次完整记录'+ 10* '-')
            else:
                print('当前没有可保存的内容')
            pro_audio_buffer = None
            first_round = True
            session_log.clear() 
            continue
        elif sentence.lower() == '/help':
            print(f'''**本模块会自动保存你的学习记录，当累计一段时间后后，可以复习自己的学习轨迹**，
            你可以输入:
                
                /r ->朗读句子
                /doc ->查看自己存储的学习记录
                /lookup 单词 ->打开权威词典查单词
                /review ->分析最近N条的自己的语法习惯(需较长的存储记录),比如/review 10
                /word -> 跳转到单词解析模块
                /chat -> 跳转到闲聊英文模块
                  
                ''')
            continue
        elif sentence.lower().startswith('/lookup '):
            word = sentence[len('/lookup '):].strip()
            print(open_cambridge(word))
            continue
        elif sentence.lower().startswith('/doc'):
            if not PARSE_SUMMARY_LOG.exists():
                print('尚未有已保存的单词记录')
                continue
            with open(PARSE_SUMMARY_LOG, 'r', encoding='utf-8') as f:
                content = f.read()
            if content:
                record_number = sentence[len('/doc '):].strip()
                if record_number.isdigit():
                    n = int(record_number)
                    entries = [e for e in content.split('\n## ') if e.strip()]
                    latest = entries[-n:]
                    for e in latest:
                        print(f'##{e}')                   
                elif not record_number:
                    entries = [e for e in content.split('\n## ') if e.strip()]
                    latest = entries[-1:]
                    for e in latest:
                        print(f'##{e}')                   
                else:
                    print('非法输入')
                    continue
                warning = prompt('是否打开文件夹查看\n(注意：*不要移动，编辑文件内容，否则可能造成不可逆损失*) ====>y/n?:')
                if warning.strip().lower() == 'y':
                    if sys.platform == 'darwin':
                        subprocess.Popen(['open', '-R', str(PARSE_SUMMARY_LOG)])
                    elif sys.platform == 'win32':
                        subprocess.Popen(['explorer', '/select,', str(PARSE_SUMMARY_LOG)])
                    else:
                        subprocess.Popen(['xdg-open', str(PARSE_SUMMARY_LOG)])
            else:
                print('无记录')
            continue

        elif sentence.lower() == '/r':
            if pro_audio_buffer is not None:
                pro_audio_buffer.seek(0)
                data, samplerate = sf.read(pro_audio_buffer)
                sd.stop()
                sd.play(data,samplerate)
                sd.wait()
            else:
                print('新句子未出现')
            continue

        elif sentence.lower().startswith('/review'):
            if not PARSE_SUMMARY_LOG.exists():
                print('暂无历史记录')
                continue
            content = PARSE_SUMMARY_LOG.read_text(encoding='utf-8')
                # 按 "## " 时间戳把文件切成一条条记录
            raw_entries = content.split('\n## ')
            entries = ['## ' + e.strip() for e in raw_entries if e.strip()]
            if not entries:
                print('暂无历史记录')
                continue

            numbers = sentence[len('/review '):].strip()
            if numbers.isdigit():
                print(f'显示最近{numbers}条精细分析：')
                result = review_parse_summaries(entries, MODEL_NAME, n=int(numbers))
            elif numbers == 'all':
                print(f'显示全部记录的分析结果：')
                result = review_parse_summaries(entries, MODEL_NAME, n=len(entries))
            else:
                print('默认显示前10条:')
                result = review_parse_summaries(entries, MODEL_NAME)
            continue

        if first_round:
            pro_audio_buffer = groq_tts(sentence)  #此函数返回buffer
            if pro_audio_buffer is None:
                tts(sentence)

        session_log.append({'role': 'user', 'content': sentence})
        answer = analyze_sentence_structure(session_log, MODEL_NAME)
        session_log.append({'role': 'assistant', 'content': answer})
        first_round = False


class SlashCommandCompleter(Completer):
    def __init__(self, commands):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith('/'):
            return  # 不是斜杠开头，不弹出任何补全
        for cmd in self.commands:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


slash_commands1 = SlashCommandCompleter(['/parse', '/word', '/help', '/review', '/lookup', '/l', '/ll','/doc','/chat'])

new = None
new_c = None
pro_audio_buffer = None

while True:
    p = prompt('\n>>>>>输入你尝试写的英文句子\n(/help -> 查看快捷指令)===>：',
               mouse_support=True, completer=slash_commands1).strip()
    
    if p == '/l':
        if new is not None:
            print(f'repeating: {new}')
            tts(new)
        else:
            print('还未有可复述内容')
        continue
    elif p == '/ll':
        if new_c is not None:
            if pro_audio_buffer is not None:
                pro_audio_buffer.seek(0)
                data, samplerate = sf.read(pro_audio_buffer)
                sd.stop()
                sd.play(data, samplerate)
                sd.wait()
            else:
                buffer = synthesize_with_groq_tts(f'[professionally]{new_c}')
                if buffer is not None:
                    pro_audio_buffer = buffer
                    print(f'repeating[pro]: {new_c}')
                    data, samplerate = sf.read(buffer)
                    sd.stop()
                    sd.play(data,samplerate)
                    sd.wait()
                else:
                    print(f'repeating: {new_c}')
                    tts(new_c)
        else:
            print('还未有可复述内容')
        continue
    elif check_global_jump(p):
        continue
    elif p.lower() == '/help':
        print(f'''**当看到输入英文(or type "/help" -> 查看其他口令）**，你可以输入:
              
                /parse -> 进入长难句的句子分析模式
                /chat ->进入英语使用杂问模式
                /word -> 进入单词解析模块
                /l ->重新朗读刚才的输入句
                /ll ->重新朗读刚才的修改句
                /doc ->查看自己存储的学习记录
                /lookup 单词 ->打开权威词典查单词
                /review ->分析自己的语法习惯(需较长学习记录，当前{len(texts_list)}条)
              ''')
        continue
    elif p.lower() == '/doc':
        if RECORDS.exists():
            content = json.loads(RECORDS.read_text(encoding='utf-8'))
            n = 1
            print('-' * 10 + f'记录第{n}条' + '-' * 10)
            for item in content[-3:]:
                print()
                print(f"原输入：{item['draft']}")
                print(f"修正后：{item['revised']}")
                n += 1
                if item.get('notes'):
                    for note in item['notes']:
                        print(note)
                print()
                print('-' * 10 + f'记录第{n}条' + '-' * 10)
            print('-' *10 +'以上为最近的三条记录' + '-' *10)
            warning = prompt('是否打开文件夹查看(注意：*不要移动，编辑文件内容，否则可能造成不可逆损失*)\n===> (y/n?):')
            if warning.strip().lower() == 'y':
                if sys.platform == 'darwin':
                    subprocess.Popen(['open', '-R', str(RECORDS)])
                elif sys.platform == 'win32':
                    subprocess.Popen(['explorer', '/select,', str(RECORDS)])
                else:
                    subprocess.Popen(['xdg-open', str(SAVE_DIR)])

        else:
            print('无记录')
        continue
    elif p.lower().startswith('/lookup '):
        word = p[len('/lookup '):].strip()
        print(open_cambridge(word))
        continue
    elif p.lower() == '/review':
        review_patterns(texts_list, MODEL_NAME)
        continue

    elif p.lower() == '/chat':
        chat_mode()
        continue
    elif p.lower() == '/parse':
        parse_sentence_mode()
        continue
    else:
        new = p

    tts(new)
    new_c = correct_text(new)
    print(f'调整后： {new_c}')
    tts(new_c)
    pro_audio_buffer = None

    saved_1 = False
    while True:
        ask_save = prompt(f'是否保存？\n1->yes/ 2-> no/ 3-> play again / 4-> why fix it: ').strip()

        if ask_save == '1':
            if saved_1:
                print('已经保存过了。')
                continue
            write_json(new, new_c)
            saved_1 = True
            print('-' * 10 + f'json已记录。总共{len(texts_list)}条' + '-' * 10)
            continue
        elif ask_save == '2' or ask_save.lower() in ('/chat', '/parse', '/word'):
            if ask_save.lower() != '2':
                check_global_jump(ask_save)
            break
        elif ask_save == '3':
            if pro_audio_buffer is not None:
                pro_audio_buffer.seek(0)
                data, samplerate = sf.read(pro_audio_buffer)
                sd.stop()
                sd.play(data, samplerate)
                sd.wait()
            else:
                buffer = synthesize_with_groq_tts(f'[professionally]{new_c}')
                if buffer is not None:
                    pro_audio_buffer = buffer
                    print(f'repeating[pro]: {new_c}')
                    data, samplerate = sf.read(buffer)
                    sd.stop()
                    sd.play(data, samplerate)
                    sd.wait()
                else:
                    print(f'repeating: {new_c}')
                    tts(new_c)
            continue
        elif ask_save == '4':
            thread, chat = ask_why_fixed_thread(new, new_c)
            rounds = 0
            saved = False
            last_saved_index = None
            while True:
                keep_asking = prompt("\n还有什么不解?\n(或/save -> 保存本次分析；/back -> 返回): ").strip()
                if keep_asking.lower() == '/back':
                    break
                elif keep_asking == '/save':
                    if saved:
                        print('请勿重复保存！')
                        continue
                    if rounds > 2:
                        summary_request = thread + [{'role': 'user', 'content': SAVE_NOTE_SUMMARY_PROMPT}]
                        to_save = call_cloud_with_fallback(summary_request, stream_print=True)
                        if to_save is None:
                            to_save = call_local_stream(summary_request, MODEL_NAME)
                    else:
                        to_save = chat

                    if to_save is None:
                        print('总结生成失败（云端和本地均不可用），改为保存最近一次回复')
                        to_save = chat if chat is not None else '（分析生成失败，未保存有效内容）'

                    for i in texts_list:
                        if i.get('revised') == new_c:
                            if 'notes' not in i:
                                i['notes'] = []      
                            if last_saved_index is not None and 0 <= last_saved_index < len(i['notes']):                                       
                                i['notes'][last_saved_index] = to_save
                            else:
                                i['notes'].append(to_save)
                                last_saved_index = len(i['notes']) - 1 

                            save_all()
                            print('已保存。')                        
                            break
                    else:
                        write_json(new, new_c, [to_save])
                        last_saved_index = 0
                        print('-' * 10 + '已保存完整结果' + '-' * 10 )

                    saved = True

                else:
                    rounds += 1
                    saved = False
                    thread.append({'role': 'user', 'content': keep_asking})
                    chat = call_cloud_with_fallback(thread,stream_print=True)
                    if chat is None:
                        chat = call_local_stream(thread, MODEL_NAME)
                    if chat is None:
                        chat = '（回答生成失败，云端和本地模型均不可用）'
                    thread.append({'role': 'assistant', 'content': chat})
            break

