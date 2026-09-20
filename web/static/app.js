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
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  let html = '', inList = false;
  for (const raw of esc(src).split('\n')) {
    const line = raw.trim();
    const li = line.match(/^[*\-+]\s+(.*)$/);
    if (li) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inline(li[1])}</li>`;
      continue;
    }
    if (inList) { html += '</ul>'; inList = false; }
    if (!line) continue;
    const h = line.match(/^#{1,4}\s+(.*)$/);
    const q = line.match(/^&gt;\s*(.*)$/);           // esc() 已经把 > 转成了 &gt;
    if (h) html += `<div class="md-h">${inline(h[1])}</div>`;
    else if (q) html += `<blockquote>${inline(q[1])}</blockquote>`;
    else html += `<p>${inline(line)}</p>`;
  }
  return inList ? html + '</ul>' : html;
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

async function correct() {
  const text = $('#p-input').value.trim();
  if (!text) return;
  state.draft = text;
  state.revised = '';
  $('#p-input').value = '';
  $('#p-result').style.display = 'block';
  $('#p-why-box').style.display = 'none';
  $('#p-draft').textContent = text;
  const rev = $('#p-revised');
  rev.textContent = '';
  rev.classList.add('caret');

  msg('');
  $('#p-save').textContent = '存档';
  $('#p-save').disabled = false;

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
    e.target.textContent = `已存档 · 共 ${r.total} 条`;
    e.target.disabled = true;
  } else {
    msg(r.msg || '存档失败');
  }
});

async function askWhy(url, body) {
  const t = $('#p-why-text');
  let raw = '';
  t.textContent = '';
  t.classList.add('caret');
  // 流式阶段先按纯文本追加 —— markdown 语法是跨行的，边收边渲染会一直闪烂格式
  await stream(url, body, (m) => {
    if (m.delta) { raw += m.delta; t.textContent = raw; }
    if (m.warn || m.error) msg(m.warn || m.error);
  });
  t.classList.remove('caret');
  if (raw.trim()) t.innerHTML = mdToHtml(raw);
  $('#p-save-note').style.display = 'inline-flex';
}

$('#p-why').addEventListener('click', () => {
  $('#p-why-box').style.display = 'block';
  askWhy('/api/practice/why', { draft: state.draft, revised: state.revised });
});

$('#p-why-input').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const question = e.target.value.trim();
  if (!question) return;
  e.target.value = '';
  askWhy('/api/practice/why/followup', { question });
});

$('#p-save-note').addEventListener('click', async (e) => {
  const r = await (await fetch('/api/practice/save-note', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ revised: state.revised }),
  })).json();
  msg(r.ok ? '分析已挂到这条记录上' : (r.msg || '保存失败'));
});

/* ========== 录音 + 实时波形 ========== */
const BARS = 26;
const wave = $('#p-wave');
for (let i = 0; i < BARS; i++) wave.appendChild(document.createElement('i'));
const bars = $$('i', wave);

let rec = { on: false, ctx: null, raf: null, stream: null };

function drawBars(values) {
  bars.forEach((b, i) => {
    const v = values[i] ?? 0;
    b.style.height = Math.max(3, v) + 'px';
    b.style.background = v > 22 ? 'var(--accent-hi)' : v > 11 ? 'var(--accent)' : 'var(--accent-dim)';
  });
}

async function startRec() {
  rec.on = true;
  $('#p-mic').classList.add('rec');
  $('#p-recstate').textContent = '录音中 · 再点一次结束';
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    rec.ctx = ctx;
    const an = ctx.createAnalyser();
    an.fftSize = 64;
    ctx.createMediaStreamSource(rec.stream).connect(an);
    const data = new Uint8Array(an.frequencyBinCount);
    const loop = () => {
      an.getByteFrequencyData(data);
      drawBars([...data].slice(0, BARS).map((v) => (v / 255) * 34));
      rec.raf = requestAnimationFrame(loop);
    };
    loop();
  } catch (err) {
    $('#p-recstate').textContent = '拿不到麦克风，先用假波形演示';
    const loop = () => {
      drawBars(Array.from({ length: BARS }, () => 4 + Math.random() * 28));
      rec.raf = setTimeout(loop, 90);
    };
    loop();
  }
}

function stopRec() {
  rec.on = false;
  $('#p-mic').classList.remove('rec');
  $('#p-recstate').textContent = '转写中…（骨架阶段返回示例句）';
  if (rec.raf) { cancelAnimationFrame(rec.raf); clearTimeout(rec.raf); rec.raf = null; }
  if (rec.stream) { rec.stream.getTracks().forEach((t) => t.stop()); rec.stream = null; }
  if (rec.ctx) { rec.ctx.close(); rec.ctx = null; }
  drawBars(new Array(BARS).fill(0));
  fetch('/api/practice/transcribe', { method: 'POST' })
    .then((r) => r.json())
    .then((d) => {
      $('#p-input').value = d.text;
      $('#p-recstate').textContent = '转写完成，可改后提交';
    });
}

$('#p-mic').addEventListener('click', () => (rec.on ? stopRec() : startRec()));

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

/* ==================== 长难句 ==================== */
$('#s-go').addEventListener('click', async () => {
  const sentence = $('#s-input').value.trim();
  if (!sentence) return;
  $('#s-input').value = '';
  $('#s-result').style.display = 'block';
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
});
$('#s-save').addEventListener('click', (e) => { e.target.textContent = '已存为笔记'; e.target.disabled = true; });

/* ==================== 随便问 ==================== */
let chatMode = 'local';
$$('#c-mode button').forEach((b) => b.addEventListener('click', () => {
  $$('#c-mode button').forEach((x) => x.classList.remove('on'));
  b.classList.add('on');
  chatMode = b.dataset.mode;
}));

$('#c-input').addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  const msg = e.target.value.trim();
  if (!msg) return;
  e.target.value = '';
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
