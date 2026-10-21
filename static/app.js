/* ResumeMailer · 简历投递助手 — 前端逻辑 */
(function () {
'use strict';

// ── 状态 ──
let config = {};
let recipients = [];
let attachments = [];        // {name, path, size, on}
let currentJob = null;
let pollTimer = null;
let lastPreview = null;
let saveRecipientsTimer = null;
let bodyChatHistory = [];
const TOKEN_KEY = 'resumemailer_token';

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

function toast(msg, type = 'info', ms = 3200) {
  const el = $('toast');
  el.textContent = msg;
  el.className = `toast ${type} show`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), ms);
}

function fmtSize(n) {
  if (!n) return '';
  return n > 1024 * 1024 ? (n / 1024 / 1024).toFixed(1) + ' MB' : Math.round(n / 1024) + ' KB';
}

// ── API ──
async function api(method, url, body, retried) {
  const opts = { method, headers: {} };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) opts.headers['X-Token'] = token;
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  let data = {};
  try { data = await resp.json(); } catch (e) { /* 空响应 */ }
  if (resp.status === 401 && data.need_token && !retried) {
    const t = prompt('这个实例开启了访问口令（RESUMEMAILER_TOKEN），请输入：');
    if (t) { localStorage.setItem(TOKEN_KEY, t.trim()); return api(method, url, body, true); }
    throw new Error('需要访问口令');
  }
  if (!resp.ok && data.ok !== true) {
    throw new Error(data.error || data.msg || data.detail || `请求失败 (${resp.status})`);
  }
  return data;
}

function download(url) {
  const t = localStorage.getItem(TOKEN_KEY);
  location.href = t ? url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(t) : url;
}

// ── Tab ──
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    $('tab-' + tab.dataset.tab).classList.add('active');
    if (tab.dataset.tab === 'send') loadPreview();
    if (tab.dataset.tab === 'logs') { loadLogs(); loadContacts(); }
    if (tab.dataset.tab === 'guide') loadGuide();
  });
});

document.querySelectorAll('.sub-tabs').forEach(group => {
  group.addEventListener('click', e => {
    const btn = e.target.closest('.sub-tab');
    if (!btn) return;
    group.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    const section = btn.closest('.tab-content');
    section.querySelectorAll('.method-panel').forEach(p => p.classList.remove('active'));
    $('method-' + btn.dataset.method).classList.add('active');
  });
});

// ── 邮箱配置 ──
let PRESETS = {};

function applyEmailPreset(name) {
  const p = PRESETS[name];
  if (!p) { $('presetHint').textContent = ''; return; }
  $('smtpHost').value = p.smtp_host;
  $('smtpPort').value = p.smtp_port;
  $('imapHost').value = p.imap_host;
  $('imapPort').value = p.imap_port;
  $('useSsl').value = p.use_ssl ? 'true' : 'false';
  $('presetHint').textContent = p.daily_hint
    ? `该邮箱每日发信量参考上限约 ${p.daily_hint} 封，超过会被服务商拦截。`
    : '';
  if (!$('dailyLimitInput').value || $('dailyLimitInput').value === '0') {
    $('dailyLimitInput').value = p.daily_hint || 0;
  }
}

function initEmailPresets() {
  const sel = $('emailPreset');
  const names = Object.keys(PRESETS);
  // QQ 邮箱在国内求职场景最常用，放第一个；没有已保存配置时直接就选它
  sel.innerHTML = names.map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('')
    + '<option value="">手动填写</option>';
  sel.addEventListener('change', () => applyEmailPreset(sel.value));

  const saved = config.email && config.email.email;
  const pick = names.includes('QQ邮箱') ? 'QQ邮箱' : names[0];
  if (!saved) { sel.value = pick; applyEmailPreset(pick); }
}

function gatherEmailConfig() {
  return {
    email: $('emailAddr').value.trim(),
    smtp_host: $('smtpHost').value.trim(),
    smtp_port: parseInt($('smtpPort').value) || 465,
    imap_host: $('imapHost').value.trim(),
    imap_port: parseInt($('imapPort').value) || 993,
    use_ssl: $('useSsl').value === 'true',
    auth_code: $('authCode').value.trim(),
    sender_name: $('senderName').value.trim(),
  };
}

$('testConnBtn').addEventListener('click', async () => {
  const btn = $('testConnBtn');
  btn.disabled = true; btn.textContent = '测试中…';
  const box = $('testResult');
  box.className = 'test-result'; box.textContent = '';
  try {
    const res = await api('POST', '/api/email/test', gatherEmailConfig());
    box.textContent = res.msg; box.className = 'test-result success';
  } catch (e) {
    box.textContent = e.message; box.className = 'test-result error';
  }
  btn.disabled = false; btn.textContent = '测试连接';
});

$('saveEmailBtn').addEventListener('click', async () => {
  try {
    await api('POST', '/api/config/email', gatherEmailConfig());
    $('authCode').value = '';
    config = await api('GET', '/api/config');
    toast('邮箱配置已保存', 'success');
  } catch (e) { toast(e.message, 'error'); }
});

// ── 收件人 ──
function renderRecipients() {
  const wrap = $('recipientTableWrapper');
  wrap.style.display = recipients.length ? 'block' : 'none';
  $('recipientCount').textContent = recipients.length + ' 条';

  const varNames = new Set();
  recipients.forEach(r => Object.keys(r.vars || {}).forEach(k => varNames.add(k)));
  $('recipientVars').textContent = varNames.size ? '可用变量：' + [...varNames].map(v => `{${v}}`).join(' ') : '';

  const tbody = $('recipientTable').querySelector('tbody');
  tbody.innerHTML = '';
  recipients.forEach((r, i) => {
    const tr = document.createElement('tr');
    const chips = Object.entries(r.vars || {})
      .map(([k, v]) => `<span class="chip">${esc(k)}=${esc(v)}</span>`).join(' ');
    tr.innerHTML = `<td>${i + 1}</td>
      <td><input class="cell-input" data-i="${i}" data-k="company" value="${esc(r.company)}"></td>
      <td><input class="cell-input" data-i="${i}" data-k="email" value="${esc(r.email)}"></td>
      <td><input class="cell-input" data-i="${i}" data-k="subject" value="${esc(r.subject || '')}" placeholder="留空用主题模板"></td>
      <td class="chip-cell">${chips || '<span class="tip">—</span>'}</td>
      <td><button class="btn btn-secondary btn-xs" data-del="${i}">删除</button></td>`;
    tbody.appendChild(tr);
  });

  tbody.querySelectorAll('.cell-input').forEach(inp => {
    inp.addEventListener('input', () => {
      const i = +inp.dataset.i, k = inp.dataset.k;
      recipients[i][k] = inp.value;
      clearTimeout(saveRecipientsTimer);
      saveRecipientsTimer = setTimeout(saveRecipients, 600);
    });
  });
  tbody.querySelectorAll('[data-del]').forEach(btn => {
    btn.addEventListener('click', () => {
      recipients.splice(+btn.dataset.del, 1);
      renderRecipients(); saveRecipients();
    });
  });
  updateSendStats();
}

function saveRecipients() {
  api('POST', '/api/recipients/save', { recipients }).catch(() => {});
}

function showParseErrors(errors, warnings) {
  const box = $('parseErrors');
  const parts = [];
  (warnings || []).forEach(w =>parts.push(`<p class="warn-line">${esc(w)}</p>`));
  (errors || []).forEach(e =>parts.push(`<p>${esc(e)}</p>`));
  box.innerHTML = parts.slice(0, 40).join('');
  if (parts.length > 40) box.innerHTML += `<p>…还有 ${parts.length - 40} 条</p>`;
}

function splitEmailCell(raw) {
  return String(raw || '')
    .split(/[,;，；、]+/)
    .map(t => {
      const m = t.match(/<([^<>]+)>/);
      return (m ? m[1] : t).trim();
    })
    .filter(Boolean);
}

function applyRecipients(rows, opts) {
  const options = opts || {};
  // 一格多邮箱 → 拆成多行，别让两个 HR 出现在同一个 To 里
  const incoming = [];
  (rows || []).forEach(r => {
    const emails = splitEmailCell(r.email);
    (emails.length ? emails : ['']).forEach(em => {
      incoming.push({
        seq: incoming.length + 1, company: r.company || '', email: em,
        subject: r.subject || '', vars: r.vars || {},
      });
    });
  });
  const append = $('appendMode') && $('appendMode').checked && recipients.length > 0;
  if (!append) {
    if (options.confirmReplace && recipients.length) {
      const ok = confirm(`会用新导入的 ${incoming.length} 条替换当前的 ${recipients.length} 条。`
        + '\n要保留原名单，先勾选上面的「追加到现有名单」。继续替换？');
      if (!ok) return null;
    }
    recipients = incoming;
    return incoming.length;
  }
  const seen = new Set(recipients.map(r => (r.email || '').toLowerCase()).filter(Boolean));
  let added = 0;
  for (const r of incoming) {
    const key = (r.email || '').toLowerCase();
    if (key && seen.has(key)) continue;
    seen.add(key);
    recipients.push(Object.assign({}, r, { seq: recipients.length + 1 }));
    added += 1;
  }
  return added;
}

function applyParsed(res) {
  const added = applyRecipients(res.recipients, { confirmReplace: true });
  if (added === null) return;
  renderRecipients();
  showParseErrors(res.errors, res.warnings);
  toast($('appendMode').checked
    ? `新增 ${added} 条，当前共 ${recipients.length} 条`
    : `已加载 ${recipients.length} 位收件人`, 'success');
}

const excelZone = $('excelUploadZone');
excelZone.addEventListener('click', () => $('excelFileInput').click());
excelZone.addEventListener('dragover', e => { e.preventDefault(); excelZone.classList.add('dragover'); });
excelZone.addEventListener('dragleave', () => excelZone.classList.remove('dragover'));
excelZone.addEventListener('drop', e => {
  e.preventDefault(); excelZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) uploadTable(e.dataTransfer.files[0]);
});
$('excelFileInput').addEventListener('change', e => {
  if (e.target.files.length) uploadTable(e.target.files[0]);
});

async function uploadTable(file) {
  if (recipients.length && !confirm(`上传新表格会替换当前的 ${recipients.length} 条收件人，继续？`)) return;
  const fd = new FormData();
  fd.append('file', file);
  try {
    toast('解析中…', 'info', 1500);
    applyParsed(await api('POST', '/api/template/parse', fd));
  } catch (e) { toast(e.message, 'error'); }
}

$('pasteParseBtn').addEventListener('click', async () => {
  const text = $('pasteInput').value;
  if (!text.trim()) { toast('先粘贴点内容', 'error'); return; }
  try {
    applyParsed(await api('POST', '/api/recipients/parse-text', { text }));
  } catch (e) { toast(e.message, 'error'); }
});

// ── 截图 / 图片导入 ──
let pendingImages = [];

const imageZone = $('imageUploadZone');
imageZone.addEventListener('click', () => $('imageInput').click());
imageZone.addEventListener('dragover', e => { e.preventDefault(); imageZone.classList.add('dragover'); });
imageZone.addEventListener('dragleave', () => imageZone.classList.remove('dragover'));
imageZone.addEventListener('drop', e => {
  e.preventDefault(); imageZone.classList.remove('dragover');
  addImages(e.dataTransfer.files);
});
$('imageInput').addEventListener('change', e => addImages(e.target.files));

function addImages(fileList) {
  for (const f of fileList || []) {
    if (!f.type || !f.type.startsWith('image/')) continue;
    if (f.size > 8 * 1024 * 1024) { toast(`${f.name} 超过 8MB，先压缩`, 'error'); continue; }
    if (pendingImages.length >= 6) { toast('最多 6 张图，够用了', 'error'); break; }
    pendingImages.push(f);
  }
  renderImages();
}

function renderImages() {
  const box = $('imagePreview');
  box.innerHTML = pendingImages.map((f, i) => `
    <div class="image-thumb">
      <img src="${URL.createObjectURL(f)}" alt="${esc(f.name)}">
      <button class="thumb-del" data-delimg="${i}" title="移除">×</button>
    </div>`).join('');
  box.querySelectorAll('[data-delimg]').forEach(btn => {
    btn.addEventListener('click', () => {
      pendingImages.splice(+btn.dataset.delimg, 1);
      renderImages();
    });
  });
}

// 在收件人页直接 ⌘V / Ctrl+V 粘贴截图
document.addEventListener('paste', e => {
  const panel = $('tab-recipients');
  if (!panel || !panel.classList.contains('active')) return;
  const files = Array.from((e.clipboardData && e.clipboardData.files) || [])
    .filter(f => f.type && f.type.startsWith('image/'));
  if (files.length) { e.preventDefault(); addImages(files); }
});

$('imageParseBtn').addEventListener('click', async () => {
  if (!pendingImages.length) { toast('先拖一张截图进来', 'error'); return; }
  if (!aiConfigured()) {
    toast('先去「AI 设置」选一个会看图的模型、粘贴 Key', 'error', 6000);
    switchTab('ai'); return;
  }
  if (recipients.length && !confirm(`识别结果会替换当前的 ${recipients.length} 条收件人，继续？`)) return;

  const btn = $('imageParseBtn');
  btn.disabled = true; btn.textContent = '识别中…（大图要十几秒）';
  const fd = new FormData();
  pendingImages.forEach(f => fd.append('files', f));
  fd.append('hint', $('imageHint').value.trim());
  try {
    const res = await api('POST', '/api/ai/parse-images', fd);
    if (applyRecipients(res.recipients, { confirmReplace: true }) === null) {
      btn.disabled = false; btn.textContent = '识别截图里的收件人'; return;
    }
    renderRecipients();
    showParseErrors([], res.recipients.length ? [] : ['图里没有识别到收件人，换一张清晰点的，或补一句说明']);
    pendingImages = [];
    renderImages();
    $('imageHint').value = '';
    toast(`识别出 ${recipients.length} 条收件人`, 'success', 5000);
  } catch (e) {
    toast(e.message, 'error', 9000);
  }
  btn.disabled = false; btn.textContent = '识别截图里的收件人';
});

// ── AI 设置 ──
let aiState = { provider: "" };

function aiConfigured() {
  return !!(config.ai && config.ai.configured);
}

function renderAiStatus() {
  const a = config.ai || {};
  const line = aiConfigured()
    ? `当前 AI：<strong>${esc(a.provider)} · ${esc(a.model)}</strong>`
    : '还没配置 AI（只影响截图/文字提取，表格导入不需要它）';
  ['aiStatusRecipients', 'aiStatusBody'].forEach(id => {
    const el = $(id); if (!el) return;
    el.innerHTML = line + ' · <a href="#" data-goto-ai>去 AI 设置</a>';
  });
  const el = $('aiStatus');
  if (el) {
    el.innerHTML = aiConfigured()
      ? ` ${line}${a.api_key ? ' · Key 已保存' : ''}`
      : '未配置。选一个提供商、粘贴 Key，点「测试连接」确认可用。';
  }
  document.querySelectorAll('[data-goto-ai]').forEach(link => {
    link.addEventListener('click', e => { e.preventDefault(); switchTab('ai'); });
  });
}

function renderProviderCards() {
  const box = $('aiProviderCards');
  if (!box) return;
  box.innerHTML = (config.ai_providers || []).map(p => {
    const active = p.name === aiState.provider ? 'active' : '';
    const vision = (p.vision && p.vision.length)
      ? '<span class="pv-tag">支持看图</span>' : '';
    return `<div class="provider-card ${active}" data-provider="${esc(p.name)}">
      <div class="pv-name">${esc(p.name)}</div>${vision}</div>`;
  }).join('');
  box.querySelectorAll('[data-provider]').forEach(card => {
    card.addEventListener('click', () => selectProvider(card.dataset.provider));
  });
}

function selectProvider(name) {
  aiState.provider = name;
  const preset = (config.ai_providers || []).find(p => p.name === name) || {};
  const models = preset.models || [];
  const isCustom = name.indexOf('自定义') === 0;
  const sel = $('aiModelSelect');
  const custom = $('aiModelCustom');
  sel.innerHTML = models.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('')
    + '<option value="__custom__">其它模型（手动输入）</option>';
  const manual = isCustom || !models.length;
  sel.style.display = manual ? 'none' : 'block';
  custom.style.display = manual ? 'block' : 'none';
  sel.onchange = () => {
    const picked = sel.value === '__custom__';
    custom.style.display = picked ? 'block' : 'none';
    if (picked) custom.focus();
  };
  $('aiBaseUrlGroup').style.display = isCustom ? 'block' : 'none';

  const link = $('aiDocsLink');
  if (preset.docs) { link.href = preset.docs; link.style.display = 'inline-block'; }
  else { link.style.display = 'none'; }

  $('aiVisionHint').textContent = (preset.vision && preset.vision.length)
    ? `图片识别用：${preset.vision.join(' / ')}` : '';
  $('aiTestResult').style.display = 'none';
  renderProviderCards();
}

function currentAiForm() {
  const provider = aiState.provider;
  const sel = $('aiModelSelect');
  const manual = sel.style.display === 'none' || sel.value === '__custom__';
  return {
    provider,
    model: manual ? $('aiModelCustom').value.trim() : sel.value,
    api_key: $('aiKeyInput').value.trim(),
    base_url: provider.indexOf('自定义') === 0 ? $('aiBaseUrlInput').value.trim() : '',
  };
}

function fillAiFormFromConfig() {
  const a = config.ai || {};
  renderProviderCards();
  if (a.provider) {
    selectProvider(a.provider);
  } else {
    const first = (config.ai_providers || [])[0];
    if (first) selectProvider(first.name);
    else { aiState.provider = ""; renderProviderCards(); }
  }
  if (a.model) {
    const sel = $('aiModelSelect');
    const manual = sel.style.display === 'none';
    if (manual) {
      $('aiModelCustom').value = a.model;
    } else {
      // 存过但不在预设列表里的模型名，也要能显示出来
      if (![...sel.options].some(o => o.value === a.model)) {
        sel.insertAdjacentHTML('beforeend',
          `<option value="${esc(a.model)}">${esc(a.model)}</option>`);
      }
      sel.value = a.model;
    }
  }
  $('aiBaseUrlInput').value = a.base_url || '';
  $('aiKeyInput').value = '';
  $('aiKeyInput').placeholder = a.api_key ? '已保存（留空则沿用）' : '粘贴 API Key';
  renderAiStatus();
}

$('saveAiBtn').addEventListener('click', async () => {
  const f = currentAiForm();
  if (!f.provider) { toast('先选一个提供商', 'error'); return; }
  if (!f.model) { toast('模型不能为空', 'error'); return; }
  if (f.provider.indexOf('自定义') === 0 && !f.base_url) { toast('自定义提供商要填 Base URL', 'error'); return; }
  try {
    await api('POST', '/api/config/ai', f);
    config = await api('GET', '/api/config');
    $('aiKeyInput').value = '';
    $('aiKeyInput').placeholder = config.ai.api_key ? '已保存（留空则沿用）' : '粘贴 API Key';
    renderAiStatus();
    toast('AI 配置已保存', 'success');
  } catch (e) { toast(e.message, 'error'); }
});

$('testAiBtn').addEventListener('click', async () => {
  const f = currentAiForm();
  if (!f.provider || !f.model) { toast('先选提供商和模型', 'error'); return; }
  const btn = $('testAiBtn');
  btn.disabled = true; btn.textContent = '测试中…';
  const box = $('aiTestResult');
  box.style.display = 'block'; box.className = 'test-result'; box.textContent = '正在让模型回一句话…';
  try {
    const r = await api('POST', '/api/ai/test', f);
    box.className = 'test-result success';
    box.textContent = `连接成功：${r.provider} · ${r.model}，${r.latency_ms} ms，模型回复「${r.reply}」`;
    await api('POST', '/api/config/ai', f);
    config = await api('GET', '/api/config');
    $('aiKeyInput').value = '';
    $('aiKeyInput').placeholder = '已保存（留空则沿用）';
    renderAiStatus();
  } catch (e) {
    box.className = 'test-result error';
    box.textContent = e.message;
  }
  btn.disabled = false; btn.textContent = '测试连接';
});

$('aiFillBtn').addEventListener('click', async () => {
  const input = $('aiInput').value.trim();
  if (!input) { toast('先粘贴公司信息', 'error'); return; }
  if (recipients.length && !confirm(`AI 提取会替换当前的 ${recipients.length} 条收件人，继续？`)) return;
  if (!aiConfigured()) {
    toast('先去「AI 设置」选提供商、粘贴 Key', 'error', 6000);
    switchTab('ai'); return;
  }
  const btn = $('aiFillBtn');
  btn.disabled = true; btn.textContent = 'AI 分析中…';
  try {
    const res = await api('POST', '/api/ai/fill-template', { input });
    if (applyRecipients(res.recipients, { confirmReplace: true }) === null) {
      btn.disabled = false; btn.textContent = 'AI 自动填充'; return;
    }
    renderRecipients();
    showParseErrors([], res.recipients.length ? [] : ['AI 没有提取到收件人，检查一下输入内容']);
    toast(`AI 提取了 ${recipients.length} 条`, 'success');
  } catch (e) { toast(e.message, 'error', 6000); }
  btn.disabled = false; btn.textContent = 'AI 自动填充';
});

// ── 正文 ──
function gatherUser() {
  return {
    '姓名': $('userName').value.trim(), '学校': $('userSchool').value.trim(),
    '专业': $('userMajor').value.trim(), '年级': $('userGrade').value.trim(),
    '电话': $('userPhone').value.trim(), '邮箱': $('userEmail').value.trim(),
  };
}

$('saveUserInfoBtn').addEventListener('click', async () => {
  try {
    const u = gatherUser();
    await api('POST', '/api/config/user', {
      name: u['姓名'], school: u['学校'], major: u['专业'],
      grade: u['年级'], phone: u['电话'], email: u['邮箱'],
    });
    config.user = { name: u['姓名'], school: u['学校'], major: u['专业'],
                    grade: u['年级'], phone: u['电话'], email: u['邮箱'] };
    updateVarHint();
    toast('个人信息已保存', 'success');
  } catch (e) { toast(e.message, 'error'); }
});

$('saveBodyBtn').addEventListener('click', async () => {
  try {
    await api('POST', '/api/config/settings', {
      body_template: $('bodyEditor').value,
      subject_template: $('subjectEditor').value,
    });
    toast('正文与主题已保存', 'success');
  } catch (e) { toast(e.message, 'error'); }
});

function updateVarHint() {
  const names = new Set();
  recipients.forEach(r => Object.keys(r.vars || {}).forEach(k => names.add(k)));
  $('varHint').innerHTML = names.size
    ? '表格里的自定义列：' + [...names].map(v => `<code>{${esc(v)}}</code>`).join(' ')
    : '在表格里加一列「岗位」，正文就能写 {岗位}。';
}

$('bodyChatSend').addEventListener('click', sendBodyChat);
$('bodyChatInput').addEventListener('keydown', e => {
  // 中文输入法选词时的回车不能当成发送
  if (e.key === 'Enter' && !e.isComposing) sendBodyChat();
});

function appendChatMsg(text, role) {
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  $('bodyChatMsgs').appendChild(div);
  $('bodyChatMsgs').scrollTop = $('bodyChatMsgs').scrollHeight;
  return div;
}

async function sendBodyChat() {
  const input = $('bodyChatInput');
  const msg = input.value.trim();
  if (!msg) return;
  if (!aiConfigured()) {
    toast('先去「AI 设置」选提供商、粘贴 Key', 'error', 6000);
    switchTab('ai'); return;
  }
  input.value = '';
  appendChatMsg(msg, 'user');
  bodyChatHistory.push({ role: 'user', content: msg });
  const loading = appendChatMsg('思考中…', 'assistant');
  try {
    const system = '你是求职邮件写作助手。输出可直接使用的纯文本正文，不要 Markdown，不要解释，保留 {姓名} {学校} {公司名} {岗位} 这类占位符。';
    const res = await api('POST', '/api/ai/chat', {
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: `当前正文：\n${$('bodyEditor').value}` },
      ].concat(bodyChatHistory.slice(-8)),
    });
    loading.remove();
    bodyChatHistory.push({ role: 'assistant', content: res.content });
    appendChatMsg(res.content, 'assistant');
    const useBtn = document.createElement('button');
    useBtn.className = 'btn btn-warning btn-xs';
    useBtn.style.margin = '4px 0 10px';
    useBtn.textContent = '使用此正文';
    useBtn.addEventListener('click', () => {
      $('bodyEditor').value = res.content;
      toast('已填入编辑框，记得点「保存正文与主题」', 'success');
    });
    $('bodyChatMsgs').appendChild(useBtn);
  } catch (e) {
    loading.remove();
    appendChatMsg('错误：' + e.message, 'error');
  }
}

// ── 附件 ──
const attachZone = $('attachUploadZone');
attachZone.addEventListener('click', () => $('attachFileInput').click());
attachZone.addEventListener('dragover', e => { e.preventDefault(); attachZone.classList.add('dragover'); });
attachZone.addEventListener('dragleave', () => attachZone.classList.remove('dragover'));
attachZone.addEventListener('drop', e => {
  e.preventDefault(); attachZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) uploadAttachments(e.dataTransfer.files);
});
$('attachFileInput').addEventListener('change', e => {
  if (e.target.files.length) uploadAttachments(e.target.files);
});

async function uploadAttachments(files) {
  const uploaded = [];
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await api('POST', '/api/attachments/upload', fd);
      uploaded.push(res.file.path);
    } catch (e) { toast(`${file.name}: ${e.message}`, 'error', 6000); }
  }
  await loadAttachments(uploaded);
  if (uploaded.length) toast('附件已上传，记得在发送页勾选', 'success');
}

async function loadAttachments(newPaths) {
  let res;
  try { res = await api('GET', '/api/attachments'); } catch (e) { return; }
  const keep = new Set(attachments.filter(a => a.on).map(a => a.path));
  (newPaths || []).forEach(p => keep.add(p));
  const chosen = new Set(config.last_attachments || []);
  attachments = (res.files || []).map(f => ({
    name: f.name, path: f.path, size: f.size,
    on: keep.size ? keep.has(f.path) : chosen.has(f.path),
  }));
  renderAttachments();
}

function renderAttachments() {
  const list = $('attachList');
  if (!attachments.length) {
    list.innerHTML = '<p class="tip">暂无附件。没有简历就发出去等于白发。</p>';
    updateSendStats();
    return;
  }
  list.innerHTML = attachments.map((f, i) => `
    <div class="file-item">
      <label class="file-check">
        <input type="checkbox" data-att="${i}" ${f.on ? 'checked' : ''}>
        <span class="file-name">${esc(f.name)}</span>
        <span class="tip">${fmtSize(f.size)}</span>
      </label>
      <span class="file-del" data-delatt="${i}">删除</span>
    </div>`).join('');
  list.querySelectorAll('[data-att]').forEach(cb => {
    cb.addEventListener('change', () => {
      attachments[+cb.dataset.att].on = cb.checked;
      updateSendStats();
    });
  });
  list.querySelectorAll('[data-delatt]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const f = attachments[+btn.dataset.delatt];
      try {
        await api('DELETE', '/api/attachments/' + encodeURIComponent(f.name));
        await loadAttachments(false);
      } catch (e) { toast(e.message, 'error'); }
    });
  });
  updateSendStats();
}

function selectedAttachments() {
  return attachments.filter(a => a.on);
}

function updateSendStats() {
  $('sendTotal').textContent = recipients.length;
  $('sendAttachCount').textContent = selectedAttachments().length;
}

// ── 预览 / 预检 ──
async function loadPreview() {
  updateSendStats();
  if (!recipients.length) {
    $('sendPreview').innerHTML = '<p class="tip">还没有收件人。先去「收件人」页导入表格。</p>';
    $('preflight').innerHTML = '';
    return;
  }
  $('sendPreview').innerHTML = '<p class="tip">渲染中…</p>';
  try {
    lastPreview = await api('POST', '/api/preview', {
      recipients,
      body: $('bodyEditor').value,
      subject: $('subjectEditor').value,
      user: gatherUser(),
      limit: 3,
    });
    renderPreflight(lastPreview);
    renderPreviewCards(lastPreview);
    if (lastPreview.today) $('todaySent').textContent = lastPreview.today.sent;
  } catch (e) {
    $('sendPreview').innerHTML = `<p class="tip">预览失败：${esc(e.message)}</p>`;
  }
}

function renderPreflight(p) {
  const box = $('preflight');
  const items = [];
  const remaining = p.today.limit ? Math.max(0, p.today.limit - p.today.sent) : Infinity;

  if (p.unknown_variables.length) {
    items.push(['error', `正文/主题里有未识别的变量：${p.unknown_variables.map(v => '{' + v + '}').join(' ')}。它们会原样发出去。`]);
  }
  if (p.empty_variables && p.empty_variables.length) {
    items.push(['error', `这些变量当前是空的：${p.empty_variables.map(v => '{' + v + '}').join(' ')}。去「正文」页补齐，否则主题会出现「实习申请--行研」这种空洞。`]);
  }
  if (p.today.limit && p.total > remaining) {
    items.push(['error', `今日还可发 ${remaining} 封，本批 ${p.total} 封，超出部分会被跳过。`]);
  }
  if (p.invalid_address_count) {
    const names = (p.invalid_addresses || []).slice(0, 3)
      .map(x => `${x.company || '—'}（${x.reason}）`).join('、');
    items.push(['error', `${p.invalid_address_count} 行邮箱有问题，这些行不会发送：${names}${p.invalid_address_count > 3 ? '…' : ''}`]);
  }
  if (p.dead_address_count) {
    const names = p.dead_addresses.slice(0, 3).map(x => x.company || x.email).join('、');
    items.push(['warn', `${p.dead_address_count} 个地址之前退信过（${names}${p.dead_address_count > 3 ? '…' : ''}），发送时会自动跳过。要强制重试，去「投递记录」勾选「忽略退信记录」。`]);
  }
  const contactedCount = p.already_contacted_count || p.already_contacted.length;
  if (contactedCount) {
    const names = p.already_contacted.slice(0, 5).map(x => `${x.company || x.email}`).join('、');
    items.push(['warn', `${contactedCount} 个邮箱之前已成功投过（${names}${contactedCount > 5 ? '…' : ''}）。勾选下方「跳过已投递」可避免重复打扰。`]);
  }
  if (p.duplicates_in_batch.length) {
    items.push(['warn', `批内有 ${p.duplicates_in_batch.length} 个重复邮箱。`]);
  }
  if (p.missing_company.length) {
    items.push(['warn', `${p.missing_company.length} 行没有公司名，{公司名} 会是空白。`]);
  }
  const chosenAtt = selectedAttachments();
  const attMb = chosenAtt.reduce((s, a) => s + (a.size || 0), 0) / 1024 / 1024;
  if (!chosenAtt.length) {
    items.push(['warn', '当前没有勾选任何附件——投简历却忘了附简历是最常见的翻车。']);
  } else if (attMb > 20) {
    items.push(['warn', `附件共 ${attMb.toFixed(1)}MB，接近多数邮箱 25MB 上限（base64 后还会膨胀约 33%）。`]);
  }
  const secs = Math.ceil(p.total * 60 / (parseInt($('rateInput').value) || 20));
  const dur = secs >= 60 ? `${Math.ceil(secs / 60)} 分钟` : `${secs} 秒`;
  items.push(['info', `今日已发 ${p.today.sent} 封${p.today.limit ? ' / 上限 ' + p.today.limit : ''}。整批约需 ${dur}。`]);

  const klass = { error: 'pre-error', warn: 'pre-warn', info: 'pre-info' };
  const skipBox = contactedCount
    ? `<label class="checkbox-label" style="margin-top:8px;">
         <input type="checkbox" id="skipSent" checked>
         跳过已投递过的邮箱（${contactedCount} 个）
       </label>`
    : '<input type="checkbox" id="skipSent" hidden>';
  box.innerHTML = items.map(([k, t]) => `<div class="pre-line ${klass[k]}">${esc(t)}</div>`).join('') + skipBox;
}

function renderPreviewCards(p) {
  const cards = p.items.map(it => `
    <div class="preview-card${it.error ? ' preview-bad' : ''}">
      <div class="preview-subject">${esc(it.subject || '(无主题)')}</div>
      <div class="preview-to">${esc(it.company || '—')} &lt;${esc(it.email)}&gt;</div>
      ${it.error ? `<div class="preview-error">这行不会发出去：${esc(it.error)}</div>` : ''}
      <div class="preview-body">${esc(it.body)}</div>
    </div>`).join('');
  $('sendPreview').innerHTML = cards +
    (p.total > p.items.length ? `<p class="tip">仅预览前 ${p.items.length} 封，共 ${p.total} 封。</p>` : '');
}

$('rateInput').addEventListener('change', updateSendStats);

$('saveSettingsBtn').addEventListener('click', async () => {
  try {
    await api('POST', '/api/config/settings', {
      send_rate: parseInt($('rateInput').value) || 20,
      daily_limit: parseInt($('dailyLimitInput').value) || 0,
      cc_self: $('ccSelf').checked,
    });
    $('dailyInfo').textContent = (parseInt($('dailyLimitInput').value) || 0) || '不限';
    toast('发送设置已保存', 'success');
  } catch (e) { toast(e.message, 'error'); }
});

// ── 测试发给自己 ──
$('testBtn').addEventListener('click', async () => {
  if (!config.email || !config.email.email) { toast('先配置邮箱', 'error'); return; }
  const btn = $('testBtn');
  btn.disabled = true; btn.textContent = '发送中…';
  try {
    const res = await api('POST', '/api/send/test', {
      recipients, body: $('bodyEditor').value, subject: $('subjectEditor').value,
      user: gatherUser(), attachments: selectedAttachments().map(a => a.path),
    });
    toast(res.msg, 'success', 6000);
  } catch (e) { toast(e.message, 'error', 8000); }
  btn.disabled = false; btn.textContent = '先发给自己';
});

// ── 发送 ──
$('draftBtn').addEventListener('click', () => {
  if (!guardSend()) return;
  if (!confirm(`把 ${sendList().length} 封邮件存进草稿箱？（不会直接发出）`)) return;
  startSending('draft');
});

$('sendBtn').addEventListener('click', () => {
  if (!guardSend()) return;
  $('warningInput').value = '';
  $('warningConfirm').disabled = true;
  $('sendWarning').style.display = 'flex';
});

$('warningInput').addEventListener('input', () => {
  $('warningConfirm').disabled = $('warningInput').value.trim() !== '确认发送';
});
$('warningCancel').addEventListener('click', () => { $('sendWarning').style.display = 'none'; });
$('warningConfirm').addEventListener('click', () => {
  $('sendWarning').style.display = 'none';
  startSending('send');
});

function guardSend() {
  if (!recipients.length) { toast('收件人为空', 'error'); return false; }
  if (!config.email || !config.email.email) { toast('先配置邮箱', 'error'); return false; }
  return true;
}

function sendList() {
  const skip = $('skipSent') && $('skipSent').checked;
  const contacted = new Set((lastPreview && lastPreview.already_contacted || []).map(x => x.email));
  const list = skip ? recipients.filter(r => !contacted.has(String(r.email).toLowerCase())) : recipients.slice();
  return list;
}

async function startSending(mode) {
  const list = sendList();
  if (!list.length) { toast('没有需要发的收件人', 'error'); return; }
  $('draftBtn').disabled = true;
  $('sendBtn').disabled = true;
  $('testBtn').disabled = true;
  $('sendResult').style.display = 'none';
  $('sendProgress').style.display = 'block';
  $('progressLog').innerHTML = '';
  $('progressFill').style.width = '0%';
  $('progressText').textContent = '准备中…';
  $('cancelBtn').style.display = 'none';

  try {
    const res = await api('POST', '/api/send/start', {
      recipients: list,
      body: $('bodyEditor').value,
      subject: $('subjectEditor').value,
      attachments: selectedAttachments().map(a => a.path),
      send_mode: mode,
      rate: parseInt($('rateInput').value) || 20,
      daily_limit: parseInt($('dailyLimitInput').value) || 0,
      cc_self: $('ccSelf').checked,
      include_dead: !!($('includeDead') && $('includeDead').checked),
    });
    currentJob = res.job_id;
    if (res.dead_skipped) toast(`已自动跳过 ${res.dead_skipped} 个退信地址`, 'info', 6000);
    $('cancelBtn').style.display = 'inline-block';
    $('progressText').textContent = `0 / ${res.total}`;
    pollJob();
  } catch (e) {
    finishUI();
    $('progressText').textContent = '启动失败：' + e.message;
  }
}

async function pollJob() {
  if (!currentJob) return;
  let st;
  try {
    st = await api('GET', '/api/send/status/' + currentJob);
  } catch (e) {
    $('progressText').textContent = '查询进度失败：' + e.message;
    finishUI();
    return;
  }
  const pct = st.total ? Math.round(st.done / st.total * 100) : 0;
  $('progressFill').style.width = pct + '%';
  $('progressText').textContent = `${st.done} / ${st.total}（成功 ${st.success}，失败 ${st.failed}）`;
  $('progressLog').innerHTML = st.results.slice(-12).map(r => {
    const label = r.status === 'sent' ? '已发送' : r.status === 'draft' ? '存草稿'
      : r.status === 'dry' ? '试跑' : r.status === 'skipped' ? '跳过' : '失败';
    return `<p class="${r.success ? 'success' : 'error'}"><span class="status-dot ${esc(r.status)}"></span>`
      + `<span class="log-label">${label}</span> ${esc(r.company || r.email)}`
      + `${r.error ? ' — ' + esc(r.error) : ''}</p>`;
  }).join('');
  $('progressLog').scrollTop = $('progressLog').scrollHeight;

  if (st.status === 'running') {
    pollTimer = setTimeout(pollJob, 900);
    return;
  }
  currentJob = null;
  $('cancelBtn').style.display = 'none';
  finishUI();
  renderResults(st);
  if (st.mode === 'draft' && st.success) {
    toast(`已存入草稿箱：${st.draft_box || 'Drafts'}`, 'info', 6000);
  }
  if (st.status === 'error') toast('批次异常：' + st.error, 'error', 8000);
  else if (st.mode === 'dry') toast('试跑完成，没有真的发出', 'info', 5000);
  else if (st.stopped) toast(st.stopped, 'info', 7000);
  else toast('批次完成', 'success');
}

$('cancelBtn').addEventListener('click', async () => {
  if (!currentJob) return;
  try {
    await api('POST', '/api/send/cancel/' + currentJob);
    $('cancelBtn').disabled = true;
    $('progressText').textContent += ' — 已请求停止，当前这封发完即停';
  } catch (e) { toast(e.message, 'error'); }
});

function finishUI() {
  $('draftBtn').disabled = false;
  $('sendBtn').disabled = false;
  $('testBtn').disabled = false;
  $('cancelBtn').disabled = false;
}

function renderResults(st) {
  $('sendResult').style.display = 'block';
  const summary = $('resultSummary');
  const totalDone = st.success + st.failed + st.skipped;
  if (st.mode === 'dry') {
    summary.textContent = `试跑完成：${st.success} 封已完整组装（正文、主题、附件），但没有真的发出`;
    summary.style.background = '#eef3fa'; summary.style.color = '#1A4B8C';
  } else if (st.failed === 0 && st.skipped === 0) {
    summary.textContent = `全部成功：${st.success} 封${st.mode === 'send' ? '已发送' : '已存入草稿箱'}`;
    summary.style.background = '#e8f5e9'; summary.style.color = '#2e7d32';
  } else {
    summary.textContent = `成功 ${st.success} · 失败 ${st.failed} · 跳过 ${st.skipped}（共 ${totalDone}）${st.stopped ? ' — ' + st.stopped : ''}`;
    summary.style.background = st.success ? '#fff3e0' : '#fbe9e7';
    summary.style.color = st.success ? '#b45309' : '#b3261e';
  }
  if (st.failed && st.mode !== 'dry') {
    summary.textContent += ' — 修好原因后回本页重跑，勾选「跳过已投递」就只会补发失败的。';
  }
  const tbody = $('resultTable').querySelector('tbody');
  tbody.innerHTML = (st.results || []).map(r => {
    const icon = r.status === 'sent' ? '已发送' : r.status === 'draft' ? '存草稿'
      : r.status === 'dry' ? '试跑' : r.status === 'skipped' ? '跳过' : '失败';
    return `<tr><td>${esc(r.company)}</td><td>${esc(r.email)}</td><td>${esc(r.subject)}</td>
      <td>${icon}</td><td style="color:${r.success ? '#888' : '#b3261e'}">${esc(r.error || '-')}</td></tr>`;
  }).join('');
  loadPreview();
}

$('exportBtn').addEventListener('click', () => download('/api/report/export'));

// ── 日志 ──
async function loadLogs() {
  try {
    const res = await api('GET', '/api/logs');
    const tbody = $('logTable').querySelector('tbody');
    tbody.innerHTML = (res.logs || []).slice().reverse().map(log => {
      const time = log.time ? new Date(log.time).toLocaleString('zh-CN', { hour12: false }) : '-';
      return `<tr><td>${esc(time)}</td><td>${esc(log.company)}</td><td>${esc(log.email)}</td>
        <td>${esc(log.subject || '')}</td>
        <td>${log.mode === 'send' ? '发送' : '存草稿'}</td>
        <td style="color:${log.success ? '#2e7d32' : '#b3261e'}">${log.success ? '成功' : '失败'}</td>
        <td style="color:${log.success ? '#888' : '#b3261e'}">${esc(log.error || '-')}</td></tr>`;
    }).join('');
  } catch (e) { toast(e.message, 'error'); }
}
$('refreshLogsBtn').addEventListener('click', loadLogs);
$('exportLogsBtn').addEventListener('click', () => download('/api/report/export'));
$('clearLogsBtn').addEventListener('click', async () => {
  if (!confirm('清空所有发送日志？导出过就别清了。')) return;
  await api('DELETE', '/api/logs');
  loadLogs();
  toast('日志已清空', 'success');
});

// ── 投递记录 / 收件箱扫描 ──
function fmtTime(s) {
  if (!s) return '—';
  const d = new Date(s);
  return isNaN(d.getTime()) ? String(s) : d.toLocaleString('zh-CN', { hour12: false });
}

async function loadContacts() {
  let data;
  try { data = await api('GET', '/api/contacts'); } catch (e) { return; }
  $('statSent').textContent = data.counts.sent || 0;
  $('statReplied').textContent = data.counts.replied || 0;
  $('statBounced').textContent = data.counts.bounced || 0;

  const tbody = $('contactTable').querySelector('tbody');
  const rows = (data.contacts || []).map(c => {
    const label = c.status === 'replied' ? '已回复'
      : c.status === 'bounced' ? '退信' : '已投递';
    const color = c.status === 'bounced' ? '#b3261e'
      : c.status === 'replied' ? '#2e7d32' : '#5a6b80';
    return `<tr><td>${esc(c.company || '—')}</td><td>${esc(c.email)}</td>
      <td>${esc(fmtTime(c.sent_at))}</td>
      <td><span class="status-dot ${esc(c.status || 'sent')}"></span>${label}</td>
      <td style="color:${color}">${esc(c.detail || '—')}</td></tr>`;
  }).join('');
  tbody.innerHTML = rows || '<tr><td colspan="5" class="tip">还没有投递记录</td></tr>';

  $('scanInfo').textContent = data.last_scan
    ? `上次检查：${fmtTime(data.last_scan)}（只读最近 14 天邮件，不会改成已读）`
    : '还没检查过收件箱。点「检查退信与回复」会读取最近 14 天的邮件（只读，不会改成已读）。';
}

$('scanBtn').addEventListener('click', async () => {
  const btn = $('scanBtn');
  btn.disabled = true; btn.textContent = '扫描中…（大邮箱要十几秒）';
  try {
    const res = await api('POST', '/api/inbox/scan', { days: 14 });
    await loadContacts();
    const bits = [`扫描 ${res.scanned} 封`];
    if (res.new_bounced) bits.push(`新增退信 ${res.new_bounced}`);
    if (res.new_replied) bits.push(`新增回复 ${res.new_replied}`);
    if (!res.new_bounced && !res.new_replied) bits.push('没有新的退信或回复');
    toast(bits.join('，'), res.new_bounced || res.new_replied ? 'success' : 'info', 6000);
  } catch (e) {
    toast(e.message, 'error', 8000);
  }
  btn.disabled = false; btn.textContent = '检查退信与回复';
});

// ── 上手引导 ──
function switchTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) tab.click();
}

async function loadGuide() {
  let data;
  try { data = await api('GET', '/api/onboarding'); } catch (e) { return null; }
  const box = $('guideChecklist');
  box.innerHTML = data.steps.map((s, i) => `
    <div class="guide-step ${s.done ? 'done' : ''}">
      <span class="gs-num">${s.done
        ? '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true"><path d="M2 6.2l2.6 2.6L10 3.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        : i + 1}</span>
      <div class="gs-body">
        <div class="gs-title">${esc(s.title)}${s.done ? ' <span class="gs-badge">完成</span>' : ''}</div>
        <div class="gs-hint">${esc(s.hint)}${s.detail ? ' · ' + esc(s.detail) : ''}</div>
      </div>
      <button class="btn ${s.done ? 'btn-secondary' : 'btn-primary'} btn-xs" data-goto="${esc(s.tab)}">${s.done ? '再看' : '去完成'}</button>
    </div>`).join('');
  box.querySelectorAll('[data-goto]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.goto));
  });
  const done = data.steps.filter(s => s.done).length;
  $('guideTip').textContent = done === data.steps.length
    ? '全部完成了。以后想复看这份清单，随时回到这一页。'
    : (data.first_run
        ? '第一次用？先点「载入示例数据」，再点「试跑一遍」，整个流程不用真发信就能看明白。'
        : '示例用的是 example.com 保留域名，不会发给任何真人。');
  return data;
}

$('demoBtn').addEventListener('click', async () => {
  try {
    const res = await api('POST', '/api/demo/load', {});
    config = await api('GET', '/api/config');
    applyRecipients(res.recipients);
    renderRecipients();
    updateVarHint();
    $('bodyEditor').value = config.body_template || '';
    $('subjectEditor').value = config.subject_template || '';
    const u = config.user || {};
    $('userName').value = u.name || '';
    $('userSchool').value = u.school || '';
    $('userMajor').value = u.major || '';
    $('userGrade').value = u.grade || '';
    $('userPhone').value = u.phone || '';
    $('userEmail').value = u.email || '';
    await loadGuide();
    toast(res.user_filled && res.user_filled.length
      ? '已载入示例数据（含示例个人信息，记得改成你自己的）'
      : '已载入 3 条示例，接着点「试跑一遍」', 'success', 6000);
  } catch (e) { toast(e.message, 'error'); }
});

$('dryBtn').addEventListener('click', () => {
  if (!recipients.length) { toast('先载入示例数据，或去「收件人」页导入你的表格', 'error'); return; }
  startSending('dry');
});

// ── 初始化 ──
async function init() {
  try {
    config = await api('GET', '/api/config');
  } catch (e) {
    toast('读取配置失败：' + e.message, 'error', 8000);
    return;
  }

  PRESETS = config.email_presets || {};
  initEmailPresets();

  const e = config.email || {};
  $('emailAddr').value = e.email || '';
  $('senderName').value = e.sender_name || '';
  $('smtpHost').value = e.smtp_host || '';
  $('smtpPort').value = e.smtp_port || 465;
  $('imapHost').value = e.imap_host || '';
  $('imapPort').value = e.imap_port || 993;
  $('useSsl').value = e.use_ssl ? 'true' : 'false';
  $('authCode').placeholder = e.auth_code ? '已保存（留空则沿用）' : '16 位授权码';
  $('presetHint').textContent = '';
  if (e.email) {
    // 只有配过邮箱才反查服务商；否则保留默认的 QQ
    for (const [name, p] of Object.entries(PRESETS)) {
      if (p.smtp_host === e.smtp_host) {
        $('emailPreset').value = name;
        if (p.daily_hint) $('presetHint').textContent = `该邮箱每日发信量参考上限约 ${p.daily_hint} 封。`;
        break;
      }
    }
  }

  fillAiFormFromConfig();
  if (config.version) $('appVersion').textContent = 'v' + config.version;

  const u = config.user || {};
  $('userName').value = u.name || '';
  $('userSchool').value = u.school || '';
  $('userMajor').value = u.major || '';
  $('userGrade').value = u.grade || '';
  $('userPhone').value = u.phone || '';
  $('userEmail').value = u.email || '';

  $('bodyEditor').value = config.body_template || '';
  $('subjectEditor').value = config.subject_template || '';
  $('rateInput').value = config.send_rate || 20;
  $('dailyLimitInput').value = config.daily_limit || 0;
  $('dailyInfo').textContent = config.daily_limit || '不限';
  $('ccSelf').checked = !!config.cc_self;
  $('todaySent').textContent = (config.today && config.today.sent) || 0;

  recipients = (config.last_recipients || []).map(r => ({
    seq: r.seq, company: r.company || '', email: r.email || '',
    subject: r.subject || '', vars: r.vars || {},
  }));
  renderRecipients();
  updateVarHint();
  await loadAttachments(false);

  const guide = await loadGuide();
  if (guide && guide.first_run && !recipients.length) switchTab('guide');

  if (config.running_job) {
    currentJob = config.running_job;
    $('sendProgress').style.display = 'block';
    pollJob();
  }
}

init();
})();
