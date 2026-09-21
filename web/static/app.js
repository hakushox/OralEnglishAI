'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ========== 流式读取：后端按行返回 JSON ========== */
async function stream(url, body, onChunk) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (line.trim()) onChunk(JSON.parse(line));
    }
  }
}

/* ========== 词级 diff（LCS） ========== */
const norm = (s) => s.toLowerCase().replace(/[^a-z0-9']/g, '');

function diffWords(a, b) {
  const A = a.split(/\s+/).filter(Boolean);
  const B = b.split(/\s+/).filter(Boolean);
  const m = A.length, n = B.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = norm(A[i]) === norm(B[j])
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (norm(A[i]) === norm(B[j])) { out.push({ t: 'eq', a: A[i], b: B[j] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: 'del', a: A[i] }); i++; }
    else { out.push({ t: 'ins', b: B[j] }); j++; }
  }
  while (i < m) out.push({ t: 'del', a: A[i++] });
  while (j < n) out.push({ t: 'ins', b: B[j++] });
  return out;
}

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

/* ========== 极简 markdown 渲染 ==========
   模型回答里只会出现标题、加粗、行内代码、无序列表这几种，
   够用就行，不值得为此引一个 CDN 依赖（这是本地程序，应当断网也能开界面）。
   嵌套列表会被拍平成一层，可以接受。 */
function mdToHtml(src) {
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')          // 必须先于斜体，否则 ** 会被拆成两个斜体
    .replace(/\*([^*\n]+)\*/g, '<i>$1</i>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/&lt;br\s*\/?&gt;/g, '<br>');           // 模型偶尔混着吐原生 <br>，只放行这一个标签

  // 表格：模型做 A/B 对比时几乎必用，而"两个词有什么区别"正是这个 app 的高频问题
  const table = (lines) => {
    const rows = lines.map((l) => l.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
    const body = rows.filter((r) => !r.every((c) => /^:?-{2,}:?$/.test(c)));
    if (!body.length) return '';
    const [head, ...rest] = body;
    return '<table><thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') +
      '</tr></thead><tbody>' +
      rest.map((r) => '<tr>' + r.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') +
      '</tbody></table>';
  };

  let html = '', inList = false, buf = [];
  const flushList = () => { if (inList) { html += '</ul>'; inList = false; } };
  const flushTable = () => { if (buf.length) { html += table(buf); buf = []; } };

  for (const raw of esc(src).split('\n')) {
    const line = raw.trim();

    if (line.startsWith('|') && line.length > 1) { flushList(); buf.push(line); continue; }
    flushTable();

    const li = line.match(/^[*\-+]\s+(.*)$/);
    if (li) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inline(li[1])}</li>`;
      continue;
    }
    flushList();
    if (!line) continue;

    const h = line.match(/^#{1,4}\s+(.*)$/);
    const q = line.match(/^&gt;\s*(.*)$/);           // esc() 已经把 > 转成了 &gt;
    // 模型爱用「1. **小节名**：正文」或整行加粗当小节标题
    // （WORD_PARSE_SYSTEM_PROMPT 和纠错分析都是这个格式），单独排版才不糊成一团
    const numSec = line.match(/^(\d+)[.、]\s*\*\*(.+?)\*\*[:：]?\s*(.*)$/);
    const boldSec = line.match(/^\*\*(.+?)\*\*[:：]?$/);
    if (h) html += `<div class="md-h">${inline(h[1])}</div>`;
    else if (numSec) {
      html += `<div class="md-sec"><i class="md-num">${numSec[1]}</i>${inline(numSec[2])}</div>`;
      if (numSec[3]) html += `<p>${inline(numSec[3])}</p>`;
    } else if (boldSec) html += `<div class="md-sec">${inline(boldSec[1])}</div>`;
    else if (q) html += `<blockquote>${inline(q[1])}</blockquote>`;
    else html += `<p>${inline(line)}</p>`;
  }
  flushList(); flushTable();
  return html;
}

const wrapWords = (words) =>
  words.map((w) => `<span class="w">${esc(w)}</span>`).join(' ');

function renderDiff(draft, revised) {
  // 把连续的同类改动并成一段，避免每个词单独套一个色块，视觉上太碎
  const groups = [];
  for (const p of diffWords(draft, revised)) {
    const word = p.t === 'del' ? p.a : p.b;
    const last = groups[groups.length - 1];
    if (last && last.t === p.t) last.words.push(word);
    else groups.push({ t: p.t, words: [word] });
  }

  let dh = '', rh = '', k = 0;
  for (const g of groups) {
    const delay = `animation-delay:${k++ * 70}ms`;
    if (g.t === 'eq') {
      dh += wrapWords(g.words) + ' ';
      rh += `<span class="grp" style="${delay}">${wrapWords(g.words)}</span> `;
    } else if (g.t === 'del') {
      dh += `<span class="del" style="${delay}">${wrapWords(g.words)}</span> `;
    } else {
      rh += `<span class="grp ins" style="${delay}">${wrapWords(g.words)}</span> `;
    }
  }
  $('#p-draft').innerHTML = dh;
  $('#p-revised').innerHTML = rh;
}

/* ========== 语音播放 + 跟读高亮 ========== */
let litTimers = [];
let curAudio = null;
const ttsCache = new Map();   // 同一句重复播不重新合成

function clearLit(el) {
  litTimers.forEach(clearTimeout);
  litTimers = [];
  $$('.w', el).forEach((w) => w.classList.remove('lit'));
}

async function speak(el, text, btn) {
  if (!text || !text.trim()) return;
  if (curAudio) { curAudio.pause(); curAudio = null; }
  clearLit(el);

  let data = ttsCache.get(text);
  if (!data) {
    const label = btn.textContent;
    btn.textContent = '合成中…';
    btn.disabled = true;
    try {
      data = await (await fetch('/api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })).json();
    } finally {
      btn.textContent = label;
      btn.disabled = false;
    }
    if (!data.ok) { msg(data.msg || '语音合成失败'); return; }
    ttsCache.set(text, data);
  }

  const audio = new Audio('data:audio/mpeg;base64,' + data.audio);
  curAudio = audio;

  // 用 edge-tts 的 WordBoundary 时间戳对齐高亮，不再是假定时器
  const words = $$('.w', el);
  const n = Math.min(words.length, data.marks.length);
  for (let i = 0; i < n; i++) {
    litTimers.push(setTimeout(() => {
      words.forEach((x) => x.classList.remove('lit'));
      words[i].classList.add('lit');
    }, data.marks[i].offset_ms));
  }
  audio.addEventListener('ended', () => clearLit(el));
  audio.play().catch(() => msg('播放被浏览器拦截了，点一下页面再试'));
}

function msg(text) {
  const box = $('#p-msg');
  if (!box) return;
  box.textContent = text;
  if (text) setTimeout(() => { if (box.textContent === text) box.textContent = ''; }, 4000);
}

/* ========== 导航 ========== */
$$('.nav button').forEach((b) => {
  b.addEventListener('click', () => {
    $$('.nav button').forEach((x) => x.classList.remove('on'));
    $$('.view').forEach((v) => v.classList.remove('on'));
    b.classList.add('on');
    $('#v-' + b.dataset.view).classList.add('on');
    closePop();
    if (b.dataset.view === 'archive') loadArchive('all');
    if (b.dataset.view === 'word') refreshWordCount();   // 只更新计数，不自动打开某个词
    if (b.dataset.view === 'parse') refreshParseCount();
    if (b.dataset.view === 'chat') refreshChatCount();
  });
});

/* ==================== 练习 ==================== */
let state = { draft: '', revised: '' };

/* 递进式阶段：① 输入 → ② 改写 → ③ 解析 → ④ 追问
   显隐和尺寸全由 CSS 的 [data-stage] 规则管，这里只负责改这一个属性。 */
function setStage(n) {
  const stage = $('#p-stage');
  if (stage.dataset.stage === String(n)) return;
  stage.dataset.stage = String(n);
  // 重新触发滑入动画：光改 data-stage 不会让已经播过的 animation 再跑一次
  $$('.slide-up', stage).forEach((el) => {
    el.style.animation = 'none';
    void el.offsetWidth;
    el.style.animation = '';
  });
}

function resetStage() {
  if (curAudio) { curAudio.pause(); curAudio = null; }
  state = { draft: '', revised: '' };
  $('#p-input').value = '';
  $('#p-draft').innerHTML = '';
  $('#p-revised').innerHTML = '';
  $('#p-thread').innerHTML = '';
  $('#p-src').textContent = '';
  msg('');
  $('#p-save').textContent = '存进档案';
  $('#p-save').disabled = false;
  $('#p-save-note').textContent = '总结这段讨论，存进记录';
  $('#p-save-note').disabled = false;
  $('#p-saved').innerHTML = '';
  $('#p-deck').innerHTML = '';
  $('#p-pager').hidden = true;
  $('#p-foot').hidden = true;
  $('#p-section').classList.remove('open');
  setStage(1);
  $('#p-input').focus();
}


async function correct() {
  const text = $('#p-input').value.trim();
  if (!text) return;
  state.draft = text;
  state.revised = '';
  $('#p-input').value = '';
  setStage(2);
  // 换了新句子，上一句的解析线索和存档状态都得清掉 ——
  // 不清的话前一句的追问会挂在新句子下面（走「换一句继续练」时 resetStage 会清，
  // 但直接在 ① 里改一句再提交不经过那条路）
  $('#p-thread').innerHTML = '';
  $('#p-saved').innerHTML = '';
  $('#p-deck').innerHTML = '';
  $('#p-pager').hidden = true;
  $('#p-foot').hidden = true;
  $('#p-section').classList.remove('open');
  $('#p-draft').textContent = text;
  const rev = $('#p-revised');
  rev.textContent = '';
  rev.classList.add('caret');

  msg('');
  $('#p-save').textContent = '存进档案';
  $('#p-save').disabled = false;
  $('#p-save-note').textContent = '总结这段讨论，存进记录';
  $('#p-save-note').disabled = false;

  await stream('/api/practice/correct', { text }, (m) => {
    if (m.delta) { state.revised += m.delta; rev.textContent = state.revised; }
    if (m.source) $('#p-src').textContent = m.source;
    if (m.warn || m.error) msg(m.warn || m.error);
  });
  rev.classList.remove('caret');
  if (state.revised.trim()) {
    renderDiff(state.draft, state.revised);
    // 改完自动读一遍地道版 —— 这是练口语的，"听到正确的说法"才是重点
    speak($('#p-revised'), state.revised, $('#p-play-rev'));
  }
}

$('#p-go').addEventListener('click', correct);
$('#p-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) correct();
});
$('#p-play-draft').addEventListener('click', (e) => speak($('#p-draft'), state.draft, e.target));
$('#p-play-rev').addEventListener('click', (e) => speak($('#p-revised'), state.revised, e.target));

$('#p-save').addEventListener('click', async (e) => {
  const r = await (await fetch('/api/practice/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft: state.draft, revised: state.revised }),
  })).json();
  if (r.ok) {
    e.target.textContent = `✓ 已存档 · 共 ${r.total} 条`;
    e.target.disabled = true;
    $('#arc-count').textContent = r.total;
  } else {
    msg(r.msg || '存档失败');
  }
});

/* ========== 解析线索：每轮一条，旧的折叠成一行 ==========
   之前是一张卡片被反复清空重写，追问会把上一轮的分析擦掉。
   现在每轮独立成 .round，点标题头展开/收起，随时能翻回去看。 */
function addRound(title, threadSel = '#p-thread') {
  const thread = $(threadSel);
  $$('.round', thread).forEach((r) => r.classList.remove('open'));   // 新的一轮进来，旧的收起

  const el = document.createElement('div');
  el.className = 'round open';
  el.innerHTML = `
    <button class="round-head"><span>${esc(title)}</span><span class="chev">⌄</span></button>
    <div class="round-body"><div class="card md"></div></div>`;
  thread.appendChild(el);

  $('.round-head', el).addEventListener('click', () => {
    const wasOpen = el.classList.contains('open');
    $$('.round', thread).forEach((r) => r.classList.remove('open'));
    if (!wasOpen) el.classList.add('open');
  });
  return el;
}

async function askWhy(url, body, title) {
  const round = addRound(title);
  const md = $('.md', round);
  let raw = '';
  md.classList.add('caret');
  // 流式阶段先按纯文本追加 —— markdown 语法跨行，边收边渲染会一直闪烂格式
  await stream(url, body, (m) => {
    if (m.delta) { raw += m.delta; md.textContent = raw; }
    if (m.warn || m.error) msg(m.warn || m.error);
  });
  md.classList.remove('caret');
  if (raw.trim()) md.innerHTML = mdToHtml(raw);

  setStage(4);                           // 读完了，追问框和保存按钮才一起滑进来
}

$('#p-save-note').addEventListener('click', async (e) => {
  const btn = e.target;
  const label = btn.textContent;
  btn.textContent = '正在总结…';
  btn.disabled = true;
  const r = await (await fetch('/api/practice/save-note', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ revised: state.revised, draft: state.draft }),
  })).json();
  if (r.ok) {
    btn.textContent = r.summarized ? '✓ 已总结并存进记录' : '✓ 已存进记录';
    // 把实际存进去的那段话显示出来 —— 后端本来就返回了，之前前端丢掉了，
    // 等于让用户存了一段自己没读过的东西进档案
    $('#p-saved').innerHTML =
      `<div class="card slide-up" style="margin-top:12px">
         <div class="label acc">${r.summarized ? '存进记录的总结' : '存进记录的内容'}</div>
         <div class="md"></div>
       </div>`;
    $('#p-saved .md').innerHTML = mdToHtml(r.note || '');
    $('#p-deck').innerHTML = '';               // 记录变了，下次展开重新取
    $('#p-pager').hidden = true;
    $('#p-foot').hidden = true;
    $('#p-section').classList.remove('open');
  } else {
    btn.textContent = label;
    btn.disabled = false;
    msg(r.msg || '保存失败');
  }
});

$('#p-why').addEventListener('click', () => {
  setStage(3);
  askWhy('/api/practice/why', { draft: state.draft, revised: state.revised }, '为什么这么改');
});

$('#p-again').addEventListener('click', resetStage);

/* 就地翻看最近记录，对应终端版练习循环里的 /doc（它也是只打印最近 3 条）。
   复用档案页的接口和卡片样式，不用动后端。 */
$('#p-recent').addEventListener('click', (e) => {
  e.currentTarget.blur();                    // 留着焦点的话按方向键会给它画焦点框
  const sec = $('#p-section');
  if (sec.classList.contains('open')) {      // 再点一次收起
    sec.classList.remove('open');
    $('#p-deck').innerHTML = '';
    $('#p-pager').hidden = true;
    $('#p-foot').hidden = true;
    activeDeck = null;
    return;
  }
  sec.classList.add('open');
  loadPracticeBook();
});

/* 输入框统一走这个：键盘和按钮两条路都要有，不能只留快捷键。
   单行 input 用回车提交；textarea 里回车是换行，改用 ⌘/Ctrl + 回车。 */
function bindSend(inputSel, buttonSel, handler) {
  const input = $(inputSel);
  const multiline = input.tagName === 'TEXTAREA';
  const fire = () => {
    const value = input.value.trim();
    if (!value) return;
    input.value = '';
    handler(value);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    if (multiline && !(e.metaKey || e.ctrlKey)) return;
    e.preventDefault();
    fire();
  });
  $(buttonSel).addEventListener('click', fire);
}

bindSend('#p-why-input', '#p-why-send',
  (question) => askWhy('/api/practice/why/followup', { question }, question));

/* ========== 录音 + 转写：每个输入框各管各的 ==========
   录到的文字只填进自己那个框，不切换页面状态 ——
   说话是一种输入方式，不该等于"开始新对话"。
   语言按框的性质走（data-lang）：造句/句子/查词框说英文，追问框和随便问说中文。 */
const BARS = 14;        // 波形缩成麦克风旁边一小条，条数也跟着减

/* 浏览器自带的实时识别，只用来做录音过程中的字幕预览。
   为什么不用 whisper 做实时：实测 large-v3-turbo 在 CPU 上转写 7 秒音频要 4 秒，
   每秒重转一遍整个缓冲区根本跟不上（终端版 listen() 就是这么做的，所以很卡）。
   浏览器这个是瞬时的、零 CPU，代价是音频要经 Google 的服务器。
   最终定稿仍然用本地 whisper —— 它更准，而且保留语法错误（练习需要）。 */
function startLiveCaption(lang, onText) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  try {
    const sr = new SR();
    sr.lang = lang === 'zh' ? 'zh-CN' : lang === 'en' ? 'en-US' : navigator.language;
    sr.continuous = true;
    sr.interimResults = true;
    let settled = '';
    sr.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) settled += r[0].transcript;
        else interim += r[0].transcript;
      }
      onText((settled + interim).trim());
    };
    sr.onerror = () => {};            // no-speech / aborted 之类不用管，波形还在
    sr.start();
    return sr;
  } catch (err) {
    return null;
  }
}

// 浏览器支持的录音格式不一样：Chrome/Edge 走 webm+opus，Safari 只有 mp4。
// 传空字符串让浏览器自己挑，比硬写一个不支持的格式安全。
function pickMime() {
  const want = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
  return want.find((t) => MediaRecorder.isTypeSupported(t)) || '';
}

// 录音是**追加**而不是替换：一句没说完可以再录一次补上，
// 也可以先打几个字再补说。空格接缝处理掉重复空白。
const joinSpeech = (a, b) => {
  a = (a || '').replace(/\s+$/, '');
  b = (b || '').replace(/^\s+/, '');
  if (!a) return b;
  if (!b) return a;
  return a + ' ' + b;
};

function setupMic(btn) {
  const field = btn.closest('.field');
  const target = $(btn.dataset.mic);
  const lang = btn.dataset.lang || 'auto';

  // 实时字幕单独一行，不写进输入框。浏览器自带识别只能设一种语言，
  // 中英混着说必然出错；把不准的文字填进输入框会让人误当成结果。
  const cap = document.createElement('div');
  cap.className = 'live-cap';
  cap.innerHTML = '<b></b><span></span><em></em>';
  const capTag = cap.querySelector('b');
  const capText = cap.querySelector('span');
  const capHint = cap.querySelector('em');
  (field.closest('.inrow') || field).after(cap);
  const wave = $('[data-wave]', field);
  for (let i = 0; i < BARS; i++) wave.appendChild(document.createElement('i'));
  const bars = $$('i', wave);

  const draw = (values) => bars.forEach((b, i) => {
    const v = values[i] ?? 0;
    b.style.height = Math.max(3, v) + 'px';
    b.style.background = v > 17 ? 'var(--accent-hi)' : v > 9 ? 'var(--accent)' : 'var(--accent-dim)';
  });

  let on = false, raf = null, media = null, ctx = null, rec = null, chunks = [];
  let sr = null, live = '', base = '';

  async function start() {
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      msg('拿不到麦克风权限，检查一下系统设置里的隐私权限');
      return;
    }
    
    on = true;
    field.classList.add('recording');

    // 波形和录音共用同一路音频流
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const an = ctx.createAnalyser();
      an.fftSize = 64;
      ctx.createMediaStreamSource(media).connect(an);
      const data = new Uint8Array(an.frequencyBinCount);
      const loop = () => {
        an.getByteFrequencyData(data);
        draw([...data].slice(0, BARS).map((v) => (v / 255) * 26));
        raf = requestAnimationFrame(loop);
      };
      loop();
    } catch (err) { /* 波形画不出来不影响录音 */ }

    chunks = [];
    const mime = pickMime();
    rec = new MediaRecorder(media, mime ? { mimeType: mime } : undefined);
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    rec.start();

    // 记住开录前已有的内容 —— 不清空，方便分几次说完
    base = target.value;
    live = '';
    capTag.textContent = '实时·粗略';
    capText.textContent = '听着…';
    // 明确告诉用户：不点第二次不会开始转写。不然容易以为说完就完了
    capHint.textContent = '再点一次麦克风 → 结束并开始转写';
    cap.classList.remove('busy');
    cap.classList.add('on');
    sr = startLiveCaption(lang, (text) => {
      live = text;
      if (on) capText.textContent = text || '听着…';
    });
  }

  async function stop() {
    on = false;
    if (sr) { try { sr.stop(); } catch (e) { /* 已经停了 */ } sr = null; }
    // 不马上收起字幕行 —— 它要接着显示"正在转写"的加载状态
    // 先把 recorder 停干净拿到数据，再关音频流 —— 顺序反了会丢掉最后一段
    const blob = await new Promise((done) => {
      if (!rec || rec.state === 'inactive') return done(null);
      rec.onstop = () => done(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
      rec.stop();
    });

    if (raf) { cancelAnimationFrame(raf); raf = null; }
    if (media) { media.getTracks().forEach((t) => t.stop()); media = null; }
    if (ctx) { ctx.close(); ctx = null; }
    rec = null;
    draw(new Array(BARS).fill(0));

    if (!blob || blob.size < 1200) {       // 太短基本是误触
      cap.classList.remove('on');
      field.classList.remove('recording');
      target.value = joinSpeech(base, live);   // 实时字幕里有东西就留着，别白说
      msg(live ? '录音太短，先用实时字幕的结果' : '录到的太短了');
      return;
    }

    // 转写要几秒，必须有明确的加载态：麦克风转圈 + 字幕行换成"正在转写"
    btn.classList.add('busy');
    btn.disabled = true;
    field.classList.remove('recording');
    capTag.textContent = '转写中';
    capText.textContent = live || '正在用本地模型识别…';
    capHint.textContent = '';
    cap.classList.add('busy');
    try {
      const form = new FormData();
      form.append('audio', blob, 'rec' + (blob.type.includes('mp4') ? '.mp4' : '.webm'));
      form.append('lang', lang);
      const r = await (await fetch('/api/transcribe', { method: 'POST', body: form })).json();
      if (r.ok) {
        // 追加到开录前的内容后面，并让用户先改再提交 —— 识别总有错，
        // 跟终端版 edit_text() 一个道理
        target.value = joinSpeech(base, r.text);
        target.focus();
        target.setSelectionRange(target.value.length, target.value.length);
      } else if (live) {
        // whisper 失败但实时字幕有内容，就留着它 —— 比清空让用户重说一遍好
        target.value = joinSpeech(base, live);
        target.focus();
        msg('本地识别失败，先用实时字幕的结果，可以改');
      } else {
        msg(r.msg || '转写失败');
      }
    } catch (err) {
      if (live) { target.value = joinSpeech(base, live); msg('转写请求失败，先用实时字幕的结果'); }
      else msg('转写请求失败：' + err.message);
    } finally {
      btn.classList.remove('busy');
      btn.disabled = false;
      cap.classList.remove('on', 'busy');
    }
  }

  btn.addEventListener('click', () => (on ? stop() : start()));
}

// 进页面就问一次模型状态：还在加载的话提前告诉用户，别等按了才发现要等十几秒
fetch('/api/transcribe/status').then((r) => r.json()).then((d) => {
  if (!d.ready) console.info('[stt] ' + d.msg);
});

$$('.mic-btn').forEach(setupMic);

/* ==================== 单词 ====================
   主次：查词是主角，生词本是收起的抽屉，进来不自动选词。 */

// 熟练度：没做过测验的词是 null，要显示"未测过"而不是 0 分
const dots = (n) => n === null || n === undefined
  ? '<span style="color:var(--text-5);font-size:11px">未测</span>'
  : `<span style="color:var(--accent)">${'●'.repeat(Math.round(n))}</span>` +
    `<span style="color:var(--text-5)">${'○'.repeat(Math.max(0, 5 - Math.round(n)))}</span>`;

let wordState = { word: '', body: '' };

function wordSetStage(n) {
  $('#w-stage').dataset.stage = String(n);
}

function collapseWordRounds() {
  $$('#w-thread .round').forEach((r) => r.classList.remove('open'));
}

/* 往线索里流一条 round。解析和追问走同一条路 ——
   所以追问进来时，前面那大段解析会自动收起，屏幕上只留当前在看的。 */
async function streamRound(title, url, body) {
  const round = addRound(title, '#w-thread');
  const md = $('.md', round);
  let raw = '';
  md.classList.add('caret');
  await stream(url, body, (m) => {
    if (m.delta) { raw += m.delta; md.textContent = raw; }
    if (m.warn || m.error) wordMsg(m.warn || m.error);
  });
  md.classList.remove('caret');
  if (raw.trim()) md.innerHTML = mdToHtml(raw);
  return raw;
}

async function analyzeWord(word) {
  wordState = { word, body: '' };
  wordSetStage(2);
  $('#w-word').textContent = word;
  $('#w-badge').textContent = '';
  $('#w-stars').textContent = '';
  $('#w-thread').innerHTML = '';
  $('#w-saved').innerHTML = '';
  $('.wcard').classList.remove('ready');
  $('.wcard').classList.remove('savable');
  $('#w-next').classList.remove('pulse');
  $('#w-save-note').textContent = '总结这个词，存进生词本';
  $('#w-save-note').disabled = false;
  wordMsg('');

  // 先把词读出来 —— 查词的第一件事是知道它怎么念。
  // 跟解析并行，不用等文字流完（点"查询"本身就是用户手势，不会被浏览器拦）
  speak($('#w-word'), word, $('#w-play'));

  wordState.body = await streamRound('词条解析', '/api/word/analyze', { word });
  const st = (wordState.body.match(/★+☆*/) || [''])[0];   // 星级拎到卡头上，别埋在正文里
  $('#w-stars').textContent = st;
  $('.wcard').classList.add('ready');
  $('.wcard').classList.add('savable');   // 新解析出来的内容还没存过
}

function wordMsg(text) {
  const box = $('#w-msg');
  box.textContent = text;
  if (text) setTimeout(() => { if (box.textContent === text) box.textContent = ''; }, 4000);
}

bindSend('#w-add', '#w-go', analyzeWord);

$('#w-play').addEventListener('click', (e) =>
  speak($('#w-word'), wordState.word, e.target));

$('#w-cam').addEventListener('click', () => window.open(
  'https://dictionary.cambridge.org/dictionary/english-chinese-simplified/' +
  encodeURIComponent(wordState.word), '_blank'));

$('#w-next').addEventListener('click', () => {
  wordSetStage(1);
  $('#w-next').classList.remove('pulse');
  $('#w-add').value = '';
  $('#w-add').focus();
});

bindSend('#w-more', '#w-more-send', async (question) => {
  await streamRound(question, '/api/word/followup', { question, word: wordState.word });
  // 追问出了新东西，这才值得存 —— 没追问过的已存笔记不该出现「总结」按钮
  $('.wcard').classList.add('savable');
});

$('#w-save-note').addEventListener('click', async (e) => {
  const btn = e.target;
  const label = btn.textContent;
  btn.textContent = '正在总结…';
  btn.disabled = true;
  const r = await post('/api/word/save-note', { word: wordState.word });
  if (!r.ok) {
    btn.textContent = label;
    btn.disabled = false;
    wordMsg(r.msg || '保存失败');
    return;
  }
  btn.textContent = r.summarized ? '✓ 已总结并存入生词本' : '✓ 已存入生词本';
  collapseWordRounds();          // 存完了，前面的讨论过程收起来，留总结当结论
  $('#w-saved').innerHTML =
    `<div class="card slide-up" style="margin-top:12px">
       <div class="label acc">${r.summarized ? '存进生词本的总结' : '存进生词本的内容'}</div>
       <div class="md"></div>
     </div>`;
  $('#w-saved .md').innerHTML = mdToHtml(r.note || '');
  afterWordSaved();
  // 这一轮到此为止，把"查下一个词"点亮，明确告诉用户下一步在哪
  $('#w-next').classList.add('pulse');
});

function afterWordSaved() {
  refreshWordCount();
  closeWordBook();                    // 生词本内容变了，下次展开重新取
}

/* ========== 生词本：可横滑的卡片牌组 ========== */

// 从笔记里抽一句中文释义当卡片摘要。
// 必须先剥掉 markdown 标记再匹配 —— 模型写的是 `**释义**：喧闹的`，
// 中间那两个星号会把 /释义[:：]/ 挡住。
function glossOf(md) {
  const plain = (md || '').replace(/[*`_]/g, '');
  const m = plain.match(/(?:中文释义|中文|释义)\s*[:：]\s*([^\n]+)/);
  let text = m ? m[1] : '';
  if (!text) {
    const lines = plain.split('\n')
      .map((l) => l.replace(/^[-•\d.、\s]+/, '').trim())
      .filter(Boolean);
    // 跳过"词头 + 词性"那种纯英文行，它不是释义
    text = lines.find((l) => l.length > 6 && /[\u4e00-\u9fa5]/.test(l)) || lines[0] || '';
  }
  // 统一清理：
  // - 开头的项目符号（模型会用 -、•、–，还可能夹窄空格 \u202f）
  //   注意「**释义**：」后面常紧跟换行，上面那个 \s* 会跨过换行把 "- " 一起抓进来
  // - 英文括注和例句/搭配/辨析，卡片上只放第一句中文释义
  text = text
    .replace(/^[\s\u00a0\u202f\-–—•·>]+/, '')
    .split(/例句|Example|English|常见搭配|搭配|辨析|同义词|用法/)[0]
    .split(/[(（]/)[0]
    .split('。')[0]
    .trim();
  return text.slice(0, 56) || '（还没有笔记）';
}

const deckStars = (s) => s
  ? `<span class="stars">${esc(s)}</span>`
  : '<span class="stars" style="color:var(--text-5)" title="解析里没给星级">—</span>';

/* ========== 层叠轮播（coverflow）通用组件 ==========
   生词本和练习记录都用它。抽出来是因为手势那部分（连续位移、吸附、
   键盘、圆点、提拉展开、容器高度跟随）有一百多行，两份重复维护迟早走偏。

   调用方只提供 tile(item) 返回卡片内部 HTML，以及 onAction 处理
   卡片里 [data-act] 按钮的点击。 */

let activeDeck = null;     // 当前开着的那个轮播，键盘翻页要知道操作谁

function mountCoverflow(opts) {
  const { deck, pager, foot, posEl, dotBox, prev, next, items, tile, onAction } = opts;

  pager.hidden = !items.length;
  foot.hidden = !items.length;
  if (!items.length) {
    deck.innerHTML = `<div class="hint" style="padding:10px 2px">${esc(opts.emptyText || '还是空的')}</div>`;
    return;
  }

  let index = 0;
  deck.innerHTML = items.map((it) => `
    <div class="wslide"><div class="wbig">${tile(it)}</div></div>`).join('');
  const slides = $$('.wslide', deck);
  dotBox.innerHTML = items.map(() => '<i></i>').join('');

  function fitHeight() {
    const cur = slides[index];
    if (cur) deck.style.height = cur.querySelector('.wbig').offsetHeight + 16 + 'px';
  }

  // center 可以是小数 —— 滑动过程中按连续位置摆位，停手后才吸附到整数
  function layout(center = index) {
    slides.forEach((sl, i) => {
      const d = i - center;
      const ad = Math.abs(d);
      // 衰减刻意温和：侧卡要清楚可见，不是快消失的影子
      sl.style.transform =
        `translateX(-50%) translateX(${d * 47}%) scale(${Math.max(0.78, 1 - ad * 0.1)})`;
      sl.style.opacity = ad > 2 ? 0 : String(Math.max(0, 1 - ad * 0.22));
      sl.style.zIndex = String(50 - Math.round(ad));
      sl.style.pointerEvents = ad > 2 ? 'none' : 'auto';
      sl.classList.toggle('active', ad < 0.5);
      if (ad >= 0.5) sl.classList.remove('up');     // 翻走的那张自动收起
    });
    posEl.textContent = `${Math.round(center) + 1} / ${items.length}`;
    $$('i', dotBox).forEach((d, k) => d.classList.toggle('on', k === Math.round(center)));
    prev.disabled = index <= 0;
    next.disabled = index >= items.length - 1;
    fitHeight();
  }

  const go = (k) => {
    index = Math.max(0, Math.min(items.length - 1, k));
    pos = index;
    slides.forEach((sl) => { sl.style.transition = ''; });
    layout();
  };

  slides.forEach((slide, i) => {
    $('.wbig', slide).addEventListener('click', (e) => {
      const act = e.target.closest('[data-act]');
      if (act) { onAction(act.dataset.act, items[i], slide, act); return; }
      if (i !== index) { go(i); return; }          // 点两侧的卡片 = 翻到它
      slide.classList.toggle('up');                // 点中间那张 = 往上提拉展开
      setTimeout(fitHeight, 30);
      setTimeout(fitHeight, 430);
    });
  });

  const nav = (fn) => (e) => { e.currentTarget.blur(); fn(); };
  prev.onclick = nav(() => go(index - 1));
  next.onclick = nav(() => go(index + 1));
  $$('i', dotBox).forEach((d, k) => d.addEventListener('click', nav(() => go(k))));

  /* 翻页手势：按位移连续响应 + 停手吸附，不去划分"一次手势"。
     wheel 事件流里没有可靠的手势边界 —— 加锁的写法要么一滑飞过好几张
     （惯性尾巴攒够阈值又翻），要么锁不放（靠事件间隔判断结束，
     而触控板松手后还在持续发惯性事件，那个间隔等不到）。 */
  const PX_PER_CARD = 220;     // 实测标定：轻扫≈1张，重扫≈3张，连滑两次≈2张
  let pos = index, snapTimer = null;
  deck.onwheel = (e) => {
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;   // 纵向滚动交给页面
    e.preventDefault();
    const step = Math.max(-60, Math.min(60, e.deltaX)) / PX_PER_CARD;  // 上限防偶发巨大 delta
    pos = Math.max(0, Math.min(items.length - 1, pos + step));
    slides.forEach((sl) => { sl.style.transition = 'none'; });
    layout(pos);
    clearTimeout(snapTimer);
    snapTimer = setTimeout(() => {
      slides.forEach((sl) => { sl.style.transition = ''; });
      index = Math.round(pos);
      pos = index;
      layout();
    }, 90);
  };

  activeDeck = { go, get index() { return index; }, count: items.length };
  layout();
  setTimeout(fitHeight, 60);      // markdown 渲染完再量一次，高度才准
  return { go, reload: opts.reload };
}

// 键盘翻页统一走这里，两个轮播共用。焦点在输入框里时不抢键。
document.addEventListener('keydown', (e) => {
  if (!activeDeck) return;
  if (/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
  if (e.key === 'ArrowLeft') { e.preventDefault(); activeDeck.go(activeDeck.index - 1); }
  if (e.key === 'ArrowRight') { e.preventDefault(); activeDeck.go(activeDeck.index + 1); }
});

/* ========== 生词本 ========== */
async function loadWordBook() {
  const list = await (await fetch('/api/words')).json();
  mountCoverflow({
    deck: $('#w-deck'), pager: $('#w-pager'), foot: $('#w-foot'),
    posEl: $('#w-pos'), dotBox: $('#w-dots'),
    prev: $('#w-prev'), next: $('#w-next-card'),
    items: list,
    emptyText: '生词本还是空的，查个词存进来吧',
    tile: (w) => `
      <div class="wbig-top">
        ${deckStars(w.stars)}
        <span class="wbig-prof" title="${w.proficiency == null ? '还没测过' : '熟练度 ' + w.proficiency + '/5'}">${dots(w.proficiency)}</span>
      </div>
      <div class="wbig-word en">${esc(w.word)}</div>
      <div class="wbig-gloss">${esc(glossOf(w.usage))}</div>
      <div class="wbig-foot">
        <span>存于 ${esc(w.time || '未知')}</span>
        <span class="chev">⌄</span>
      </div>
      <div class="wbig-detail"><div class="wbig-detail-inner">
        <div class="card md">${mdToHtml(w.usage || '（这个词还没有笔记）')}</div>
        <div class="row" style="margin-top:12px">
          <button class="pill acc" data-act="review">追问这个词</button>
          <button class="pill" data-act="test">出题测一测</button>
          <button class="pill" data-act="del" style="margin-left:auto;background:#5a2523;color:#f0c9c6">删除</button>
        </div>
      </div></div>`,
    onAction: async (act, w, slide, btn) => {
      if (act === 'review') return showSavedWord(w.word);
      if (act === 'test') {
        const old = btn.textContent;
        btn.textContent = '出题还没接上';
        btn.disabled = true;
        setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 2000);
        return;
      }
      // 删除藏在提拉展开后的动作里 —— 必须先点开看清是哪个词才能删
      const r = await post('/api/archive/delete', { kind: 'word', id: w.id });
      if (!r.ok) { toast(r.msg || '删除失败'); return; }
      toast(`已删除「${w.word}」`, '撤销', async () => {
        const u = await post('/api/archive/undo', {});
        if (u.ok) { await loadWordBook(); refreshWordCount(); } else toast(u.msg || '撤销失败');
      });
      await loadWordBook();
      refreshWordCount();
    },
  });
}

/* ========== 练习记录：跟生词本同一套轮播 ========== */
async function loadPracticeBook() {
  // 全部显示。之前只取 3 条是照搬终端版 /doc 的做法，不是资源考虑；
  // 做成幻灯片之后没有只给 3 条的理由了。
  const items = await (await fetch('/api/archive?filter=draft')).json();
  mountCoverflow({
    deck: $('#p-deck'), pager: $('#p-pager'), foot: $('#p-foot'),
    posEl: $('#p-pos'), dotBox: $('#p-dots'),
    prev: $('#p-prev'), next: $('#p-next-card'),
    items,
    emptyText: '还没有练习记录，改一句存进来吧',
    tile: (it) => `
      <div class="wbig-top">
        <span class="wbig-badge">${esc(it.when)}</span>
        ${it.note ? '<span class="wbig-prof" title="有分析笔记">📝</span>' : ''}
      </div>
      ${it.old ? `<div class="wbig-old en">${esc(it.old)}</div>` : ''}
      <div class="wbig-new en">${esc(it.title || '')}</div>
      <div class="wbig-foot">
        <span>${it.note ? '点开看分析笔记' : '点开看详情'}</span>
        <span class="chev">⌄</span>
      </div>
      <div class="wbig-detail"><div class="wbig-detail-inner">
        ${it.old ? `<div class="label">你说的</div><div class="en" style="color:var(--text-3);margin-bottom:10px">${esc(it.old)}</div>` : ''}
        <div class="label acc">地道版</div>
        <div class="en" style="margin-bottom:12px">${esc(it.title || '')}</div>
        ${it.note ? `<div class="card md">${mdToHtml(it.note)}</div>` : '<div class="hint">这条没有分析笔记</div>'}
        <div class="row" style="margin-top:12px">
          <button class="pill" data-act="play">▶ 朗读地道版</button>
          <button class="pill" data-act="del" style="margin-left:auto;background:#5a2523;color:#f0c9c6">删除</button>
        </div>
      </div></div>`,
    onAction: async (act, it, slide, btn) => {
      if (act === 'play') {
        const el = $('.wbig-new', slide);
        return speak(el, it.title || '', btn);
      }
      const r = await post('/api/archive/delete', { kind: 'draft', id: it.id });
      if (!r.ok) { toast(r.msg || '删除失败'); return; }
      toast('已删除这条记录', '撤销', async () => {
        const u = await post('/api/archive/undo', {});
        if (u.ok) { await loadPracticeBook(); refreshPracticeCount(); } else toast(u.msg || '撤销失败');
      });
      await loadPracticeBook();
      refreshPracticeCount();
    },
  });
}

function closeWordBook() {
  $('#w-deck').innerHTML = '';
  $('#w-pager').hidden = true;
  $('#w-foot').hidden = true;
  $('#w-section').classList.remove('open');
  activeDeck = null;                 // 关了就别再吃键盘方向键
}

$('#w-book').addEventListener('click', (e) => {
  // 点完立刻失焦。不然按方向键翻页时 Chrome 会给这个还留着焦点的按钮
  // 画上 focus-visible 焦点框，看起来像"我的生词本被选中了"
  e.currentTarget.blur();
  if ($('#w-section').classList.contains('open')) { closeWordBook(); return; }
  $('#w-section').classList.add('open');
  loadWordBook();
});

/* 复习：把已存的笔记放到主区，可以接着追问 */
async function showSavedWord(word) {
  // 走 POST /api/word/open：它会把这个词的笔记塞进服务端 thread 当上下文。
  // 不换上下文的话，追问会在上一个查过的词的语境里作答。
  const d = await post('/api/word/open', { word });
  if (!d.ok) { wordMsg(d.msg || '读取失败'); return; }
  wordState = { word: d.word, body: d.usage || '' };
  wordSetStage(2);
  $('#w-word').textContent = d.word;
  $('#w-stars').textContent = d.stars || (d.usage || '').match(/★+☆*/)?.[0] || '';
  $('#w-badge').textContent =
    `存于 ${d.time || '未知时间'}${d.proficiency != null ? ` · 熟练度 ${d.proficiency}/5` : ' · 还没测过'}`;
  $('#w-thread').innerHTML = '';
  $('#w-saved').innerHTML = '';
  $('#w-next').classList.remove('pulse');
  // 已存的笔记也放进线索里当第一条，这样追问时它会自动收起
  const round = addRound('已存的笔记', '#w-thread');
  $('.md', round).innerHTML = mdToHtml(d.usage || '');
  // 只给追问，不给「总结」—— 这条笔记已经在生词本里了，没有新东西可存。
  // 等真的追问出新内容，savable 才加上（见 bindSend('#w-more') 那里）
  $('.wcard').classList.add('ready');
  $('.wcard').classList.remove('savable');
  $('#w-save-note').textContent = '总结这个词，存进生词本';
  $('#w-save-note').disabled = false;
  closeWordBook();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function refreshWordCount() {
  const list = await (await fetch('/api/words')).json();
  $('#w-count').textContent = list.length ? `${list.length} 个词` : '还是空的';
}

/* ==================== 长难句 ==================== */
let parseState = { sentence: '' };

function parseMsg(t) {
  const b = $('#s-msg');
  b.textContent = t;
  if (t) setTimeout(() => { if (b.textContent === t) b.textContent = ''; }, 4000);
}

async function analyzeSentence(sentence) {
  parseState.sentence = sentence;
  $('#s-stage').dataset.stage = '2';
  $('#s-sentence').textContent = sentence;
  $('#s-thread').innerHTML = '';
  $('#s-saved').innerHTML = '';
  $('#s-save').textContent = '总结成复习笔记';
  $('#s-save').disabled = false;
  $('#s-next').classList.remove('pulse');
  parseMsg('');

  const round = addRound('结构解析', '#s-thread');
  const md = $('.md', round);
  let raw = '';
  md.classList.add('caret');
  await stream('/api/parse/analyze', { sentence }, (m) => {
    if (m.delta) { raw += m.delta; md.textContent = raw; }
    if (m.warn || m.error) parseMsg(m.warn || m.error);
  });
  md.classList.remove('caret');
  if (raw.trim()) md.innerHTML = mdToHtml(raw);
}

bindSend('#s-input', '#s-go', analyzeSentence);

$('#s-play').addEventListener('click', (e) =>
  speak($('#s-sentence'), parseState.sentence, e.target));

// 追问不能复用 analyzeSentence —— 那会把标题栏的原句换成问题本身
bindSend('#s-more', '#s-more-send', async (question) => {
  const round = addRound(question, '#s-thread');
  const md = $('.md', round);
  let raw = '';
  md.classList.add('caret');
  await stream('/api/parse/followup', { question }, (m) => {
    if (m.delta) { raw += m.delta; md.textContent = raw; }
    if (m.warn || m.error) parseMsg(m.warn || m.error);
  });
  md.classList.remove('caret');
  if (raw.trim()) md.innerHTML = mdToHtml(raw);
});

$('#s-save').addEventListener('click', async (e) => {
  const btn = e.target, label = btn.textContent;
  btn.textContent = '正在总结…';
  btn.disabled = true;
  const r = await post('/api/parse/save', {});
  if (!r.ok) { btn.textContent = label; btn.disabled = false; parseMsg(r.msg || '保存失败'); return; }
  btn.textContent = '✓ 已存成笔记';
  $$('#s-thread .round').forEach((x) => x.classList.remove('open'));   // 过程收起，留总结
  $('#s-saved').innerHTML =
    `<div class="card slide-up" style="margin-top:12px">
       <div class="label acc">存下的复习笔记</div><div class="md"></div>
     </div>`;
  $('#s-saved .md').innerHTML = mdToHtml(r.note || '');
  $('#s-next').classList.add('pulse');
  refreshParseCount();
  $('#s-list').innerHTML = '';
  $('#s-section').classList.remove('open');
});

$('#s-next').addEventListener('click', () => {
  $('#s-stage').dataset.stage = '1';
  $('#s-next').classList.remove('pulse');
  $('#s-input').value = '';
  $('#s-input').focus();
});

$('#s-review').addEventListener('click', async (e) => {
  const btn = e.target;
  btn.disabled = true;
  $('#s-report').innerHTML = '<div class="card md caret"></div>';
  const md = $('#s-report .md');
  let raw = '';
  await stream('/api/parse/review', {}, (m) => {
    if (m.delta) { raw += m.delta; md.textContent = raw; }
    if (m.error) md.textContent = m.error;
  });
  md.classList.remove('caret');
  if (raw.trim()) md.innerHTML = mdToHtml(raw);
  btn.disabled = false;
});

$('#s-book').addEventListener('click', async (e) => {
  e.currentTarget.blur();
  const sec = $('#s-section');
  if (sec.classList.contains('open')) {
    sec.classList.remove('open');
    $('#s-list').innerHTML = '';
    return;
  }
  sec.classList.add('open');
  $('#s-list').innerHTML = '<div class="hint">读取中…</div>';
  const items = await (await fetch('/api/archive?filter=parse')).json();
  if (!items.length) { $('#s-list').innerHTML = '<div class="hint">还没有笔记</div>'; return; }
  renderCards(items, $('#s-list'), () => $('#s-book').click());
});

async function refreshParseCount() {
  const items = await (await fetch('/api/archive?filter=parse')).json();
  $('#s-count').textContent = items.length ? `${items.length} 条` : '还是空的';
}

/* ==================== 随便问 ==================== */
let chatMode = 'local';
$$('#c-mode button').forEach((b) => b.addEventListener('click', () => {
  $$('#c-mode button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on');
  chatMode = b.dataset.mode;
}));

function chatMsg(t) {
  const b = $('#c-msg');
  b.textContent = t;
  if (t) setTimeout(() => { if (b.textContent === t) b.textContent = ''; }, 4000);
}

bindSend('#c-input', '#c-send', async (msg) => {
  $('#c-stage').dataset.stage = '2';
  const box = $('#c-bubbles');
  box.insertAdjacentHTML('beforeend', `<div class="b-user"><span>${esc(msg)}</span></div>`);
  const deep = chatMode === 'deep';
  box.insertAdjacentHTML('beforeend',
    `<div class="b-ai ${deep ? 'deep' : ''}"><span class="tag">${deep ? '深度' : '本地'}</span><span class="body caret"></span></div>`);
  const body = box.lastElementChild.querySelector('.body');
  let raw = '';
  await stream('/api/chat/send', { message: msg, mode: chatMode }, (m) => {
    if (m.delta) { raw += m.delta; body.textContent = raw; }
    if (m.warn || m.error) chatMsg(m.warn || m.error);
  });
  body.classList.remove('caret');
  if (raw.trim()) body.innerHTML = mdToHtml(raw);   // 深度模式常带表格和列表
  $('#c-save').textContent = '总结这次对话，存进档案';
  $('#c-save').disabled = false;
  body.scrollIntoView({ block: 'end', behavior: 'smooth' });
});

$('#c-save').addEventListener('click', async (e) => {
  const btn = e.target, label = btn.textContent;
  btn.textContent = '正在总结…';
  btn.disabled = true;
  const r = await post('/api/chat/save', {});
  if (!r.ok) { btn.textContent = label; btn.disabled = false; chatMsg(r.msg || '保存失败'); return; }
  btn.textContent = '✓ 已存进档案';
  $('#c-saved').innerHTML =
    `<div class="card slide-up" style="margin-top:12px">
       <div class="label acc">存进档案的总结</div><div class="md"></div>
     </div>`;
  $('#c-saved .md').innerHTML = mdToHtml(r.note || '');
  refreshChatCount();
  $('#c-list').innerHTML = '';
  $('#c-section').classList.remove('open');
});

$('#c-clear').addEventListener('click', async () => {
  await post('/api/chat/clear', {});
  $('#c-bubbles').innerHTML = '';
  $('#c-saved').innerHTML = '';
  $('#c-stage').dataset.stage = '1';
  $('#c-input').focus();
});

$('#c-book').addEventListener('click', async (e) => {
  e.currentTarget.blur();
  const sec = $('#c-section');
  if (sec.classList.contains('open')) {
    sec.classList.remove('open');
    $('#c-list').innerHTML = '';
    return;
  }
  sec.classList.add('open');
  $('#c-list').innerHTML = '<div class="hint">读取中…</div>';
  const items = await (await fetch('/api/archive?filter=chat')).json();
  if (!items.length) { $('#c-list').innerHTML = '<div class="hint">还没有对话总结</div>'; return; }
  renderCards(items, $('#c-list'), () => $('#c-book').click());
});

async function refreshChatCount() {
  const items = await (await fetch('/api/archive?filter=chat')).json();
  $('#c-count').textContent = items.length ? `${items.length} 条` : '还是空的';
}

/* ==================== 档案卡片（练习页和档案页共用） ====================
   正文默认收起两行，够长的卡片整张可点展开。
   后端发的是全文，截断只发生在 CSS 层 —— 之前后端就截好了，
   前端连全文都拿不到，点开也只有节选。 */
const SWIPE_W = 84;        // 删除按钮的宽度，也是滑开的距离
let justDragged = false;   // 拖动过就不要触发"点击展开"

function renderCards(items, box, onChange) {
  box.innerHTML = items.map((it, i) => {
    const extra = it.note || it.body || '';
    const long = extra.length > 80;
    const tips = [long ? '点击展开全文' : '', '左滑删除'].filter(Boolean).join(' · ');
    return `
    <div class="arc-wrap" style="animation-delay:${i * 45}ms">
      <button class="arc-del" data-kind="${it.kind}" data-id="${it.id}">删除</button>
      <div class="arc-card ${it.kind === 'draft' ? 'draft-kind' : ''}${long ? ' expandable' : ''}"
           ${long ? 'data-exp' : ''} title="${tips}">
        <div class="arc-head">
          <span class="kind">${it.kindLabel}</span><span class="when">${it.when}</span>
          ${long ? '<span class="chev">⌄</span>' : ''}
        </div>
        ${it.old ? `<div class="arc-old en">${esc(it.old)}</div>` : ''}
        ${it.title ? `<div class="arc-new en">${esc(it.title)}</div>` : ''}
        ${extra ? `<div class="arc-body">${mdToHtml(extra)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  $$('.arc-wrap', box).forEach(enableSwipe);

  $$('[data-exp]', box).forEach((card) => card.addEventListener('click', (e) => {
    if (e.target.closest('a') || justDragged) return;     // 卡片里的链接照常跳转
    if (card.closest('.arc-wrap').classList.contains('open')) return;  // 露出删除时点击只用于收回
    card.classList.toggle('open');
  }));

  $$('.arc-del', box).forEach((btn) => btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const wrap = btn.closest('.arc-wrap');
    const r = await post('/api/archive/delete',
      { kind: btn.dataset.kind, id: Number(btn.dataset.id) });
    if (!r.ok) { toast(r.msg || '删除失败'); return; }
    wrap.style.height = wrap.offsetHeight + 'px';
    requestAnimationFrame(() => wrap.classList.add('removing'));
    setTimeout(() => wrap.remove(), 300);
    // 攒了很久的学习档案，误删不该没救
    toast('已删除', '撤销', async () => {
      const u = await post('/api/archive/undo', {});
      if (u.ok && onChange) onChange();
      else if (!u.ok) toast(u.msg || '撤销失败');
    });
  }));
}

/* 左滑露出删除。支持鼠标拖、触控板横滑、触屏滑动（pointer 事件统一处理）。 */
function enableSwipe(wrap) {
  const card = $('.arc-card', wrap);
  let startX = 0, dragging = false, moved = 0;

  const finish = (dx) => {
    dragging = false;
    card.style.transition = '';
    card.style.transform = '';
    if (dx < -30) wrap.classList.add('open');
    else if (dx > 30) wrap.classList.remove('open');
    justDragged = moved > 6;
    setTimeout(() => { justDragged = false; }, 60);
  };

  card.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    startX = e.clientX; dragging = true; moved = 0;
    card.style.transition = 'none';
  });

  card.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - startX;
    moved = Math.abs(dx);
    if (moved < 4) return;
    const base = wrap.classList.contains('open') ? -SWIPE_W : 0;
    card.style.transform =
      `translateX(${Math.max(-SWIPE_W, Math.min(0, base + dx))}px)`;
  });

  card.addEventListener('pointerup', (e) => dragging && finish(e.clientX - startX));
  card.addEventListener('pointercancel', () => dragging && finish(0));
  card.addEventListener('pointerleave', (e) => dragging && finish(e.clientX - startX));

  // 触控板双指横滑
  card.addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaX) <= Math.abs(e.deltaY)) return;
    e.preventDefault();
    if (e.deltaX > 8) wrap.classList.add('open');
    if (e.deltaX < -8) wrap.classList.remove('open');
  }, { passive: false });
}

async function post(url, body) {
  return (await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })).json();
}

/* 带可选操作的提示条。删除这类不可逆动作靠它给撤销的机会，
   比弹个确认框打断流程好 —— 确认框会让人养成条件反射点确定。 */
let toastTimer = null;
function toast(text, actionLabel, onAction, ms = 6000) {
  clearTimeout(toastTimer);
  const box = $('#toast');
  box.innerHTML = `<span>${esc(text)}</span>` +
    (actionLabel ? `<button class="toast-act">${esc(actionLabel)}</button>` : '');
  box.classList.add('on');
  if (actionLabel) {
    $('.toast-act', box).addEventListener('click', () => {
      box.classList.remove('on');
      onAction();
    });
  }
  toastTimer = setTimeout(() => box.classList.remove('on'), ms);
}

/* ==================== 档案 ==================== */
async function loadArchive(filter) {
  const items = await (await fetch('/api/archive?filter=' + filter)).json();
  if (filter === 'all') $('#arc-count').textContent = items.length;  // 导航上是总数，不跟着筛选变
  renderCards(items, $('#a-list'), () => loadArchive(filter));
}
$('#a-analyze').addEventListener('click', async (e) => {
  const box = $('#a-report');
  box.innerHTML = '<div class="card md caret"></div>';
  const md = $('.md', box);
  e.target.disabled = true;
  let raw = '';
  await stream('/api/archive/analyze', {}, (m) => {
    if (m.delta) { raw += m.delta; md.textContent = raw; }
    if (m.error) md.textContent = m.error;
  });
  md.classList.remove('caret');
  if (raw.trim()) md.innerHTML = mdToHtml(raw);
  e.target.disabled = false;
});

$$('[data-filter]').forEach((b) => b.addEventListener('click', () => {
  $$('[data-filter]').forEach((x) => x.classList.remove('acc'));
  b.classList.add('acc');
  loadArchive(b.dataset.filter);
}));

/* ==================== 选词浮层 ==================== */
let pop = null;
const closePop = () => { if (pop) { pop.remove(); pop = null; } };

document.addEventListener('mousedown', (e) => {
  if (pop && !pop.contains(e.target)) closePop();
});

document.addEventListener('mouseup', async (e) => {
  if (pop && pop.contains(e.target)) return;
  const sel = window.getSelection();
  const text = sel.toString().trim();
  if (!text || !/^[A-Za-z][A-Za-z'-]*$/.test(text)) return closePop();
  if (!e.target.closest || !e.target.closest('.en')) return closePop();

  closePop();
  const r = sel.getRangeAt(0).getBoundingClientRect();
  pop = document.createElement('div');
  pop.className = 'pop';
  pop.innerHTML = `<div class="w">${esc(text)}</div><div class="ipa">查询中…</div>`;
  document.body.appendChild(pop);
  pop.style.left = Math.min(r.left + scrollX, innerWidth - 285) + 'px';
  pop.style.top = r.bottom + scrollY + 9 + 'px';

  const d = await (await fetch('/api/lookup/' + encodeURIComponent(text))).json();
  if (!pop) return;
  pop.innerHTML = `
    <div class="w">${esc(d.word)}</div>
    <div class="ipa">${esc(d.ipa)}</div>
    <div class="def">${esc(d.def)}</div>
    <div class="acts">
      <button class="pill acc" data-act="add">加入生词本</button>
      <button class="pill" data-act="cam">剑桥 ↗</button>
    </div>`;
  $('[data-act=cam]', pop).addEventListener('click', () => window.open(
    'https://dictionary.cambridge.org/dictionary/english-chinese-simplified/' +
    encodeURIComponent(d.word), '_blank'));
  $('[data-act=add]', pop).addEventListener('click', (ev) => {
    ev.target.textContent = '已加入';
    ev.target.disabled = true;
  });
});

async function refreshPracticeCount() {
  const items = await (await fetch('/api/archive?filter=draft')).json();
  $('#p-count').textContent = items.length ? `${items.length} 条` : '还是空的';
}

/* ========== 悬停提示 ==========
   用自己的浮层而不是原生 title：原生的延迟各浏览器不一致、样式也没法跟界面统一。
   1 秒延迟是刻意的 —— 太快会在鼠标路过时乱闪。 */
let tipEl = null, tipTimer = null;

function hideTip() {
  clearTimeout(tipTimer);
  if (tipEl) { tipEl.remove(); tipEl = null; }
}

function showTip(el) {
  hideTip();
  tipEl = document.createElement('div');
  tipEl.className = 'tip';
  tipEl.textContent = el.dataset.tip;
  document.body.appendChild(tipEl);
  const r = el.getBoundingClientRect();
  const w = tipEl.offsetWidth;
  tipEl.style.left = Math.max(8, Math.min(
    r.left + scrollX + r.width / 2 - w / 2, innerWidth - w - 8)) + 'px';
  tipEl.style.top = r.bottom + scrollY + 8 + 'px';
}

$$('[data-tip]').forEach((el) => {
  el.addEventListener('mouseenter', () => {
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => showTip(el), 1000);
  });
  el.addEventListener('mouseleave', hideTip);
  el.addEventListener('click', hideTip);
});

/* ========== 初始 ========== */
fetch('/api/archive?filter=all').then((r) => r.json())
  .then((items) => { $('#arc-count').textContent = items.length; });
refreshPracticeCount();
