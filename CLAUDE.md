# SpeakNatural (OralEnglishAI)

面向中文母语者的英语口语练习工具。说/写一句英文 → 模型改成地道表达 → 朗读 → 存成学习档案，
积累之后可以复习自己的语法习惯。

界面文案、注释、commit message 一律用中文。

## 现在的状态

浏览器版四个模块都已接真实逻辑，进入迭代阶段。终端版（`edgetts.py` 等）仍在，
**迁移期间一个字都不改**；等浏览器版补齐下面三个洞、并且打包跑通之后再谈废弃。

**已经是真的**

| 模块 | 内容 |
| --- | --- |
| 练习 | 纠正（本地优先）、为什么这么改 + 多轮追问（云端优先）、总结存档、真 TTS（含词级时间戳跟读）、就地看最近记录 |
| 单词 | 查词解析、追问、总结存生词本、星级、生词本 coverflow + 提拉展开 + 删除撤销 |
| 长难句 | 结构分析、追问、`SUMMARY_PARSE` 存复习笔记、跨笔记找共性困难 |
| 随便问 | 快速档=本地 / 深度档=云端（真的换模型和 prompt）、总结存档 |
| 档案 | 四类记录合并展示、展开全文、左滑删除带撤销、分析语法习惯 |

**语音转写已接真**（`web/stt.py`）：浏览器 `MediaRecorder` 录音 → multipart 上传
→ faster-whisper `large-v3-turbo`。几个要点：

- 模型**懒加载 + 常驻内存**，服务启动时后台线程预热。不能放模块顶层
  （CPU 上加载十几秒，会把启动拖死），也不能每次请求重载。
- **语言按输入框传**（`data-lang`）：造句/句子/查词框传 `en`，各处追问框和随便问传 `zh`。
  实测 whisper 其实会无视错误的语言强制（英文音频传 `zh` 照样输出英文），
  所以终端版写死 `language='zh'` 不算坏；但短句和单个词时按框分更稳。
- 录音格式让浏览器自己挑（Chrome 走 webm+opus，Safari 只有 mp4），
  见 `app.js:pickMime()`。停录时**必须先停 recorder 拿到数据再关音频流**，
  顺序反了会丢最后一段。
- 转写失败不要把原始异常和临时文件路径吐给用户，说人话，细节留服务端日志。
- **录音是追加不是替换**（`app.js:joinSpeech()`）：开录前先记住输入框已有内容，
  实时字幕和最终结果都接在它后面。一句没说完可以再录一次补，也能先打字再补说。
- **实时字幕用浏览器自带的 `SpeechRecognition`**，不用 whisper 做实时 ——
  实测 large-v3-turbo 在 CPU 上转写 7 秒音频要 4 秒，每秒重转整个缓冲区跟不上
  （终端版 `listen()` 就是这么做的，所以卡）。浏览器那个瞬时、零 CPU，
  代价是音频经 Google 服务器（用户已知情同意）。定稿仍用本地 whisper，更准且保留语法错误。
- **实时字幕必须显示在输入框外面**（`.live-cap` 独立一行，标着「实时·粗略」）。
  浏览器自带识别只能设一种语言，中英混着说必然出错；把不准的文字直接填进输入框，
  用户会误当成结果。输入框只放 whisper 的定稿。
- whisper 失败但实时字幕有内容时，保留字幕结果而不是清空 —— 别让用户白说一遍。

**还是假的（按重要性排）**

1. **出题练一练** —— 三个 prompt（`QUESTION_GEN` / `GRADE_ANSWER` /
   `PRACTICE_CONCLUSION`）和 `save_path.update_word_proficiency` 都现成，没接。
   接上之后生词本卡片上那些「未测」才会变成真实熟练度。
2. **选词浮层** —— `/api/lookup/{word}` 是占位释义。打算用本地 ollama 快速出一句。

**不在功能清单里但必须做的：打包。**
pyinstaller 入口还指着 `edgetts.py`，`web/static/` 也没作为数据文件塞进去，
`SpeakNaturalLauncher.app` 还是启动终端版。这是"能分发的程序"这个原始目标的最后一环。

## 怎么跑

```bash
venv/bin/python edgetts.py    # 终端版
venv/bin/python run_web.py    # 浏览器版，自动开 127.0.0.1:8765
```

**8765 是我（用户）的端口。** 你验证用的预览服务走 8766（`.claude/launch.json` 里配好了），
不要占用 8765，否则我跑 `run_web.py` 会撞上 "address already in use"。

**改完代码我这边要做什么，不一样，容易搞混：**

| 改了什么 | 我要做什么 |
| --- | --- |
| `web/static/*`（前端） | 刷新页面即可（静态文件已设 `no-store`，不会拿到缓存的旧版） |
| `web/*.py`（后端） | **必须 Ctrl+C 重启** `run_web.py`，它没开热重载 |

告诉我改了哪边，别让我自己猜 —— "界面是新的、行为是旧的"这种组合最难排查。

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

## 页面层级规范（所有模块统一，新模块直接套）

**主区 = 输入 + 当前结果**，最大最亮，占视觉中心：

- `.hero` 包住输入区，`.hero-label` 是上方的小标签（「查一个词」这种）
- `.hero .field input` 高 54px、字号 17px；`.hero-btn` 是加大的主按钮

**次级板块 = 生词本 / 档案这类附属功能**，放主区下方，视觉上退后一层：

- `.section` 底色用 `--sunken`（`#121215`，比页面底色 `#16161a` 更暗）
- `.section-head` 是真正的板块标题（`.section-title` + `.section-count` + 折叠箭头），
  不要用小号灰字的链接充当标题
- `.section-body` 有横向裁切，里面的轮播侧卡会「从板块边缘探出来」而不是溢出
- 板块里的卡片要用更亮的面（`--surface`）才浮得起来

**手势**：不要用拖拽翻页 —— 拖一点点就劫持了点击，卡片点不开，
触控鼠标尤其难用。用横向滚轮（`wheel` 的 `deltaX`），
触控板双指横滑和 Magic Mouse 横扫都是原生手势，且跟点击零冲突。

**不要试图划分「一次手势」** —— wheel 事件流里没有可靠的手势边界。两种错法都踩过：

- 固定冷却（260ms）：惯性尾巴在冷却后又攒够阈值，一次手势飞过好几张
- 靠事件间隔判断手势结束（140ms 无新事件才解锁）：触控板和 Magic Mouse
  松手后会**持续发惯性事件**，那个间隔根本等不到，锁一直不放，
  必须把鼠标移出容器才能再滑

**正确做法：像原生滚动那样按位移连续响应**，惯性自然成为滚动的一部分。
把累积的 `deltaX` 换算成小数位置实时摆位，输入停 90ms 后吸附到最近一张。
每张的像素门槛需要实测标定（当前 220px，见 `PX_PER_CARD` 处的注释）；
单个事件的贡献要设上限，某些设备会偶发几百 px 的巨大 delta。

**按钮点完要 `blur()`**：留着焦点的话，用户之后按方向键时 Chrome 会给那个
焦点元素画上 focus-visible 框，看起来像"某个标题被莫名选中了"。
另外给标题和导航条加 `user-select: none`，连点时不会选中文字。

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
