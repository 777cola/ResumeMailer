# ResumeMailer · 简历投递助手

> **Batch email sender for job seekers** — Send personalized application emails with a single click. Save as drafts or send directly. Optional AI-powered template filling.
>
> **求职者批量投递助手** — 一键批量发送个性化求职邮件。支持存草稿或直接发送，可选 AI 智能填充模板。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs Welcome">
</p>

---

## ✨ Features / 功能

| English | 中文 |
|---------|------|
| 📧 **Email Sending** — Direct SMTP send or IMAP draft | 📧 **邮件发送** — SMTP 直接发送或 IMAP 存草稿 |
| 👥 **Bulk Recipients** — Import from Excel template | 👥 **批量收件人** — 从 Excel 模板导入 |
| 🤖 **AI Auto-Fill** — Let AI extract company info and generate subjects | 🤖 **AI 自动填充** — AI 提取公司信息并生成主题 |
| ✍️ **Body Editor** — Template with `{公司名}` variable substitution | ✍️ **正文编辑** — 支持 `{公司名}` 变量替换的正文模板 |
| 🤖 **AI Chat** — Chat with AI to customize your email body | 🤖 **AI 对话** — 与 AI 对话定制邮件正文 |
| 📎 **Attachments** — Upload and manage attachments per batch | 📎 **附件管理** — 上传并管理附件 |
| 🔒 **Local Only** — All data (keys, config) stored locally | 🔒 **本地安全** — 密钥、配置全部存储本地 |
| 🚦 **Rate Control** — Smart throttling to avoid spam filters | 🚦 **频率控制** — 智能限速，避免触发反垃圾 |
| 📋 **Send Logs** — Full history with retry for failures | 📋 **发送日志** — 完整历史记录，失败可重试 |

## 🚀 Quick Start / 快速开始

### Prerequisites / 前置要求

- Python 3.10+
- A mailbox with SMTP/IMAP enabled + authorization code
  - QQ邮箱: 设置 → 账户 → 生成授权码
  - 163邮箱: 设置 → POP3/SMTP → 开启 + 设置授权码
  - Gmail: App Passwords

### Install & Run / 安装运行

```bash
# 1. Clone
git clone https://github.com/777cola/ResumeMailer.git
cd ResumeMailer

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run!
python main.py
```

Then open your browser → **http://localhost:8765**

## 📖 User Guide / 使用指南

### Step 1: Email Setup / 邮箱配置

Select your email provider or enter SMTP/IMAP settings manually. Enter your authorization code and click "Test Connection" to verify.

选择邮箱服务商或手动填写 SMTP/IMAP 配置。输入授权码后点击「测试连接」验证。

### Step 2: Import Recipients / 导入收件人

**Option A: Excel Template / 上传Excel模板**

1. Download the template: click "⬇️ 下载 Excel 模板"
2. Fill in: `No. | Company | Email | Subject`
3. Upload the filled Excel

| 序号 | 公司名称 | 收件人邮箱 | 邮件主题 |
|------|---------|-----------|---------|
| 1 | 示例公司 | hr@example.com | 实习申请-姓名-学校-专业 |

**Option B: AI Auto-Fill / AI自动填充**

1. Select an AI provider (DeepSeek/GLM/MIMO/ChatGPT/Claude)
2. Enter API Key
3. Paste company/position information
4. Click "🤖 AI 自动填充"

### Step 3: Email Body / 正文编辑

Write your email body. Use `{公司名}` for automatic company name substitution.

撰写邮件正文。使用 `{公司名}` 自动替换为收件公司名称。

Use the AI chat window to generate or modify your email body with AI assistance.

使用 AI 对话窗口辅助撰写或修改正文。

### Step 4: Attachments / 附件

Upload your resume, cover letter, or other attachments. All attachments are added to every outgoing email.

上传简历、求职信等附件。所有附件将附加到每一封邮件。

### Step 5: Preview & Send / 预览发送

- **Preview** each email with ← → navigation
- **Save as Draft** (IMAP) — stored in your mailbox drafts folder
- ⚠️ **Direct Send** (SMTP) — requires triple confirmation

- **逐封预览**：使用 ← → 翻页
- **存草稿**（IMAP）：存入邮箱草稿箱，审核后再手动发
- ⚠️ **直接发送**（SMTP）：三次确认后才放行，慎用！

## 🧩 Project Structure / 项目结构

```
resumemailer/
├── main.py              # Entry point / 启动入口
├── server.py            # FastAPI server with all routes / FastAPI 服务端
├── config.py            # Config management (local JSON) / 配置管理
├── engine/
│   ├── excel_parser.py  # Excel template read/write/validate / Excel 模板读写校验
│   ├── ai_filler.py     # AI API integration / AI API 集成
│   └── sender.py        # SMTP + IMAP send engine / 发送引擎
├── static/
│   ├── index.html       # Web UI / 前端页面
│   ├── style.css        # Styles / 样式
│   └── app.js           # Frontend logic / 前端逻辑
├── templates/           # Template files directory / 模板目录
├── requirements.txt     # Dependencies / 依赖
└── README.md            # This file
```

## 🔧 Configuration / 配置

All configuration is stored in `~/.resumemailer/config.json`:
- Email settings (SMTP/IMAP host, port, auth code)
- AI provider (provider name, API key, model)
- Body template
- Send rate (default: 20 emails/minute)

所有配置存储在 `~/.resumemailer/config.json`：
- 邮箱设置（SMTP/IMAP 地址、端口、授权码）
- AI 提供商（名称、API Key、模型）
- 正文模板
- 发送速度（默认 20 封/分钟）

## 🤖 Supported AI Providers / 支持的 AI 提供商

| Provider | Base URL | Default Models |
|----------|----------|---------------|
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-reasoner |
| GLM (智谱) | `https://open.bigmodel.cn/api/paas/v4` | glm-4-plus, glm-4-air-0111, glm-4-flash |
| MIMO | `https://api.xiaomimimo.com/v1` | mimo-v2.5, mimo-v2.5-turbo, mimo-pro |
| ChatGPT | `https://api.openai.com/v1` | gpt-4.1, gpt-4o, gpt-4o-mini, o3, o4-mini |
| Claude | `https://api.anthropic.com/v1` | claude-sonnet-4, claude-4-opus, claude-haiku-3-5 |

To add custom providers, edit `config.py` → `AI_PRESETS`.

自定义提供商可修改 `config.py` 中的 `AI_PRESETS`。

## 🔒 Security / 安全

- **All credentials stored locally** — never transmitted to third parties
- Auth codes and API keys stay on your machine
- AI API calls only happen when you explicitly enable them
- Open source — review the code yourself

- **所有凭据仅在本地存储** — 绝不传输给第三方
- 授权码和 API Key 仅保存在本机
- AI API 调用仅在用户明确启用时触发
- 代码完全开源透明

## 🧪 Running Tests / 运行测试

```bash
python -c "
from engine.excel_parser import generate_template, parse_workbook
tmpl = generate_template()
result = parse_workbook(tmpl)
print(f'Template test: {len(result.recipients)} recipients, {len(result.errors)} errors')
"
```

## 📝 License / 许可

MIT License. Free for personal and commercial use.

MIT 许可证。免费用于个人和商业用途。

## 👤 Author

**AutumnPants** ([@777cola](https://github.com/777cola))

---

<p align="center">
  <b>ResumeMailer</b> — Batch email sending made simple.<br>
  <b>简历投递助手</b> — 让批量投递变得简单。
</p>
