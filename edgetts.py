import edge_tts
import sounddevice as sd
import threading
from prompt_toolkit import prompt
import asyncio
import io
import soundfile as sf

import ollama
import time
import json
from pathlib import Path
from ollama_setup import ensure_ollama_ready
from save_path import SAVE_DIR, RECORDS, migrate_clean_invalid_records, save_chat_summary
from check_update import check_and_update
import sys
import subprocess
from review import (
    review_patterns, call_cloud_with_fallback, 
    DEEP_ASK_SYSTEM_PROMPT, SUMMARY_PROMPT, call_local_stream, 
    SAVE_NOTE_SUMMARY_PROMPT, CASUAL_CHAT_SYSTEM_PROMPT
    )
import webbrowser
from urllib.parse import quote
import os
import random
import hashlib

print('正在启动SpeakNatural, 检查更新...')

if getattr(sys, 'frozen', False):
    exe_path = Path(sys.executable)
    app_dir = exe_path.parent
    try:
        updated = check_and_update(app_dir)
        if updated:
            print('更新完成，即将重启...')
            os.execv(str(exe_path), [str(exe_path)])
    except Exception as e:
        print(f'更新失败，原因{e}\n直接使用当前版本')

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
    "Hey, ready to practice some English?",
    "Let's get that English flowing today.",
    "Welcome back! Time to sound more natural.",
    "Alright, let's polish up your English.",
    "Good to see you. Let's dive in.",
]

GREETING_DIR = SAVE_DIR / 'greetings'

async def _pregenerate_greetings():
    valid_names = set()
    for text in GREETINGS:
        h = hashlib.md5(text.encode()).hexdigest()[:8]
        filename = f'greeting_{h}.mp3'
        valid_names.add(filename)
        path = GREETING_DIR / filename
        if path.exists():
            continue
        buffer = await _speak(text)
        if buffer is None:
            continue
        path.write_bytes(buffer.read())

    for f in GREETING_DIR.glob('greeting_*.mp3'):
        if f.name not in valid_names:
            f.unlink()

def start_greeting():
    """启动时调用：立即生成并播放一条问候语，其余在后台线程慢慢补全"""
    GREETING_DIR.mkdir(parents=True, exist_ok=True)

    text = random.choice(GREETINGS)
    h = hashlib.md5(text.encode()).hexdigest()[:8]
    path = GREETING_DIR / f'greeting_{h}.mp3'

    if not path.exists():
        buffer = asyncio.run(_speak(text))
        if buffer is None:
            return
        path.write_bytes(buffer.read())

    data, samplerate = sf.read(path)
    sd.stop()
    sd.play(data, samplerate)
    sd.wait()

    # 剩下的在后台线程里慢慢生成，不阻塞主程序
    threading.Thread(target=lambda: asyncio.run(_pregenerate_greetings()), daemon=True).start()

start_greeting()


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

new = None
new_c = None

while True:
    p = prompt('输入英文(or type "/help" -> 查看其他口令)\n===>：').strip()
    
    if p == '/l':
        if new is not None:
            print(f'repeating: {new}')
            tts(new)
        else:
            print('还未有可复述内容')
        continue
    elif p == '/ll':
        if new_c is not None:
            print(f'repeating: {new_c}')
            tts(new_c)
        else:
            print('还未有可复述内容')
        continue
    elif p.lower() == '/help':
        print('''**当看到输入英文(or type "/help" -> 查看其他口令）**，你可以输入:
                /chat ->进入闲聊模式（内含 /deep 进入高端模型、/local 切回本地）
                /l ->重新朗读刚才的输入句
                /ll ->重新朗读刚才的修改句
                /doc ->查看自己存储的学习记录
                /lookup 单词 ->打开权威词典查单词
                /review ->分析自己的语法习惯''')
        continue
    elif p.lower() == '/doc':
        if RECORDS.exists():
            content = RECORDS.read_text(encoding='utf-8')
            print(content)
            warning = prompt('是否打开文件夹查看(注意：*不要移动，编辑文件内容，否则可能造成不可逆损失*)\n y/n?:')
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
        session_log = []
        used_cloud = False
        use_cloud_mode = False

        while True:
            mode_hint = '[DEEP]' if use_cloud_mode else '[LOCAL]'
            text_inquiry = prompt(f'*{mode_hint}* 你想聊什么？\n(2->退出 /deep->解决难题 /local->快速提问):')
            if text_inquiry == '2':
                break

            if text_inquiry.lower().strip() == '/deep':
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

        if used_cloud and session_log:
            summary = call_cloud_with_fallback(
                session_log + [{'role': 'user', 'content': SUMMARY_PROMPT}],
                stream_print=False
            )
            if summary:
                save_chat_summary(summary)
                print(f'\n[本次对话已总结保存]\n{summary}\n'+ '-' * 20)
        continue

    else:
        new = p

    tts(new)
    new_c = correct_text(new)
    print(f'调整后： {new_c}')
    tts(new_c)

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
        elif ask_save == '2':
            break
        elif ask_save == '3':
            print(f'repeating: {new_c}')
            tts(new_c)
            continue
        elif ask_save == '4':
            thread, chat = ask_why_fixed_thread(new, new_c)
            rounds = 0
            saved = False
            last_saved_index = None
            while True:
                keep_asking = prompt("\n还有什么不解?\n(或1 -> 保存本次分析/ 2 -> skip): ").strip()
                if keep_asking == '2':
                    break
                elif keep_asking == '1':
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

