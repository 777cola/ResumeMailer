# ResumeMailer · 简历投递助手

<p align="center">
  <a href="https://resumemailer.qijunhao.xyz">
    <img src="https://img.shields.io/badge/🌐_Live_Demo-在线演示-1A4B8C?style=for-the-badge" alt="在线演示">
  </a>
  <a href="https://github.com/777cola/ResumeMailer">
    <img src="https://img.shields.io/badge/GitHub-仓库-181717?style=for-the-badge&logo=github" alt="GitHub">
  </a>
</p>

> **Batch email sender for job seekers** — one spreadsheet in, N personalized application emails out. Preview first, send one to yourself, then send or save as drafts.
>
> **求职者批量投递助手** — 一份 Excel 进，N 封个性化求职邮件出。先预览、先发给自己，再群发或存草稿。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/dependencies-5-lightgrey" alt="Dependencies">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs Welcome">
</p>

---

## 它解决什么问题

投 80 家公司的现实做法是：把简历下载 80 次、复制粘贴 80 遍模板、忘记改公司名 3 次、被 QQ 邮箱限流 1 次。
这个工具把这件事变成：填一张表 → 逐封预览 → 发给自己确认 → 一次发完，并且知道每封的成败。

不是邮件营销工具，没有订阅名单、没有打开率追踪，只做投递这一件事。

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 📄 **表格导入** | `.xlsx` / `.csv`，也可直接从 Excel 复制粘贴。列名支持「公司/单位/企业」「邮箱/邮件/email」等别名 |
| 🧩 **任意列变变量** | 表格里加一列「岗位」，正文和主题就能写 `{岗位}`；一期一岗、一司一主题 |
| 🧾 **主题也做替换** | `实习申请-{姓名}-{学校}-{岗位}` 按行渲染（很多同类工具只替换正文） |
| 👁 **发送前预览** | 服务端渲染，所见即所发；正文/主题/收件人逐封对照 |
| ✉️ **先发给自己** | 一键把第一封发到自己邮箱，确认排版和附件名 |
| 📥 **存草稿 / 直发** | 存草稿可先在网页邮箱里逐封检查再点发送；直发有二次确认 |
| 📊 **实时进度 + 停止** | 后台任务 + 轮询，50 封不卡页面，随时中止 |
| 🚦 **限速与日上限** | 按分钟限速并带随机抖动；QQ 个人邮箱约 50 封/天，到顶自动停并说明原因 |
| 🔁 **防重复投递** | 批内去重 + 对照历史记录提醒「这家你投过了」，可选择跳过 |
| 📎 **附件正确编码** | 中文文件名（`戚俊皓-简历.pdf`）在 Outlook/Foxmail 里不乱码；超 25MB 提前拦下 |
| 🧯 **失败可重跑** | 网络抖动自动重连重试；修好后重跑并勾选「跳过已投递」即只补发失败项 |
| 📋 **投递记录导出** | 一键导出 Excel，用于跟进（谁投了、什么时候、成没成） |
| 🔒 **纯本地** | 邮箱授权码、API Key 只写在本机 `~/.resumemailer/`，文件权限 600；不上传任何服务器 |

## 🖱 不想敲命令

- **macOS**：双击 `启动.command`
- **Windows**：双击 `启动.bat`

首次会自动创建虚拟环境、装依赖（约 1 分钟），之后双击即用，浏览器自动打开。前提是本机有 Python 3.10+。

## 🚀 快速开始

```bash
git clone https://github.com/777cola/ResumeMailer.git
cd ResumeMailer
pip install -r requirements.txt
python main.py          # → http://localhost:8765
```

需要 Python 3.10+，依赖只有 5 个（fastapi / uvicorn / openpyxl / httpx / python-multipart）。

### 0. 三分钟上手（应用内）

打开后进「📖 上手」页，会看到一份会自动打勾的清单（配置邮箱 → 导入收件人 → 正文 → 附件 → 发给自己 → 投递）。
不想填表也能体验：点「载入示例数据」→「试跑一遍」，整个流程会真实渲染主题、正文和附件，但**不会发出任何邮件**。示例用的是 `example.com` 保留域名。

### 1. 邮箱配置

| 邮箱 | 授权码位置 | SMTP / IMAP | 每日参考上限 |
|------|-----------|-------------|------------|
| QQ 邮箱 | 设置 → 账户 → 生成授权码 | smtp.qq.com:465 / imap.qq.com:993 | 约 50 封 |
| 163 / 126 | 设置 → POP3/SMTP/IMAP → 开启并设授权码 | smtp.163.com:465 / imap.163.com:993 | 约 100 封 |
| Gmail | 账号 → 安全性 → 应用专用密码 | smtp.gmail.com:465 / imap.gmail.com:993 | 约 500 封 |
| Outlook | 账户 → 安全 → 应用密码 | smtp.office365.com:587（STARTTLS） | 约 300 封 |

> 授权码不是登录密码。QQ/163 必须先开启 SMTP 服务，否则连不上。

### 2. 收件人

下载模板 → 填表 → 上传。模板里除四列核心字段外，多写的列都会成为变量：

| 序号 | 公司名称 | 收件人邮箱 | 邮件主题 | 应聘岗位 | HR |
|------|---------|-----------|---------|---------|-----|
| 1 | 华泰资产 | hr@htasset.com | 实习申请-{姓名}-{应聘岗位} | 量化研究 | 王女士 |

正文里就能写 `尊敬的{HR}：…… 应聘{应聘岗位}`。
一个单元格写多个邮箱（逗号/分号/顿号分隔）会拆成多封**独立**邮件，两位 HR 不会互相看到地址。

### 3. 正文与主题

内置变量：`{公司名}` `{姓名}` `{学校}` `{专业}` `{年级}` `{电话}` `{邮箱}` `{技能}`，加上表格里自定义的任意列。
可以用 AI 改写（DeepSeek / ChatGPT / Claude / GLM / MIMO / Kimi / 通义千问，任一 API Key）。

### 4. 发送

1. 点「先发给自己」，去收件箱确认排版、附件名、主题
2. 回发送页看预检：未识别变量、空变量、重复投递、没有附件、超出日上限都会标出来
3. 「全部存草稿」→ 去网页邮箱逐封检查后一起发；或「直接发送」→ 输入「确认发送」

## 🧭 常见失败原因

| 现象 | 原因 | 处理 |
|------|------|------|
| `535 Authentication failed` | 用了登录密码，或没开 SMTP 服务 | 生成授权码，确认设置里 SMTP 已开启 |
| `Connection refused` / 超时 | 公司网络/代理挡了 465 端口 | 换网络，或改用 587 + STARTTLS |
| 存草稿全失败 | 邮箱没开 IMAP，或草稿箱名特殊 | 程序会自动探测 Drafts/草稿箱/[Gmail]/Drafts；仍失败就改用直接发送 |
| 后半段全失败 | 触发每日发信上限 | 设「每日上限」，第二天继续；QQ 个人邮箱约 50 封/天 |
| 进了垃圾箱 | 新邮箱、短时间大量同文邮件 | 降速到 10 封/分、正文带姓名和岗位、别用群发式开头 |

## ☁️ 部署

### 本地（推荐）
`python main.py`，只监听 `127.0.0.1`。邮箱授权码不出本机。

### Docker
```bash
docker build -t resumemailer .
docker run -d -p 8765:8765 -v resumemailer-data:/data -e RESUMEMAILER_TOKEN=换成你的口令 --name resumemailer resumemailer
```

### Render / Fly.io / Railway
仓库自带 `render.yaml`。**公网部署请务必设置 `RESUMEMAILER_TOKEN`**：
不设的话任何人打开网址都能看到你的邮箱配置、附件列表，并用你的实例发信。设置后所有 API 需要口令，页面会提示输入一次并记住。

| 平台 | 持久存储 | 费用 | 休眠 |
|------|---------|------|------|
| Render Free | ✅ 1GB | 免费 | 15 分钟无访问 |
| Render Starter | ✅ | $7/月 | 不休眠 |
| Docker 自部署 | ✅ 卷挂载 | VPS 费用 | 可控 |

## 🧱 项目结构

```
resumemailer/
├── main.py                 启动入口
├── server.py               FastAPI 路由（配置 / 解析 / 预览 / 发送 / 日志 / 导出）
├── config.py               配置与日志持久化（~/.resumemailer/）
├── engine/
│   ├── excel_parser.py     Excel/CSV 解析、别名识别、多邮箱拆分、去重
│   ├── render.py           变量渲染（预览与发送共用同一套规则）
│   ├── sender.py           SMTP 直发 / IMAP 存草稿、限速、重试、日上限
│   ├── jobs.py             后台批次与进度
│   └── ai_filler.py        AI 提取收件人 / 改写正文
├── static/                 前端（原生 JS，无构建步骤）
└── tests/test_selftest.py  离线自检：解析 / 渲染 / MIME / 限速 / 取消
```

自检（不联网、不发信）：
```bash
python tests/test_selftest.py     # 23/23 passed
```

## ❓ FAQ

**会泄露我的邮箱授权码吗？**
不会。配置写在 `~/.resumemailer/config.json`（权限 600），只在本地进程使用。仅在你自己配置了 AI Key 并点击 AI 功能时，正文会发给对应 AI 厂商。

**一次能发多少封？**
取决于邮箱服务商，不是程序。表格超过 2000 行会被截断保护；单封附件上限 25MB。

**能当桌面软件装吗？还需要开命令行吗？**
现在是"本地网页应用"：双击启动器后浏览器打开，不碰命令行。要真正免 Python 的安装包，可以用 PyInstaller 打包（需要自己签名，macOS 首次要右键→打开，Windows 常见杀软误报）；对个人使用来说，启动器已经够用。

**能带图片签名 / HTML 排版吗？**
正文会自动生成 HTML 版（保留换行），比纯文本更不容易被判定为垃圾邮件。粘贴完整 HTML 也会原样发送。

**邮件发出去能撤回吗？**
不能。所以有「先发给自己」和「存草稿」两条路。

## 📄 License

MIT © [AutumnPants](https://github.com/777cola)
