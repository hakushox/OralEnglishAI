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
  $('#p-recent-list').innerHTML = '';
  $('#p-recent').classList.remove('open');
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
  $('#p-recent-list').innerHTML = '';
  $('#p-recent').classList.remove('open');
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
    $('#p-recent-list').innerHTML = '';        // 记录变了，下次展开重新取
    $('#p-recent').classList.remove('open');
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
$('#p-recent').addEventListener('click', async (e) => {
  const box = $('#p-recent-list');
  if (box.innerHTML) {                       // 再点一次收起
    box.innerHTML = '';
    e.target.classList.remove('open');
    return;
  }
  e.target.classList.add('open');
  box.innerHTML = '<div class="hint">读取中…</div>';
  const items = await (await fetch('/api/archive?filter=draft')).json();
  if (!items.length) { box.innerHTML = '<div class="hint">还没有记录</div>'; return; }
  renderCards(items.slice(0, 3), box, () => { box.innerHTML = ''; $('#p-recent').click(); });
  box.insertAdjacentHTML('beforeend',
    '<div class="hint" style="margin-top:6px">以上是最近 3 条，更多在「档案」页</div>');
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

let deckIndex = 0;

async function loadWordBook() {
  const deck = $('#w-deck');
  deck.innerHTML = '<div class="hint" style="padding:10px 2px">读取中…</div>';
  const list = await (await fetch('/api/words')).json();
  $('#w-pager').hidden = !list.length;
  $('#w-foot').hidden = !list.length;
  if (!list.length) {
    deck.innerHTML = '<div class="hint" style="padding:10px 2px">生词本还是空的，查个词存进来吧</div>';
    return;
  }
  deckIndex = 0;

  deck.innerHTML = list.map((w) => `
    <div class="wslide" data-word="${esc(w.word)}" data-id="${w.id}">
      <div class="wbig">
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
        <div class="wbig-detail">
          <div class="wbig-detail-inner">
            <div class="card md">${mdToHtml(w.usage || '（这个词还没有笔记）')}</div>
            <div class="row" style="margin-top:12px">
              <button class="pill acc" data-act="review">追问这个词</button>
              <button class="pill" data-act="test">出题测一测</button>
              <button class="pill" data-act="del"
                      style="margin-left:auto;background:#5a2523;color:#f0c9c6">删除</button>
            </div>
          </div>
        </div>
      </div>
    </div>`).join('');

  const slides = $$('.wslide', deck);
  const dotBox = $('#w-dots');       // 别叫 dots：外层有同名的熟练度渲染函数
  dotBox.innerHTML = list.map(() => '<i></i>').join('');

  /* 按「离中心的距离」摆位：中间原尺寸，两侧逐级缩小、压到后面、淡出。
     容器高度跟着当前那张走（展开详情时会变高），所以每次摆位后重新量一次。 */
  function layout() {
    slides.forEach((sl, i) => {
      const d = i - deckIndex;
      const ad = Math.abs(d);
      // 衰减要温和：参考的 coverflow 里侧卡是清楚可见的，不是快消失的影子
      const scale = Math.max(0.78, 1 - ad * 0.1);
      const shift = d * 47;                    // % of card width，产生重叠
      sl.style.transform = `translateX(-50%) translateX(${shift}%) scale(${scale})`;
      sl.style.opacity = ad > 2 ? 0 : String(Math.max(0, 1 - ad * 0.22));
      sl.style.zIndex = String(50 - ad);
      sl.style.pointerEvents = ad > 2 ? 'none' : 'auto';
      sl.classList.toggle('active', d === 0);
      if (d !== 0) sl.classList.remove('up');  // 翻走的那张自动收起
    });
    $('#w-pos').textContent = `${deckIndex + 1} / ${list.length}`;
    $$('i', dotBox).forEach((d, k) => d.classList.toggle('on', k === deckIndex));
    $('#w-prev').disabled = deckIndex <= 0;
    $('#w-next-card').disabled = deckIndex >= list.length - 1;
    fitHeight();
  }

  function fitHeight() {
    const cur = slides[deckIndex];
    if (!cur) return;
    // 卡片被 scale 过，offsetHeight 是缩放前的值，正好是我们要的布局高度
    deck.style.height = cur.querySelector('.wbig').offsetHeight + 16 + 'px';
  }

  const go = (k) => {
    deckIndex = Math.max(0, Math.min(list.length - 1, k));
    layout();
  };

  slides.forEach((slide, i) => {
    $('.wbig', slide).addEventListener('click', (e) => {
      if (e.target.closest('[data-act]')) return;
      if (i !== deckIndex) { go(i); return; }        // 点两侧的卡片 = 翻到它
      slide.classList.toggle('up');                  // 点中间那张 = 往上提拉展开
      setTimeout(fitHeight, 30);                     // 等 max-height 开始过渡再量
      setTimeout(fitHeight, 430);
    });

    const word = slide.dataset.word;
    $('[data-act=review]', slide).addEventListener('click', () => showSavedWord(word));
    $('[data-act=test]', slide).addEventListener('click', (e) => {
      const b = e.target, old = b.textContent;
      b.textContent = '出题还没接上';
      b.disabled = true;
      setTimeout(() => { b.textContent = old; b.disabled = false; }, 2000);
    });
    // 删除藏在展开后的动作里 —— 必须先点开看清是哪个词才能删，天然的一道闸
    $('[data-act=del]', slide).addEventListener('click', async () => {
      const r = await post('/api/archive/delete',
        { kind: 'word', id: Number(slide.dataset.id) });
      if (!r.ok) { toast(r.msg || '删除失败'); return; }
      toast(`已删除「${word}」`, '撤销', async () => {
        const u = await post('/api/archive/undo', {});
        if (u.ok) { await loadWordBook(); refreshWordCount(); }
        else toast(u.msg || '撤销失败');
      });
      await loadWordBook();
      refreshWordCount();
    });
  });

  $('#w-prev').onclick = () => go(deckIndex - 1);
  $('#w-next-card').onclick = () => go(deckIndex + 1);
  $$('i', dotBox).forEach((d, k) => d.addEventListener('click', () => go(k)));

  /* 横滑翻页：卡片是绝对定位的，没有原生滚动可用，所以自己处理 pointer 拖动。
     拖动中实时跟手（整组跟着位移），松手按距离决定翻不翻。 */
  let dragX = null, dragged = 0;
  deck.onpointerdown = (e) => {
    if (e.target.closest('[data-act]')) return;
    dragX = e.clientX; dragged = 0;
    slides.forEach((sl) => { sl.style.transition = 'none'; });
  };
  deck.onpointermove = (e) => {
    if (dragX === null) return;
    dragged = e.clientX - dragX;
    const w = deck.clientWidth || 1;
    slides.forEach((sl, i) => {
      const d = i - deckIndex - (-dragged / w) * 1.6;   // 跟手，但阻尼一下
      const ad = Math.abs(d);
      sl.style.transform =
        `translateX(-50%) translateX(${d * 47}%) scale(${Math.max(0.78, 1 - ad * 0.1)})`;
      sl.style.opacity = ad > 2.4 ? 0 : String(Math.max(0, 1 - ad * 0.22));
      sl.style.zIndex = String(50 - Math.round(ad));
    });
  };
  const dragEnd = () => {
    if (dragX === null) return;
    dragX = null;
    slides.forEach((sl) => { sl.style.transition = ''; });
    if (dragged < -40) go(deckIndex + 1);
    else if (dragged > 40) go(deckIndex - 1);
    else layout();
    dragged = 0;
  };
  deck.onpointerup = dragEnd;
  deck.onpointercancel = dragEnd;
  deck.onpointerleave = dragEnd;

  // 键盘左右翻页：只在单词页、抽屉开着、焦点不在输入框时生效
  document.onkeydown = (e) => {
    if (!$('#v-word').classList.contains('on') || !$('#w-deck').querySelector('.wslide')) return;
    if (/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); go(deckIndex - 1); }
    if (e.key === 'ArrowRight') { e.preventDefault(); go(deckIndex + 1); }
  };

  layout();
  setTimeout(fitHeight, 60);      // 字体/markdown 渲染完再量一次，高度才准
}

function closeWordBook() {
  $('#w-deck').innerHTML = '';
  $('#w-pager').hidden = true;
  $('#w-foot').hidden = true;
  $('#w-book').classList.remove('open');
}

$('#w-book').addEventListener('click', (e) => {
  if ($('#w-deck').innerHTML) { closeWordBook(); return; }
  e.currentTarget.classList.add('open');
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
  $('#w-count').textContent = list.length ? ` (${list.length})` : '（空）';
}

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
