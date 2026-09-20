# SpeakNatural (OralEnglishAI)

面向中文母语者的英语口语练习工具。说/写一句英文 → 模型改成地道表达 → 朗读 → 存成学习档案，
积累之后可以复习自己的语法习惯。

界面文案、注释、commit message 一律用中文。

## 现在的状态

正在从终端程序迁移到本地浏览器程序。

- **终端版**（`edgetts.py` 等）是目前在用的版本，**迁移期间一个字都不改**。将来浏览器版跑通后整体废弃。
- **浏览器版**（`web/`）骨架已完成：五个界面、导航、流式输出、词级 diff、录音波形、选词浮层都能跑，
  但**所有接口返回假数据**，标了 `MOCK`。
- **下一步**：新建 `web/engine.py`（生成器版的云端/本地调用）和 `web/store.py`（读真实档案），
  把 `web/server.py` 里的 MOCK 换掉。依然是纯新增。

## 怎么跑

```bash
venv/bin/python edgetts.py    # 终端版
venv/bin/python run_web.py    # 浏览器版，自动开 127.0.0.1:8765
```

没有测试、没有 lint。改完靠手动跑一遍验证。
打包命令见仓库里的 `notes` 文件（`SpeakNatural.spec` 是生成物，已 gitignore，别依赖它）。

## 协作方式

**先出方案，再动手。** 我在问问题或描述想法时，不要直接改代码——先说动哪几个文件、每处改什么、
有什么风险，等我说"可以/开始"。

- 「怎么…」「能不能…」「你觉得…」→ 只出方案
- 「改吧」「开始」「按这个来」「修一下」→ 可以动手
- 只读操作（看代码、跑起来验证、git log）→ 随时做，不用问

方案要短。有需要我拍板的分叉就直接问，别自己挑一个默默做了。

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

注意 `CORRECTION_SYSTEM_PROMPT` 和 `CORRECT_SINGLE_SYSTEM_PROMPT` 写在 `edgetts.py`
（235、269 行），而 `edgetts.py` 不能 import —— 只能复制一份到 `web/prompts.py` 并注明来源行号。
这两处以后要手动同步，是不动老文件必须付的账。

**前后端接口**：流式接口返回 NDJSON，每行一个 JSON（`{"delta": "..."}`），
前端用 `fetch` + `ReadableStream` 逐行消费（见 `app.js:stream()`）。不是 SSE。

## git

直接提交到 `master`，暂时不走 PR ——当前所有改动都是纯新增，没有任何现有代码 import `web/`，
搞不坏终端版。等到真要动老代码时再说。

**按主题分开提交**，别一个 commit 塞所有东西。`git log` 要能看懂每次改了什么。
