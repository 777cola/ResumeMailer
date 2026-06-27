/* ResumeMailer · 简历投递助手 — 前端逻辑 */
(function() {
'use strict';

// ── 状态 ──
let config = {};          // 服务端配置
let recipients = [];      // 当前收件人列表
let attachments = [];     // 当前附件列表
let previewIdx = 0;       // 预览索引
let sendResults = [];     // 发送结果
let bodyChatHistory = [   // AI 对话历史
  {role:'assistant', content:'你好！我可以帮你撰写或修改求职邮件正文。请告诉我你的要求。'}
];

// ── 工具 ──
async function api(method, url, body) {
  const opts = {method, headers:{}};
  if (body && !(body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    opts.body = body;
  }
  const resp = await fetch(url, opts);
  const data = await resp.json();
  if (!resp.ok && !data.ok) throw new Error(data.msg || data.error || '请求失败');
  return data;
}

function toast(msg, type='info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast ${type} show`;
  setTimeout(() => el.classList.remove('show'), 3000);
}

function $(id) { return document.getElementById(id); }

// ── Tab 切换 ──
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    $(`tab-${tab.dataset.tab}`).classList.add('active');
    // 进入发送tab时刷新预览
    if (tab.dataset.tab === 'send') refreshSendTab();
    if (tab.dataset.tab === 'logs') loadLogs();
  });
});

// ── Sub-tab 切换 ──
document.querySelectorAll('.sub-tabs').forEach(group => {
  group.addEventListener('click', e => {
    const btn = e.target.closest('.sub-tab');
    if (!btn) return;
    group.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    const method = btn.dataset.method;
    document.querySelectorAll(`#tab-${btn.closest('.tab-content').id.replace('tab-','')} .method-panel`).forEach(p => p.classList.remove('active'));
    document.getElementById(`method-${method}`).classList.add('active');
  });
});

// ── 1. 邮箱配置 ──
const EMAIL_PRESETS = {
  'QQ邮箱':    {smtp_host:'smtp.qq.com',smtp_port:465,imap_host:'imap.qq.com',imap_port:993,use_ssl:true},
  '163邮箱':   {smtp_host:'smtp.163.com',smtp_port:465,imap_host:'imap.163.com',imap_port:993,use_ssl:true},
  '126邮箱':   {smtp_host:'smtp.126.com',smtp_port:465,imap_host:'imap.126.com',imap_port:993,use_ssl:true},
  'Gmail':     {smtp_host:'smtp.gmail.com',smtp_port:465,imap_host:'imap.gmail.com',imap_port:993,use_ssl:true},
  'Outlook':   {smtp_host:'smtp.office365.com',smtp_port:587,imap_host:'outlook.office365.com',imap_port:993,use_ssl:false},
  'Foxmail':   {smtp_host:'smtp.qq.com',smtp_port:465,imap_host:'imap.qq.com',imap_port:993,use_ssl:true},
};

function initEmailPresets() {
  const sel = $('emailPreset');
  sel.innerHTML = '<option value="">— 手动填写 —</option>';
  Object.keys(EMAIL_PRESETS).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name; sel.appendChild(opt);
  });
  sel.addEventListener('change', () => {
    const p = EMAIL_PRESETS[sel.value];
    if (!p) return;
    $('smtpHost').value = p.smtp_host; $('smtpPort').value = p.smtp_port;
    $('imapHost').value = p.imap_host; $('imapPort').value = p.imap_port;
    $('useSsl').value = p.use_ssl ? 'true' : 'false';
  });
}

$('testConnBtn').addEventListener('click', async () => {
  const data = gatherEmailConfig();
  const btn = $('testConnBtn'); btn.disabled = true; btn.textContent = '测试中...';
  $('testResult').className = 'test-result';
  $('testResult').textContent = '';
  try {
    const res = await api('POST', '/api/email/test', data);
    $('testResult').textContent = res.msg;
    $('testResult').className = 'test-result success';
  } catch(e) {
    $('testResult').textContent = e.message;
    $('testResult').className = 'test-result error';
  }
  btn.disabled = false; btn.textContent = '测试连接';
});

function gatherEmailConfig() {
  return {
    email: $('emailAddr').value.trim(),
    smtp_host: $('smtpHost').value.trim(),
    smtp_port: parseInt($('smtpPort').value),
    imap_host: $('imapHost').value.trim(),
    imap_port: parseInt($('imapPort').value),
    use_ssl: $('useSsl').value === 'true',
    auth_code: $('authCode').value.trim(),
    sender_name: $('senderName').value.trim(),
  };
}

$('saveEmailBtn').addEventListener('click', async () => {
  try {
    await api('POST', '/api/config/email', gatherEmailConfig());
    toast('✅ 邮箱配置已保存', 'success');
  } catch(e) { toast('❌ ' + e.message, 'error'); }
});

// ── 2. 收件人 ──

// Excel 上传拖拽
const excelZone = $('excelUploadZone');
excelZone.addEventListener('click', () => $('excelFileInput').click());
excelZone.addEventListener('dragover', e => { e.preventDefault(); excelZone.classList.add('dragover'); });
excelZone.addEventListener('dragleave', () => excelZone.classList.remove('dragover'));
excelZone.addEventListener('drop', e => {
  e.preventDefault(); excelZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) handleExcelFile(e.dataTransfer.files[0]);
});
$('excelFileInput').addEventListener('change', e => {
  if (e.target.files.length) handleExcelFile(e.target.files[0]);
});

async function handleExcelFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await api('POST', '/api/template/parse', fd);
    displayRecipients(res.recipients, res.errors);
  } catch(e) { toast('❌ ' + e.message, 'error'); }
}

// AI 填充
async function initAIProviders() {
  try {
    config = await api('GET', '/api/config');
  } catch(e) { /* will retry later */ }
  const provs = (config.ai_providers || []);
  ['aiProvider2','aiProvider3'].forEach(id => {
    const sel = $(id); if (!sel) return;
    sel.innerHTML = '<option value="">— 选择 AI —</option>';
    provs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.name; opt.textContent = p.name; sel.appendChild(opt);
    });
    sel.addEventListener('change', () => {
      const p = provs.find(x => x.name === sel.value);
      if (p && p.models.length) {
        const modelInput = id === 'aiProvider2' ? $('aiModel2') : $('aiModel3');
        modelInput.value = p.models[0];
      }
    });
  });
}

$('aiFillBtn').addEventListener('click', async () => {
  const input = $('aiInput').value.trim();
  if (!input) { toast('请先输入公司信息', 'error'); return; }
  const provider = $('aiProvider2').value;
  const model = $('aiModel2').value.trim();
  const apiKey = $('aiKey2').value.trim();
  if (!provider || !model || !apiKey) { toast('请先配置 AI 参数', 'error'); return; }
  $('aiFillBtn').disabled = true; $('aiFillBtn').textContent = 'AI 分析中...';
  try {
    const res = await api('POST', '/api/ai/fill-template', {provider, api_key: apiKey, model, input});
    if (res.ok && res.recipients) {
      // Convert AI result to our format
      const list = res.recipients.map((r, i) => ({
        seq: i+1, company: r.company || '', email: r.email || '', subject: r.subject || ''
      }));
      displayRecipients(list, []);
      toast(`✅ AI 提取了 ${list.length} 条收件人信息`, 'success');
    }
  } catch(e) { toast('❌ ' + e.message, 'error'); }
  $('aiFillBtn').disabled = false; $('aiFillBtn').textContent = '🤖 AI 自动填充';
});

function displayRecipients(list, errors) {
  recipients = list;
  const wrap = $('recipientTableWrapper');
  wrap.style.display = 'block';
  $('recipientCount').textContent = `${list.length} 条`;

  const tbody = $('recipientTable').querySelector('tbody');
  tbody.innerHTML = '';
  list.forEach((r, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${r.seq || i+1}</td><td>${esc(r.company)}</td><td>${esc(r.email)}</td><td>${esc(r.subject)}</td>
      <td><button class="btn btn-secondary" style="padding:4px 10px;font-size:12px;" onclick="removeRecipient(${i})">删除</button></td>`;
    tbody.appendChild(tr);
  });

  const errDiv = $('parseErrors');
  errDiv.innerHTML = errors.map(e => `<p>⚠️ ${esc(e)}</p>`).join('');

  toast(`已加载 ${list.length} 位收件人`, 'success');
}

window.removeRecipient = function(idx) {
  recipients.splice(idx, 1);
  displayRecipients(recipients, []);
};

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ── 3. 正文 ──
async function loadBody() {
  try {
    if (!config.body_template) config = await api('GET', '/api/config');
    $('bodyEditor').value = config.body_template || '';
  } catch(e) { /* ignore */ }
}

$('saveBodyBtn').addEventListener('click', async () => {
  try {
    await api('POST', '/api/config/body', {body_template: $('bodyEditor').value});
    toast('✅ 正文已保存', 'success');
  } catch(e) { toast('❌ ' + e.message, 'error'); }
});

// AI 对话
$('bodyChatSend').addEventListener('click', sendBodyChat);
$('bodyChatInput').addEventListener('keydown', e => { if (e.key === 'Enter') sendBodyChat(); });

async function sendBodyChat() {
  const input = $('bodyChatInput');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  const provider = $('aiProvider3').value;
  const model = $('aiModel3').value.trim();
  const apiKey = $('aiKey3').value.trim();
  if (!provider || !model || !apiKey) { toast('请先配置 AI 参数', 'error'); return; }

  // 添加用户消息
  bodyChatHistory.push({role:'user', content: msg});
  appendChatMsg(msg, 'user');

  // 显示加载中
  const loadingDiv = appendChatMsg('思考中...', 'assistant', true);

  try {
    const msgs = bodyChatHistory.filter(m => m.role !== 'system').slice(-20);
    const res = await api('POST', '/api/ai/chat', {
      provider, api_key: apiKey, model,
      messages: [{role:'system', content:'你是一封求职邮件的撰写助手。返回纯文本正文，不要Markdown格式，直接给出可复制的邮件正文。'}].concat(msgs)
    });
    if (loadingDiv) loadingDiv.remove();
    bodyChatHistory.push({role:'assistant', content: res.content});
    appendChatMsg(res.content, 'assistant');

    // 询问是否使用此正文
    const useBtn = document.createElement('button');
    useBtn.className = 'btn btn-warning';
    useBtn.style.cssText = 'margin-top:4px;padding:4px 12px;font-size:12px;';
    useBtn.textContent = '📋 使用此正文';
    useBtn.addEventListener('click', () => {
      $('bodyEditor').value = res.content;
      toast('✅ 已填入正文编辑框，点击「保存正文」以持久化', 'success');
    });
    document.getElementById('bodyChatMsgs').appendChild(useBtn);
  } catch(e) {
    if (loadingDiv) loadingDiv.remove();
    appendChatMsg('错误: ' + e.message, 'error');
  }
}

function appendChatMsg(text, role, isLoading) {
  const container = document.getElementById('bodyChatMsgs');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

// ── 4. 附件 ──
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
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    try {
      const res = await api('POST', '/api/attachments/upload', fd);
      attachments.push(res.file);
    } catch(e) { toast('❌ ' + e.message, 'error'); }
  }
  renderAttachments();
  toast(`✅ 已上传 ${files.length} 个文件`, 'success');
}

async function loadAttachments() {
  try {
    const res = await api('GET', '/api/attachments');
    attachments = res.files;
    renderAttachments();
  } catch(e) { /* ignore */ }
}

function renderAttachments() {
  const list = $('attachList');
  if (!attachments.length) {
    list.innerHTML = '<p style="color:#999;font-size:13px;">暂无附件</p>';
    return;
  }
  list.innerHTML = attachments.map((f, i) =>
    `<div class="file-item">
      <span class="file-name">📎 ${esc(f.name)} (${(f.size/1024).toFixed(1)} KB)</span>
      <span class="file-del" onclick="deleteAttach(${i})">🗑 删除</span>
    </div>`
  ).join('');
}

window.deleteAttach = async function(idx) {
  const f = attachments[idx];
  try {
    await api('DELETE', `/api/attachments/${encodeURIComponent(f.name)}`);
    attachments.splice(idx, 1);
    renderAttachments();
  } catch(e) { toast('❌ ' + e.message, 'error'); }
};

// ── 5. 发送 ──
function refreshSendTab() {
  $('sendTotal').textContent = recipients.length;
  $('sendAttachCount').textContent = attachments.length;
  $('sendRateDisplay').textContent = `${config.send_rate || 20} 封/分`;
  $('sendResult').style.display = 'none';
  $('sendProgress').style.display = 'none';
  if (recipients.length) showPreview(0);
}

function showPreview(idx) {
  if (!recipients.length) {
    $('sendPreview').innerHTML = '<p style="color:#999;">请先在「收件人」页添加收件人</p>';
    return;
  }
  previewIdx = idx;
  const r = recipients[idx];
  const max = recipients.length;

  // 渲染正文：替换所有变量
  let body = $('bodyEditor').value;
  body = body.replace(/\{公司名\}/g, r.company);
  // 用户变量
  const vars = {
    '{姓名}': $('userName').value,
    '{学校}': $('userSchool').value,
    '{专业}': $('userMajor').value,
    '{年级}': $('userGrade').value,
    '{电话}': $('userPhone').value,
    '{邮箱}': $('userEmail').value,
  };
  for (const [k, v] of Object.entries(vars)) {
    body = body.replace(new RegExp(k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), v || k);
  }

  $('sendPreview').innerHTML = `
    <div class="preview-nav">
      <button onclick="prevPreview()">‹</button>
      <span>${idx+1} / ${max} — ${esc(r.company)}</span>
      <button onclick="nextPreview()">›</button>
    </div>
    <div class="preview-subject">📧 ${esc(r.subject || '(无主题)')}</div>
    <div class="preview-to">📩 ${esc(r.email)}</div>
    <hr style="margin:8px 0;border:none;border-top:1px solid #ddd;">
    <div class="preview-body">${esc(body)}</div>`;
}
window.prevPreview = () => showPreview(previewIdx > 0 ? previewIdx - 1 : recipients.length - 1);
window.nextPreview = () => showPreview(previewIdx < recipients.length - 1 ? previewIdx + 1 : 0);

$('previewBtn').addEventListener('click', () => {
  if (!recipients.length) { toast('收件人为空', 'error'); return; }
  refreshSendTab();
  toast('👁 使用左右箭头逐封预览', 'info');
});

// 存草稿
$('draftBtn').addEventListener('click', () => {
  if (!recipients.length) { toast('收件人为空', 'error'); return; }
  if (!confirm(`确定将 ${recipients.length} 封邮件存入草稿箱？`)) return;
  startSending('draft');
});

// 直接发送（三次确认）
$('sendBtn').addEventListener('click', () => {
  if (!recipients.length) { toast('收件人为空', 'error'); return; }
  if (!config.email || !config.email.email) { toast('请先在邮箱配置页配置邮箱', 'error'); return; }
  $('sendWarning').style.display = 'flex';
  $('warningInput').value = '';
  $('warningConfirm').disabled = true;
  $('warningStep1').textContent = '请输入 "确认发送" 以继续：';
});

$('warningInput').addEventListener('input', () => {
  $('warningConfirm').disabled = $('warningInput').value.trim() !== '确认发送';
});

$('warningCancel').addEventListener('click', () => {
  $('sendWarning').style.display = 'none';
});

$('warningConfirm').addEventListener('click', () => {
  $('sendWarning').style.display = 'none';
  startSending('send');
});

async function startSending(mode) {
  $('sendProgress').style.display = 'block';
  $('sendResult').style.display = 'none';
  $('progressFill').style.width = '0%';
  $('progressText').textContent = '准备中...';
  $('progressLog').innerHTML = '';
  $('draftBtn').disabled = true;
  $('sendBtn').disabled = true;

  try {
    // 先保存正文
    await api('POST', '/api/config/body', {body_template: $('bodyEditor').value});

    const res = await api('POST', '/api/send', {
      recipients: recipients,
      body: $('bodyEditor').value,
      attachments: attachments.map(a => a.path),
      send_mode: mode,
      rate: config.send_rate || 20,
    });

    $('progressText').textContent = '✅ 发送完成';
    $('progressFill').style.width = '100%';

    // 显示结果
    $('sendResult').style.display = 'block';
    sendResults = res.results || [];
    const success = (res.success || 0);
    const failed = (res.failed || 0);

    const summary = $('resultSummary');
    if (failed === 0) {
      summary.innerHTML = `✅ 全部成功！${success}/${res.total} 封已${mode === 'send' ? '发送' : '存入草稿箱'}`;
      summary.style.background = '#e8f5e9'; summary.style.color = '#2e7d32';
    } else {
      summary.innerHTML = `⚠️ ${success} 成功，${failed} 失败（共 ${res.total} 封）`;
      summary.style.background = '#fff3e0'; summary.style.color = '#e65100';
    }

    const tbody = $('resultTable').querySelector('tbody');
    tbody.innerHTML = '';
    sendResults.forEach(r => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${esc(r.company)}</td><td>${esc(r.email)}</td>
        <td>${r.success ? '✅ 成功' : '❌ 失败'}</td>
        <td style="color:${r.success ? '#999' : '#c62828'}">${esc(r.error || '-')}</td>`;
      tbody.appendChild(tr);
    });

  } catch(e) {
    $('progressText').textContent = '❌ ' + e.message;
    $('progressFill').style.width = '0%';
    const log = $('progressLog');
    log.innerHTML += `<p class="error">❌ ${esc(e.message)}</p>`;
  }

  $('draftBtn').disabled = false;
  $('sendBtn').disabled = false;
}

// ── 6. 日志 ──
async function loadLogs() {
  try {
    const res = await api('GET', '/api/logs');
    const tbody = $('logTable').querySelector('tbody');
    tbody.innerHTML = '';
    (res.logs || []).slice().reverse().forEach(log => {
      const tr = document.createElement('tr');
      const time = log.time ? new Date(log.time).toLocaleString('zh-CN') : '-';
      tr.innerHTML = `<td>${esc(time)}</td><td>${esc(log.company)}</td><td>${esc(log.email)}</td>
        <td>${log.success ? '✅' : '❌'} ${log.mode === 'send' ? '已发送' : '存草稿'}</td>
        <td style="color:${log.success ? '#999' : '#c62828'}">${esc(log.error || '-')}</td>`;
      tbody.appendChild(tr);
    });
  } catch(e) { /* ignore */ }
}

$('refreshLogsBtn').addEventListener('click', loadLogs);
$('clearLogsBtn').addEventListener('click', async () => {
  if (!confirm('确定清空所有日志？')) return;
  await api('DELETE', '/api/logs');
  loadLogs();
  toast('✅ 日志已清空', 'success');
});

// ── 初始化 ──
async function init() {
  initEmailPresets();
  await initAIProviders();
  await loadBody();
  await loadAttachments();

  // 加载保存的邮箱配置
  if (config && config.email) {
    const e = config.email;
    $('emailAddr').value = e.email || '';
    $('senderName').value = e.sender_name || '';
    $('smtpHost').value = e.smtp_host || '';
    $('smtpPort').value = e.smtp_port || 465;
    $('imapHost').value = e.imap_host || '';
    $('imapPort').value = e.imap_port || 993;
    $('useSsl').value = e.use_ssl ? 'true' : 'false';
  }

  // 加载 AI 配置到子页面
  if (config && config.ai) {
    const a = config.ai;
    if (a.provider) {
      $('aiProvider2').value = a.provider;
      $('aiProvider3').value = a.provider;
    }
    if (a.model) {
      $('aiModel2').value = a.model;
      $('aiModel3').value = a.model;
    }
  }

  // 加载用户信息
  if (config && config.user) {
    const u = config.user;
    $('userName').value = u.name || '';
    $('userSchool').value = u.school || '';
    $('userMajor').value = u.major || '';
    $('userGrade').value = u.grade || '';
    $('userPhone').value = u.phone || '';
    $('userEmail').value = u.email || '';
  }
}

// 保存用户信息
$('saveUserInfoBtn').addEventListener('click', async () => {
  try {
    await api('POST', '/api/config/user', {
      name: $('userName').value.trim(),
      school: $('userSchool').value.trim(),
      major: $('userMajor').value.trim(),
      grade: $('userGrade').value.trim(),
      phone: $('userPhone').value.trim(),
      email: $('userEmail').value.trim(),
    });
    toast('✅ 个人信息已保存', 'success');
  } catch(e) { toast('❌ ' + e.message, 'error'); }
});

document.addEventListener('DOMContentLoaded', init);

})();
