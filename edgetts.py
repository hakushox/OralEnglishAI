import edge_tts
import sounddevice as sd
import threading
from prompt_toolkit import prompt
import asyncio
import io
import soundfile as sf

import ollama
import time
import threading
import json
from pathlib import Path
from ollama_setup import ensure_ollama_ready
from save_path import SAVE_DIR, RECORDS
from check_update import check_and_update
import sys
import subprocess

if getattr(sys, 'frozen', False):
    exe_path = Path(sys.executable)
    try:
        updated = check_and_update(exe_path)
        if updated:
            print('更新完成，即将重启...')
            subprocess.Popen([str(exe_path)])
            sys.exit(0)
    except Exception as e:
        print(f'更新失败，原因{e}\n直接使用当前版本')

MODEL_NAME = ensure_ollama_ready()

def load_json():
    if RECORDS.exists():
        try:
            return json.loads(RECORDS.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            print('json解码错误')
            return []
    return []

texts_list = load_json() 

def write_json(draft, revised):
    texts = {
        'draft': draft, 'revised': revised,
    }
    texts_list.append(texts)
    RECORDS.write_text(json.dumps(texts_list, ensure_ascii=False, indent= 4), encoding='utf-8')    

async def _speak(text, rate='+1%', voice='en-US-AriaNeural'):
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    buffer = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk['type'] == 'audio':
            buffer.write(chunk['data'])
    buffer.seek(0)
    return buffer

def tts(text, rate='+1%'):
    # text = text.replace('*','~')
    def _run():
        sd.stop()
        buffer = asyncio.run(_speak(text, rate=rate))
        data, samplerate = sf.read(buffer)
        sd.play(data, samplerate)
        sd.wait()
    t1 = threading.Thread(target=_run, daemon=False)
    t1.start()
    t1.join()

async def list_voices():
    voices = await edge_tts.list_voices()
    for voice in voices:
        if voice['Locale'].startswith('en'):
            print(f"Name: {voice['Name']}, Gender: {voice['Gender']}")

chat_history = []

def correct_text(text=None, context=None, with_context=False, chat_mode=False):
    global chat_history
    if not chat_history and not chat_mode:
        chat_history.append({
            'role': 'system', 'content': '''你是一个地道的英文语法纠正器，你需要将语句转换为更为地道的口语             
             口语需要符合美剧的生活化，或者适合生活对话，要求非常美式的地道口语
             你将接收到改动前（draft）和改动后(revised)的两个句子，你来分析改动的原因！
             你的主要工作是针对改动前的句子来分析：
             改动前的句子可能有语法，拼写，句子结构，短语等等问题，你需要指出！
             如果语法没问题，也需要告知。
             必须精简化回答，不要说废话，篇幅尽量短。
             你的解释需要中文
             如果revised的句意脱离了draft,你也需要指出,但这部分只需超精简，因为这不是重点！'''
        })
    if chat_mode:
        chat_history.append({
            'role': 'system', 'content': '''你是一个地道美式的地道口语专家
            你可以对于任何关于英文使用的问题进行回答
             必须精简化回答，不要说废话，篇幅尽量短。
             你的解释需要中文
             '''
        })
        
    system_prompt = '''
             你是一个地道的英文语法纠正器，你需要将语句转换为更为地道的口语             
             口语需要符合美剧的生活化，或者适合生活对话，要求非常美式的地道口语
             如果已经语句很完美了，则不需要变化。
             除了最终语句，不要输出任何其他内容！'''
    
    if not with_context and not text and not chat_mode:
        return

    if with_context and context is None and not chat_mode:
        return
    
    now = time.time()
    # stop = False

    # def timer():
    #     while not stop:
    #         ellipsed = time.time() - now
    #         print(f'\r{ellipsed:.2f}...', end='', flush=True)
    #         time.sleep(0.1)
    
    # t = threading.Thread(target=timer)
    # t.start()


    if not with_context:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[
                {'role':'system', 'content': system_prompt},
                {'role': 'user', 'content': text}],
                options={'temperature': 0.2},think=False
            
        )
    else: 
        if context is not None:
            chat_history.append(
            {'role': 'user', 'content': context}
             )
            response = ollama.chat(
                model= MODEL_NAME,
                messages=[
                    *chat_history, #chat_history 是一个列表  应该用 *chat_history 展开
                ],
                stream=True,
                options={'temperature': 0.4},think=False
            )
            # stop = True
            # t.join()
            # print() 
            ellipsed = time.time() - now
            print(f'耗时{ellipsed:.2f}...')

            full_content=""
            for chunk in response:
                content = chunk['message']['content']
                full_content += content
                print(f'{content}', end='', flush=True)

            chat_history.append(
                {'role': 'assistant', 'content':full_content}
            )

            return full_content
        else:
            print('没有历史记录！')

    ellipsed = time.time() - now
    print(f'耗时{ellipsed:.2f}...'+'=' * 30 + f'当前模型:{response.model}' + '='* 30)
    # stop = True
    # t.join()

    return response.message.content.strip()

last_deque = texts_list
while True:
    p = prompt('输入英文(or type "chat")：')
    
    if p == '`' and len(last_deque) >= 1:
        new = last_deque[-1]
        print(f'repeating: {new}')
        tts(new)
        continue
    elif p == '``' and len(last_deque) >= 2:
        new = last_deque[-2]
        print(f'repeating: {new}')
        tts(new)
        continue
    elif p == 'chat':
        while True:
            text_inquiry = prompt('你想聊什么？(press 2 to skip):')
            if text_inquiry == '2':
                break
            correct_text(context=text_inquiry, with_context=True,chat_mode=True)
        continue
    else:
        new = p
        last_deque.append(new)

    tts(new)
    new_c = correct_text(new)
    print(f'调整后： {new_c}')
    tts(new_c)
    ask_save = prompt(f'是否保存？\n1->yes/ 2-> no/ 3-> play again / 4-> why fix it: ')

    if ask_save == '1':
        write_json(new, new_c)
        print(f'json已记录。总共{len(texts_list)}条')
    elif ask_save == '3':
        print(f'repeating: {new_c}')
        tts(new_c)
    elif ask_save == '4':
        chat = correct_text(context=json.dumps({'draft':new, 'revised': new_c}), with_context=True)
        print(chat)
        while True:
            keep_asking = prompt("是否需要追问?(type 2 to skip): ")
            if keep_asking == '2':
                break
            chat1 = correct_text(context=keep_asking, with_context=True)
            print(chat1)

    