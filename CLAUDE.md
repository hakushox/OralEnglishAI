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
- **录音的三个状态都要有明确反馈**：录音中（麦克风呼吸 + 波形 + 字幕行提示
  「再点一次麦克风 → 结束并开始转写」，不说清楚用户会以为说完就完了）、
  转写中（麦克风转圈 + 字幕行标签变「转写中」带转圈，本地 whisper 要几秒）、
  完成（字幕行消失）。只把按钮文字换成「⋯」太弱。
- **改写完成后自动朗读地道版一次** —— 这是练口语的，"听到正确的说法"比看到更重要。
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

**「出题练一练」已接真**：`QUESTION_GEN` 出题 → `GRADE_ANSWER` 逐题批改
→ `PRACTICE_CONCLUSION` 打熟练度分并写回生词本。几个要点：

- **状态全在后端**（第几题、错几次、完整记录），模型只负责出题和判单题 ——
  跟终端版 `run_practice_session()` 同一个思路，不依赖模型记住上下文。
- **`answer_hint` 绝不发给前端。** 终端版没这个问题（答案在同一进程里），
  浏览器版发过去的话，用户在开发者工具就能看到答案。判题必须留在后端。
- `correct` / `close` 都算过；`wrong` 允许重试，错满 3 次才给答案要点并放行。
- 批改抽风时返回 `retry` 让用户重答，不判死也不卡住流程。
- 熟练度写回用 `store.set_proficiency()` 而不是 `save_path.update_word_proficiency`
  —— 后者按 `word` 精确匹配（大小写敏感），跟别处不分大小写的匹配不一致，
  大小写不同时会静默写不进去。
- 判越界要看 `i < len(questions)` 而不是只看 `questions` 非空 ——
  答完最后一题后 `questions` 还在但 `i` 已越界，直接取会 IndexError 返回空响应。

**还是假的**

1. **选词浮层** —— 划词弹出的小卡片，释义来自 `/api/lookup/{word}`，那是个占位实现。
   打算用本地 ollama 快速出一句。

**打包已经跑通（浏览器版）**

```bash
./build_web.sh          # 出 dist/SpeakNatural/
./build_web.sh --app    # 顺便写进 SpeakNaturalLauncher.app（只有 macOS 有意义）
```

**打包参数的唯一事实来源是 `build_web.py`**，别在别处再抄一份：`build_web.sh` 只是
拿 venv 的 python 去调它，CI 也是调它。写成 .py 是因为 Windows 跑不了 shell 脚本，
而那串 `--collect-all` 抄成两份迟早对不上。

入口换成了 `run_web.py`。macOS 上打包会顺带生成 **`dist/SpeakNatural.app`** ——
用户要的是能双击的东西，不是一个文件夹，CI 打的 mac 包也是它。

**两个 .app 壳，别搞混**：`dist/SpeakNatural.app` 是 `build_web.py:make_bundle()`
现生成的（Info.plist + 一个 `open -a Terminal` 的启动脚本），CI 和本机出的包因此一致；
仓库根目录那个 `SpeakNaturalLauncher.app` 是你手工 osacompile 的 AppleScript applet，
被 `*.app` gitignore 挡着进不了 CI，现在只有 `--app` 参数会往里写，留着备用。

启动脚本**不能直接 exec 真程序** —— 那样没有控制台，模型下载进度、端口提示、
崩溃堆栈全看不见，用户只会看到「点了没反应」。打包后实测通过：
首页 / 静态文件 / 档案与生词本读盘 / edge-tts 合成 / whisper 转写（av 解码 +
onnxruntime VAD）/ 本地 ollama 纠正 / 云端 groq 追问。

之前预见的几个坑，各自是这么处理的：

| 坑 | 处理 |
| --- | --- |
| 静态文件路径 | 新增 `web/bundle.py:resource()`，frozen 时走 `sys._MEIPASS`；`web/static` 由 `--add-data` 打进包。以后再有随包文件也走它，别写 `Path(__file__).parent` |
| whisper 模型 | **不随包**（随包要 1.8G，zip 逼近 GitHub Release 的 2G 上限）。`stt.py` 把状态拆成 下载中 / 加载中 / 失败，`/api/env` 带百分比（按 HF 缓存 blobs 的字节数算），前端顶部 `#sysbar` 显示进度条 |
| ollama | `/api/env` 返回 `local_model`，没装时 `#sysbar` 提示「改写会走云端（需要联网）」，可以点 × 关掉 |
| 端口占用 | `run_web.py:pick_port()` 从 8765 起往后顺延 20 个，全占用就让系统随便给一个；`SPEAKNATURAL_PORT` 可以改起点 |
| 入口 | 必须 `from web.server import app` 真 import 再传给 uvicorn —— 字符串形式 `'web.server:app'` pyinstaller 静态分析看不见，打出来的包一启动就 ModuleNotFoundError |
| 依赖收集 | 见 `build_web.sh` 里的 `--collect-all` 清单（faster_whisper / ctranslate2 / onnxruntime / huggingface_hub / uvicorn / fastapi / edge_tts / ollama）和上面的注释 |

**CI 出包**（`.github/workflows/build.yml`）

手动触发、推到 master、或推 `v` 开头的 tag（最后一种顺便建 Release）。矩阵是
macOS-AppleSilicon + Windows-x64 两个平台，各出一个 zip。**已经跑通**：
mac 75M / 1分14秒，Windows 104M / 1分57秒。

（push 到 master 也触发是调试期临时开的，稳定后把 workflow 里 `branches: [master]`
那两行删掉，省得每次 push 都空跑。）

几个要点：

- **所有涉及 Windows 的地方都要当心编码**。Windows 的 Python 默认按系统代码页
  读写文件和输出，这个项目从注释到提示全是中文 —— 第一次 CI 就是挂在
  `print('已生成…')` 上。workflow 里全局开了 `PYTHONUTF8`，而**打包后的 exe
  读不到环境变量**，所以 `run_web.py` 进程自己把 stdout/stderr 重配成 UTF-8。

- **`API_KEY.py` 没进 git，但 `review.py` 顶层 import 它**，所以 CI 要现造一个。
  默认写占位串 —— 发出去的包里没有真 key。占位串**不能是空字符串**，
  OpenAI 客户端见到空 key 会在构造时直接抛异常，包就起不来了。
- mac 的 zip 用 `ditto -c -k --keepParent`，不用 `zip` —— 后者丢符号链接和可执行位，
  用户解压出来点不开。
- `requirements-web.txt` 现在是**完整**的运行时依赖清单（CI 只装这一份），
  加了新的第三方 import 记得同步进去。

**打包相关还没解决的：**

- **`API_KEY.py` 会被编进包里**（`review.py` 顶层 import 它）。终端版一直如此，
  但分发出去等于把 groq / cerebras / cloudflare 的 key 一起给了拿到包的人。
  真要公开发布，得改成让用户自己填 key 或走自己的中转，那时候要碰 `review.py`。
- 没做代码签名和公证，别人下载后首次打开得右键→打开。
- 首次录音要联网下模型；离线用户其它功能都能用，只有录音不行（界面已说明）。
- **Intel Mac 做不了**，不是偷懒：`faster-whisper` 硬依赖 `onnxruntime>=1.14`，
  而 onnxruntime 最后一个 macOS x86_64 轮子是 2021 年的 1.9.0。要支持 Intel Mac
  只能放弃本地语音识别，或者自己编译 onnxruntime。
- Windows 只在 CI 上构建过，没在真 Windows 机器上跑过。

## 怎么跑

```bash
venv/bin/python edgetts.py    # 终端版
venv/bin/python run_web.py    # 浏览器版，自动开 127.0.0.1:8765
./build_web.sh                # 打包浏览器版，加 --app 写进 .app
```

**8765 是我（用户）的端口。** 你验证用的预览服务走 8766（`.claude/launch.json` 里配好了），
不要占用 8765，否则我跑 `run_web.py` 会撞上 "address already in use"。
要验证打包产物就 `SPEAKNATURAL_PORT=8790 ./dist/SpeakNatural/SpeakNatural`，
再带上 `BROWSER=true` 免得它往我屏幕上弹标签页。

**改完代码我这边要做什么，不一样，容易搞混：**

| 改了什么 | 我要做什么 |
| --- | --- |
| `web/static/*`（前端） | 刷新页面即可（静态文件已设 `no-store`，不会拿到缓存的旧版） |
| `web/*.py`（后端） | **必须 Ctrl+C 重启** `run_web.py`，它没开热重载 |

告诉我改了哪边，别让我自己猜 —— "界面是新的、行为是旧的"这种组合最难排查。

**按钮都要有 `data-tip` 悬停说明。** 新用户看不懂"总结""追问"这些按钮到底做什么。
提示走事件委托（`app.js` 里的 `mouseover` 监听），所以卡片、折叠线索这些
动态插入的按钮也会自动生效，不用额外绑定。

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

**列表要做成卡片轮播时，套 `app.js:mountCoverflow()`，不要重写。**
生词本和练习记录都用它。卡片绝对定位，按「离中心的距离」算 scale / opacity / zIndex，
中间锐利、两侧缩小压后并往边缘溢出（`scroll-snap` 做不到这种重叠 ——
吸附要求卡片占住布局宽度）。调用方只提供 `tile(item)` 返回卡片 HTML 和
`onAction(act, item, slide, btn)` 处理 `[data-act]` 按钮。

几个容易漏的点：容器高度要跟着当前卡片走，提拉展开详情后重新量（`fitHeight()`，
`max-height` 过渡期间要量两次）；键盘方向键由一个全局监听 + `activeDeck` 指针统一处理，
关闭轮播时**必须把 `activeDeck` 置空**，否则两个轮播会互相抢键。

**卡片正面必须用 `plainText()` 剥掉 markdown 标记。** 笔记正文都是 markdown，
直接 `esc()` 会把 `**` `#` 原样露给用户；渲染成 HTML 又不适合只放一两行的正面。
标题用 `noteTitle()`（跳过「【原句】」这类纯格式标记行），摘要用 `noteGloss()`
（跳过已经当标题用掉的那句，否则同一句话在卡片上出现两遍）。

**折叠线索的标题要带序号**（`.round-num`）—— 收起之后能一眼看出聊到第几轮。

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
