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
    if (h) html += `<div class="md-h">${inline(h[1])}</div>`;
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
    if (b.dataset.view === 'word') loadWords();
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
  if (state.revised.trim()) renderDiff(state.draft, state.revised);
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
function addRound(title) {
  const thread = $('#p-thread');
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
    body: JSON.stringify({ revised: state.revised }),
  })).json();
  if (r.ok) {
    btn.textContent = r.summarized ? '✓ 已总结并存进记录' : '✓ 已存进记录';
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

/* ========== 录音：每个输入框各管各的 ==========
   录到的文字只填进自己那个框，不切换页面状态 ——
   说话是一种输入方式，不该等于"开始新对话"。 */
const BARS = 22;

function setupMic(btn) {
  const field = btn.closest('.field');
  const target = $(btn.dataset.mic);
  const wave = $('[data-wave]', field);
  for (let i = 0; i < BARS; i++) wave.appendChild(document.createElement('i'));
  const bars = $$('i', wave);

  const draw = (values) => bars.forEach((b, i) => {
    const v = values[i] ?? 0;
    b.style.height = Math.max(3, v) + 'px';
    b.style.background = v > 17 ? 'var(--accent-hi)' : v > 9 ? 'var(--accent)' : 'var(--accent-dim)';
  });

  let on = false, raf = null, media = null, ctx = null;

  async function start() {
    on = true;
    field.classList.add('recording');
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
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
    } catch (err) {
      msg('拿不到麦克风权限，先用假波形演示');
      const loop = () => { draw(Array.from({ length: BARS }, () => 4 + Math.random() * 20)); raf = setTimeout(loop, 90); };
      loop();
    }
  }

  async function stop() {
    on = false;
    if (raf) { cancelAnimationFrame(raf); clearTimeout(raf); raf = null; }
    if (media) { media.getTracks().forEach((t) => t.stop()); media = null; }
    if (ctx) { ctx.close(); ctx = null; }
    draw(new Array(BARS).fill(0));
    btn.textContent = '…';
    const d = await (await fetch('/api/practice/transcribe', { method: 'POST' })).json();
    btn.textContent = '🎙';
    field.classList.remove('recording');
    // 只填进这个框，让用户先改再提交 —— 识别总有错，跟终端版 edit_text() 一个道理
    target.value = d.text;
    target.focus();
  }

  btn.addEventListener('click', () => (on ? stop() : start()));
}

$$('.mic-btn').forEach(setupMic);

/* ==================== 单词 ==================== */
// 实心用强调色、空心用暗色，不然两个字形在小字号下几乎分不出来
const dots = (n) =>
  `<span style="color:var(--accent)">${'●'.repeat(n)}</span>` +
  `<span style="color:var(--text-5)">${'○'.repeat(4 - n)}</span>`;

async function loadWords() {
  const list = await (await fetch('/api/words')).json();
  $('#w-list').innerHTML = list.map((w, i) => `
    <button data-word="${w.word}" class="${i === 0 ? 'on' : ''}">
      <span>${w.word}</span>
      <span class="prof">${dots(w.proficiency)}</span>
    </button>`).join('');
  $$('#w-list button').forEach((b) => b.addEventListener('click', () => {
    $$('#w-list button').forEach((x) => x.classList.remove('on'));
    b.classList.add('on');
    showWord(b.dataset.word);
  }));
  if (list.length) showWord(list[0].word);
}

async function showWord(word) {
  $('#w-detail').innerHTML = '<div class="hint">查询中…</div>';
  const d = await (await fetch('/api/words/' + encodeURIComponent(word))).json();
  $('#w-detail').innerHTML = `
    <div class="row" style="align-items:baseline;gap:12px;margin-bottom:14px">
      <span style="font-size:27px">${esc(d.word)}</span>
      <span class="ipa" style="font-family:var(--font-mono);font-size:13px;color:var(--text-4)">${esc(d.ipa)}</span>
      <button class="pill ghost" style="margin-left:auto" data-cam="${esc(d.word)}">剑桥词典 ↗</button>
    </div>
    <div class="card" style="font-size:14px;line-height:1.7;color:var(--text-2)">${esc(d.usage)}</div>
    <div class="card">
      <div class="label acc">例句</div>
      ${d.examples.map((e) => `<div class="en" style="font-size:14px;line-height:1.7;color:var(--text-2)">${esc(e)}</div>`).join('')}
    </div>
    <div class="row" style="margin-top:14px">
      <button class="pill acc">出题练一练</button>
      <button class="pill">复习这个词</button>
    </div>`;
  const cam = $('[data-cam]', $('#w-detail'));
  cam.addEventListener('click', () => window.open(
    'https://dictionary.cambridge.org/dictionary/english-chinese-simplified/' +
    encodeURIComponent(d.word), '_blank'));
}

bindSend('#w-add', '#w-go', (word) => {
  $$('#w-list button').forEach((x) => x.classList.remove('on'));
  showWord(word);
});

/* ==================== 长难句 ==================== */
async function analyzeSentence(sentence) {
  $('#s-result').style.display = 'block';
  $('#s-thread').innerHTML = '';        // 换新句子时清掉上一轮的追问
  $('#s-sentence').textContent = sentence;
  $('#s-tags').textContent = '分析中…';
  const a = $('#s-analysis');
  a.textContent = '';
  a.classList.add('caret');
  await stream('/api/parse', { sentence }, (m) => {
    if (m.tags) $('#s-tags').textContent = m.tags;
    if (m.delta) a.textContent += m.delta;
  });
  a.classList.remove('caret');
}

bindSend('#s-input', '#s-go', analyzeSentence);

// 追问不能复用 analyzeSentence —— 那个会把标题栏的句子换成问题本身。
// 追问是在原分析下面接着聊，原句必须留在上面。
bindSend('#s-more', '#s-more-send', async (question) => {
  const box = $('#s-thread');
  box.insertAdjacentHTML('beforeend',
    `<div class="card"><div class="label">${esc(question)}</div><div class="md caret"></div></div>`);
  const body = box.lastElementChild.querySelector('.md');
  let raw = '';
  await stream('/api/parse', { sentence: question, followup: true }, (m) => {
    if (m.delta) { raw += m.delta; body.textContent = raw; }
    if (m.warn || m.error) msg(m.warn || m.error);
  });
  body.classList.remove('caret');
  if (raw.trim()) body.innerHTML = mdToHtml(raw);
});
$('#s-save').addEventListener('click', (e) => { e.target.textContent = '已存为笔记'; e.target.disabled = true; });

/* 这两个依赖的模块还是 MOCK，先给一句明确说明 ——
   点了毫无反应是最糟的，用户分不清是坏了还是没做。 */
const notReady = (sel, what) => $(sel).addEventListener('click', (e) => {
  const old = e.target.textContent;
  e.target.textContent = `${what}还没接真实逻辑`;
  e.target.disabled = true;
  setTimeout(() => { e.target.textContent = old; e.target.disabled = false; }, 2200);
});
notReady('#s-review', '长难句笔记复习');
notReady('#c-save', '对话总结存档');

/* ==================== 随便问 ==================== */
let chatMode = 'local';
$$('#c-mode button').forEach((b) => b.addEventListener('click', () => {
  $$('#c-mode button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on');
  chatMode = b.dataset.mode;
}));

bindSend('#c-input', '#c-send', async (msg) => {
  const box = $('#c-bubbles');
  box.insertAdjacentHTML('beforeend', `<div class="b-user"><span>${esc(msg)}</span></div>`);
  const deep = chatMode === 'deep';
  box.insertAdjacentHTML('beforeend',
    `<div class="b-ai ${deep ? 'deep' : ''}"><span class="tag">${deep ? '深度' : '本地'}</span><span class="body caret"></span></div>`);
  const body = box.lastElementChild.querySelector('.body');
  await stream('/api/chat', { message: msg, mode: chatMode },
    (m) => { if (m.delta) body.textContent += m.delta; });
  body.classList.remove('caret');
  box.scrollIntoView({ block: 'end', behavior: 'smooth' });
});

/* ==================== 档案 ==================== */
async function loadArchive(filter) {
  const items = await (await fetch('/api/archive?filter=' + filter)).json();
  if (filter === 'all') $('#arc-count').textContent = items.length;  // 导航上是总数，不跟着筛选变
  $('#a-list').innerHTML = items.map((it, i) => `
    <div class="arc-card ${it.kind === 'draft' ? 'draft-kind' : ''}" style="animation-delay:${i * 40}ms">
      <div class="arc-head"><span class="kind">${it.kindLabel}</span><span class="when">${it.when}</span></div>
      ${it.old ? `<div class="arc-old en">${esc(it.old)}</div>` : ''}
      ${it.title ? `<div class="arc-new en">${esc(it.title)}</div>` : ''}
      ${it.body ? `<div style="font-size:13px;color:var(--text-3);line-height:1.65;margin-top:5px">${esc(it.body)}</div>` : ''}
      ${it.note ? `<div class="arc-note">${esc(it.note)}</div>` : ''}
    </div>`).join('');
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

/* ========== 初始 ========== */
fetch('/api/archive?filter=all').then((r) => r.json())
  .then((items) => { $('#arc-count').textContent = items.length; });
