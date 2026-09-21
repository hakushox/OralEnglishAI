# SpeakNatural (OralEnglishAI)

面向中文母语者的英语口语练习工具。说/写一句英文 → 模型改成地道表达 → 朗读 → 存成学习档案，
积累之后可以复习自己的语法习惯。

界面文案、注释、commit message 一律用中文。

## 现在的状态

正在从终端程序迁移到本地浏览器程序。

- **终端版**（`edgetts.py` 等）是目前在用的版本，**迁移期间一个字都不改**。将来浏览器版跑通后整体废弃。
- **浏览器版**（`web/`）五个界面都能跑。其中 **练习页已接真实逻辑**：
  纠正走本地 ollama、解析走云端、语音是真 edge-tts（含词级时间戳）、
  存档写进用户真实档案。**单词 / 长难句 / 随便问 / 查词浮层 / 语音转写仍是 `MOCK`。**
- **练习页已改成递进式布局**：`data-stage` 四阶段（输入 → 改写 → 解析 → 追问），
  前一阶段缩小变暗退到顶部当上下文而不是消失；解析是主角，朗读收成行内小图标；
  追问在解析流完后才滑入；右上 ✕ 清空；录音条在非输入阶段收成麦克风圆钮。
- **练习页的交互模式**（其余模块应对齐）：下一步用「浮现式邀请」而不是按钮；
  保存统一用 `.bookmark` 书签图标，内容读完后滑入并脉动两下；多轮问答用 `.round`
  折叠线索，旧的收成一行可点开；每个输入框都套 `.field` 内嵌麦克风，
  录音只填进那个框、不切换页面状态。
- **档案页「分析我的语法习惯」已接真**（复用 `review.py:REVIEW_SYSTEM_PROMPT`，取最近 30 条 draft）。
- **保存分析时会先总结**：追问超过两轮就用 `review.py:SAVE_NOTE_SUMMARY_PROMPT`
  把整段讨论压成一条笔记，对齐终端版 `edgetts.py:944`。别只存最后一条回复。
- **练习页可就地翻看记录**（「看看最近存的几条」，对应终端版的 `/doc`），
  存完会把实际存进去的那段总结显示出来 —— 别让用户存了自己没读过的东西。
- **下一步**：把单词 / 长难句 / 随便问三个模块接真（逻辑在 `review.py` 里都现成，
  各自的"总结存档"也要一并接上），以及浏览器录音上传 + faster-whisper 转写。
- **已知不足**：`SAVE_NOTE_SUMMARY_PROMPT` 限制 80 字，多话题讨论会丢内容
  （比如语法点 + 词义辨析同时聊，总结可能只留后者）。要改得在 `web/prompts.py`
  里另写一份更长的总结 prompt，`review.py` 那个不能动。

## 怎么跑

```bash
venv/bin/python edgetts.py    # 终端版
venv/bin/python run_web.py    # 浏览器版，自动开 127.0.0.1:8765
```

**8765 是我（用户）的端口。** 你验证用的预览服务走 8766（`.claude/launch.json` 里配好了），
不要占用 8765，否则我跑 `run_web.py` 会撞上 "address already in use"。

没有测试、没有 lint。改完靠手动跑一遍验证。
打包命令见仓库里的 `notes` 文件（`SpeakNatural.spec` 是生成物，已 gitignore，别依赖它）。

## 协作方式

**先出方案，再动手。** 我在问问题或描述想法时，不要直接改代码——先说动哪几个文件、每处改什么、
有什么风险，等我说"可以/开始"。

- 「怎么…」「能不能…」「你觉得…」→ 只出方案
- 「改吧」「开始」「按这个来」「修一下」→ 可以动手
- 只读操作（看代码、跑起来验证、git log）→ 随时做，不用问

方案要短。有需要我拍板的分叉就直接问，别自己挑一个默默做了。

**每做完一块，回头更新上面的「现在的状态」节。** 那节是新会话唯一的进度来源 ——
哪些模块接真了、哪些还是 MOCK、下一步做什么，都写在那儿。不要另建 ROADMAP / PROGRESS
之类的文件：CLAUDE.md 每个会话自动读，别的文件不会，最后必然两份都半新半旧。

**我在学 vibe coding，该用工具时提醒我。** 某个环节用 plan mode / subagent / skill / hooks /
`/code-review` 会更合适时，先说一句「这里可以用 X」，解释它是什么、为什么合适，
再加一句「不用也行，区别是……」让我判断。不要默默用掉，也不要因为我没提就默默不用。

## 硬规则

**1. 不修改、不删除任何现有 .py 文件**

`edgetts.py`、`review.py`、`save_path.py`、`groq_tts.py`、`ollama_setup.py`、
`check_update.py`、`updater.py` —— 一行都不要动。浏览器版的代码全部放在 `web/` 里。
需要复用就 import，需要不同的函数签名就在 `web/` 里新写一份。

**2. 永远不要 `import edgetts`**

它顶层有阻塞性副作用：68 行 `ensure_ollama_ready()`、770 行加载 Whisper 模型、
779 行 `while True` 主循环。import 它等于启动整个终端程序。

`review.py` 和 `save_path.py` 可以安全 import——顶层只有常量和 client 构造。

**3. `API_KEY.py` 是密钥文件**

`GROQ_API_KEY` / `CEREBRAS_API_KEY` / `CLOUDFLARE_API_KEY` / `CLOUDFLARE_ACCOUNT_ID`。
已 gitignore 且从未进过 git 历史。不要 commit、不要打印、不要写进日志或报错信息。

**4. 用户数据在仓库外，改格式要考虑存量**

`SAVE_DIR` = macOS `~/Library/Application Support/OralEnglish`（Win 是 `%APPDATA%`，
Linux 是 `~/.config`）。里面是 `Oral_English_Exercise.json`（造句记录）、`chat_summaries.md`、
`parse_summaries.md`、`words_summaries.json`、`version.json`。

老用户手里有存量数据。改结构要参考 `save_path.py:migrate_clean_invalid_records()`
那种「一次性迁移 + flag 文件」的做法，别假设都是新格式。

**5. 不要 commit `venv/`、`dist/`、`build/`、`.DS_Store`**

## 代码地图

**终端版（只读）**

| 文件 | 职责 |
| --- | --- |
| `edgetts.py` | 主入口，模块级 `while True`。四个模式：改句 / `chat_mode` / `word_usage_mode` / `parse_sentence_mode`。TTS 播放、录音、键盘监听也在这 |
| `review.py` | 系统 prompt（大写常量）+ 云端多供应商轮询 + 本地 ollama 调用 + 复习/出题/批改 |
| `save_path.py` | 用户数据路径与读写，所有落盘的唯一出口 |
| `groq_tts.py` | Groq TTS 合成；`listen()` 用 faster-whisper 录音转文字 |
| `ollama_setup.py` | 确保本地 ollama 就绪，返回 `MODEL_NAME` |
| `check_update.py` / `updater.py` | 从 GitHub Release 自更新，只在打包后生效 |
| `cloud_models_availiability.py` | 额度 header 的调试脚本，主流程不依赖 |
| `NOTFORNOWgrop_stt.py`、`test.py` | 停用的实验代码，不要当参考 |

**浏览器版（在写）**

| 文件 | 职责 |
| --- | --- |
| `run_web.py` | 入口，起 uvicorn + 自动开浏览器 |
| `web/server.py` | FastAPI 路由。接口按 `MOCK` 标注分组，接真逻辑时替换函数体、保持接口形状不变 |
| `web/static/app.js` | 视图切换、流式消费、词级 LCS diff、录音波形、选词浮层 |
| `web/static/style.css` | 设计 token 全在顶部 `:root`，改配色只动那一块 |
| `web/static/index.html` | 单页，五个 `<section class="view">` |

## 写新代码的约定

**AI 调用必须「云端优先 + 本地兜底」。** 云端在 groq → cloudflare 之间轮询换模型，
全失败才回落到本地 ollama，本地也失败要给用户一句明确的失败提示，不能静默返回空。
不要直接裸调 `OpenAI` client。

终端版的实现是 `review.py:call_cloud_with_fallback()`（返回完整字符串）。
浏览器版要流式，**在 `web/` 里另写一份生成器版本**，不要去改老函数——它有 17 个调用点，
且中途失败重试的语义改成生成器后会出错（已 yield 的内容收不回来，会出现半句 A + 整句 B）。

**prompt 放哪**：`review.py` 里已有的直接 import 复用。新加的写进 `web/prompts.py`，
命名跟着现有的来（`XXX_SYSTEM_PROMPT`）。

**一次性任务的 prompt 拿去做多轮对话，一定要加追问约束。**
终端版的 prompt（`CORRECTION_SYSTEM_PROMPT` 等）都写死了输出结构，
多轮时每轮都生效，模型会把第一轮那套格式反复重跑而不是回答追问，
越往后越像上一轮的复制品。做法见 `web/prompts.py:FOLLOWUP_GUARD`：
约束只拼进**发给模型的那一份** messages，存进 thread 的仍是用户原话 ——
否则约束会污染后续上下文，"总结存档"也会把这段指令当成用户说的话。

注意 `CORRECTION_SYSTEM_PROMPT` 和 `CORRECT_SINGLE_SYSTEM_PROMPT` 写在 `edgetts.py`
（235、269 行），而 `edgetts.py` 不能 import —— 只能复制一份到 `web/prompts.py` 并注明来源行号。
这两处以后要手动同步，是不动老文件必须付的账。

**前后端接口**：流式接口返回 NDJSON，每行一个 JSON（`{"delta": "..."}`），
前端用 `fetch` + `ReadableStream` 逐行消费（见 `app.js:stream()`）。不是 SSE。

**改 HTML 删元素时，务必回头搜 `app.js` 里对应的 `$('#id')`。**
`app.js` 是顶层脚本，`$('#不存在的id').addEventListener(...)` 会抛错并让**整个脚本
从那一行起全部停止执行**，后面所有事件绑定都失效。而且函数声明会提升，
控制台里 `typeof someFn` 仍是 `'function'`，看起来一切正常，极难排查。
一条命令扫出所有悬空引用：

```bash
python3 -c "
import re;from pathlib import Path
js=Path('web/static/app.js').read_text();html=Path('web/static/index.html').read_text()
ids=set(re.findall(r'id=\"([^\"]+)\"',html))
used={m.group(1) for m in re.finditer(r'\\$\\$?\(\s*[\'\"]#([A-Za-z0-9_-]+)',js)}
print(sorted(used-ids))"
```

## git

直接提交到 `master`，暂时不走 PR ——当前所有改动都是纯新增，没有任何现有代码 import `web/`，
搞不坏终端版。等到真要动老代码时再说。

**按主题分开提交**，别一个 commit 塞所有东西。`git log` 要能看懂每次改了什么。
