"""ResumeMailer FastAPI 服务端"""
import io
import os
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import openpyxl
import uvicorn
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from config import (EMAIL_PRESETS, load_config, save_config, EmailConfig, ATTACH_DIR,
                    LOG_FILE, sent_today, already_contacted, load_log)
from engine.excel_parser import generate_template, parse_workbook, parse_tsv
from engine.ai_filler import ai_chat, ai_fill_template, ai_generate_body, get_available_providers
from engine.sender import test_connection, send_test
from engine.render import (render_email, unknown_placeholders, collect_vars,
                           build_context)
from engine import jobs

app = FastAPI(title="ResumeMailer · 简历投递助手")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 公开部署时可设访问口令，避免别人读到你的配置 / 用你的实例发信
ACCESS_TOKEN = os.environ.get("RESUMEMAILER_TOKEN", "").strip()
MAX_ATTACH_MB = 25


@app.middleware("http")
async def guard(request: Request, call_next):
    if ACCESS_TOKEN and request.url.path.startswith("/api"):
        provided = request.headers.get("x-token") or request.query_params.get("token")
        if provided != ACCESS_TOKEN:
            return JSONResponse(status_code=401,
                                content={"ok": False, "need_token": True,
                                         "error": "需要访问口令（RESUMEMAILER_TOKEN）"})
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── 配置 ──

def _config_payload() -> dict:
    cfg = load_config()
    return {
        "email": {
            "email": cfg.email.email,
            "smtp_host": cfg.email.smtp_host,
            "smtp_port": cfg.email.smtp_port,
            "imap_host": cfg.email.imap_host,
            "imap_port": cfg.email.imap_port,
            "use_ssl": cfg.email.use_ssl,
            "auth_code": bool(cfg.email.auth_code),   # 只返回是否存在
            "sender_name": cfg.email.sender_name,
        },
        "ai": {
            "provider": cfg.ai.provider,
            "api_key": bool(cfg.ai.api_key),
            "model": cfg.ai.model,
        },
        "user": {
            "name": cfg.user.name, "school": cfg.user.school, "major": cfg.user.major,
            "grade": cfg.user.grade, "phone": cfg.user.phone, "email": cfg.user.email,
        },
        "body_template": cfg.body_template,
        "subject_template": cfg.subject_template,
        "send_rate": cfg.send_rate,
        "daily_limit": cfg.daily_limit,
        "cc_self": cfg.cc_self,
        "last_attachments": cfg.last_attachments,
        "last_recipients": cfg.last_recipients,
        "ai_providers": get_available_providers(),
        "email_presets": EMAIL_PRESETS,
        "today": {"sent": sent_today(), "date": date.today().isoformat()},
        "token_required": bool(ACCESS_TOKEN),
        "running_job": jobs.active_job_id(),
        "limits": {"max_attach_mb": MAX_ATTACH_MB},
    }


@app.get("/api/config")
def get_config():
    return _config_payload()


@app.post("/api/config/email")
def save_email_config(data: dict):
    cfg = load_config()
    for key in ("email", "smtp_host", "smtp_port", "imap_host", "imap_port",
                "use_ssl", "sender_name"):
        if key in data and data[key] is not None:
            setattr(cfg.email, key, data[key])
    if data.get("auth_code"):
        cfg.email.auth_code = str(data["auth_code"]).strip()
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/ai")
def save_ai_config(data: dict):
    cfg = load_config()
    if data.get("provider"):
        cfg.ai.provider = data["provider"]
    if data.get("model"):
        cfg.ai.model = data["model"]
    if data.get("api_key"):
        cfg.ai.api_key = str(data["api_key"]).strip()
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/settings")
def save_settings(data: dict):
    """正文 / 主题 / 速度 / 每日上限 / 抄送自己"""
    cfg = load_config()
    if "body_template" in data:
        cfg.body_template = data["body_template"] or ""
    if "subject_template" in data:
        cfg.subject_template = data["subject_template"] or ""
    if "send_rate" in data:
        try:
            cfg.send_rate = max(1, min(120, int(data["send_rate"])))
        except (TypeError, ValueError):
            pass
    if "daily_limit" in data:
        try:
            cfg.daily_limit = max(0, min(1000, int(data["daily_limit"])))
        except (TypeError, ValueError):
            pass
    if "cc_self" in data:
        cfg.cc_self = bool(data["cc_self"])
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/user")
def save_user_info(data: dict):
    cfg = load_config()
    for key in ("name", "school", "major", "grade", "phone", "email"):
        if key in data:
            setattr(cfg.user, key, str(data[key] or "").strip())
    save_config(cfg)
    return {"ok": True}


# ── 连接测试 ──

@app.post("/api/email/test")
def test_email(data: dict):
    cfg = load_config()
    ecfg = EmailConfig(
        email=data.get("email") or cfg.email.email,
        smtp_host=data.get("smtp_host") or cfg.email.smtp_host,
        smtp_port=int(data.get("smtp_port") or cfg.email.smtp_port),
        imap_host=data.get("imap_host") or cfg.email.imap_host,
        imap_port=int(data.get("imap_port") or cfg.email.imap_port),
        use_ssl=bool(data.get("use_ssl", cfg.email.use_ssl)),
        auth_code=data.get("auth_code") or cfg.email.auth_code,
    )
    if not ecfg.email or not ecfg.auth_code:
        return JSONResponse(status_code=400,
                            content={"ok": False, "msg": "邮箱地址或授权码为空"})
    ok, msg = test_connection(ecfg)
    return {"ok": ok, "msg": msg} if ok else JSONResponse(
        status_code=400, content={"ok": False, "msg": msg})


# ── 模板 / 解析 ──

@app.get("/api/template/download")
def download_template():
    content = generate_template()
    fname = quote("ResumeMailer收件人模板.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


def _store_recipients(recipients: list):
    cfg = load_config()
    cfg.last_recipients = recipients
    save_config(cfg)


@app.post("/api/template/parse")
async def parse_excel(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "文件超过 10MB，请确认是不是选错了文件")
    result = parse_workbook(content, file.filename or "")
    recipients = [r.to_dict() for r in result.recipients]
    if recipients:
        _store_recipients(recipients)
    return {"recipients": recipients, "errors": result.errors,
            "warnings": result.warnings, "total": len(recipients),
            "variables": collect_vars(recipients)}


@app.post("/api/recipients/parse-text")
def parse_text(data: dict):
    result = parse_tsv(data.get("text", ""))
    recipients = [r.to_dict() for r in result.recipients]
    if recipients:
        _store_recipients(recipients)
    return {"recipients": recipients, "errors": result.errors,
            "warnings": result.warnings, "total": len(recipients),
            "variables": collect_vars(recipients)}


@app.get("/api/recipients/last")
def last_recipients():
    cfg = load_config()
    return {"recipients": cfg.last_recipients, "variables": collect_vars(cfg.last_recipients)}


@app.post("/api/recipients/save")
def save_recipients(data: dict):
    _store_recipients(data.get("recipients") or [])
    return {"ok": True}


# ── 预览 / 预检 ──

@app.post("/api/preview")
def preview(data: dict):
    cfg = load_config()
    recipients = _requested_recipients(data, cfg)
    body = data.get("body", cfg.body_template)
    subject = data.get("subject", cfg.subject_template)
    user = data.get("user") or {
        "姓名": cfg.user.name, "学校": cfg.user.school, "专业": cfg.user.major,
        "年级": cfg.user.grade, "电话": cfg.user.phone, "邮箱": cfg.user.email,
    }
    limit = max(1, min(50, int(data.get("limit") or 5)))

    items = []
    for r in recipients[:limit]:
        rendered = render_email(r, user, body, subject)
        items.append({
            "seq": r.get("seq"), "company": r.get("company", ""),
            "email": r.get("email", ""), "subject": rendered["subject"],
            "body": rendered["body"], "html": rendered["html"],
            "vars": r.get("vars") or {},
        })

    unknown = set()
    empty = set()
    for r in recipients:
        ctx = build_context(r, user)
        own_subject = (r.get("subject") or "") or (subject or "")
        unknown |= set(unknown_placeholders(own_subject, ctx))
        unknown |= set(unknown_placeholders(body or "", ctx))
        for name in set(re.findall(r"\{([^{}\r\n]{1,24})\}", own_subject + (body or ""))):
            if name in ctx and not str(ctx[name]).strip():
                empty.add(name)

    contacted = already_contacted()
    dup_in_batch, contacted_hits, seen = [], [], set()
    for r in recipients:
        addr = str(r.get("email", "")).lower()
        if addr in seen:
            dup_in_batch.append(addr)
        seen.add(addr)
        if addr in contacted:
            contacted_hits.append({"email": addr, "company": r.get("company", ""),
                                   "last": contacted[addr]})

    return {
        "items": items,
        "total": len(recipients),
        "unknown_variables": sorted(unknown),
        "empty_variables": sorted(empty),
        "missing_company": [r.get("email") for r in recipients if not r.get("company")],
        "duplicates_in_batch": dup_in_batch,
        "already_contacted": contacted_hits[:50],
        "already_contacted_count": len(contacted_hits),
        "variables": collect_vars(recipients),
        "today": {"sent": sent_today(), "limit": cfg.daily_limit},
        "attachments": [Path(p).name for p in (cfg.last_attachments or [])],
    }


# ── AI ──

def _ai_params(data: dict):
    cfg = load_config()
    provider = data.get("provider") or cfg.ai.provider
    model = data.get("model") or cfg.ai.model
    key = data.get("api_key") or cfg.ai.api_key
    if not provider or not key or not model:
        raise HTTPException(400, "请先配置 AI 提供商、API Key 和模型（保存过即可，不必每次重填）")
    return provider, key, model


@app.post("/api/ai/chat")
def ai_chat_endpoint(data: dict):
    provider, key, model = _ai_params(data)
    messages = data.get("messages") or []
    if not messages:
        raise HTTPException(400, "消息不能为空")
    try:
        return {"ok": True, "content": ai_chat(provider, key, model, messages)}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/api/ai/fill-template")
def ai_fill(data: dict):
    provider, key, model = _ai_params(data)
    text = (data.get("input") or "").strip()
    if not text:
        raise HTTPException(400, "输入内容不能为空")
    try:
        rows = ai_fill_template(provider, key, model, text)
        recipients = []
        for i, r in enumerate(rows if isinstance(rows, list) else []):
            recipients.append({
                "seq": i + 1,
                "company": r.get("company", ""),
                "email": r.get("email", ""),
                "subject": r.get("subject", ""),
                "vars": r.get("vars") or {},
            })
        if recipients:
            _store_recipients(recipients)
        return {"ok": True, "recipients": recipients,
                "variables": collect_vars(recipients)}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/api/ai/generate-body")
def ai_gen_body(data: dict):
    provider, key, model = _ai_params(data)
    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(400, "请输入修改要求")
    cfg = load_config()
    try:
        content = ai_generate_body(provider, key, model, instruction,
                                   current_body=data.get("current_body", cfg.body_template),
                                   user={"姓名": cfg.user.name, "学校": cfg.user.school,
                                         "专业": cfg.user.major, "年级": cfg.user.grade})
        return {"ok": True, "content": content}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


# ── 附件 ──

def _safe_attachment(path: str) -> str:
    """只允许使用上传目录里的文件，防止公开部署时被读任意路径"""
    p = Path(path).resolve()
    root = ATTACH_DIR.resolve()
    if p.parent != root:
        raise HTTPException(400, f"附件路径非法：{Path(path).name}")
    if not p.is_file():
        raise HTTPException(400, f"附件不存在：{Path(path).name}")
    return str(p)


@app.get("/api/attachments")
def list_attachments():
    files = []
    if ATTACH_DIR.exists():
        for f in sorted(ATTACH_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                files.append({"name": f.name, "path": str(f), "size": f.stat().st_size})
    return {"files": files}


@app.post("/api/attachments/upload")
async def upload_attachment(file: UploadFile = File(...)):
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "attachment").name
    save_path = ATTACH_DIR / name
    if save_path.exists():
        save_path = ATTACH_DIR / f"{save_path.stem}_{datetime.now():%H%M%S}{save_path.suffix}"
    content = await file.read()
    if len(content) > MAX_ATTACH_MB * 1024 * 1024:
        raise HTTPException(400, f"单个附件不能超过 {MAX_ATTACH_MB}MB")
    save_path.write_bytes(content)

    cfg = load_config()
    if str(save_path) not in cfg.last_attachments:
        cfg.last_attachments.append(str(save_path))
        save_config(cfg)
    return {"ok": True, "file": {"name": save_path.name, "path": str(save_path),
                                 "size": len(content)}}


@app.delete("/api/attachments/{filename}")
def delete_attachment(filename: str):
    filepath = ATTACH_DIR / Path(filename).name
    if filepath.is_file():
        filepath.unlink()
        cfg = load_config()
        cfg.last_attachments = [p for p in cfg.last_attachments if Path(p).name != filepath.name]
        save_config(cfg)
    return {"ok": True}


# ── 发送 ──

def _requested_recipients(data: dict, cfg) -> list:
    """显式传空列表 = 没有收件人；没传字段才沿用上次的"""
    raw = data["recipients"] if "recipients" in data else cfg.last_recipients
    return raw or []


def _requested_attachments(data: dict, cfg) -> list:
    """显式传空列表 = 不发附件；没传字段 = 沿用上次选择"""
    raw = data["attachments"] if "attachments" in data else cfg.last_attachments
    return [_safe_attachment(p) for p in (raw or [])]


def _check_ready(cfg) -> None:
    if not cfg.email.email or not cfg.email.auth_code:
        raise HTTPException(400, "请先在「邮箱配置」页填写邮箱和授权码")


@app.post("/api/send/test")
def send_to_self(data: dict):
    """先发给自己一封，确认排版和附件名"""
    cfg = load_config()
    _check_ready(cfg)
    recipients = _requested_recipients(data, cfg)
    sample = recipients[0] if recipients else {"company": "示例公司", "email": "", "vars": {}}
    user = data.get("user") or {"姓名": cfg.user.name, "学校": cfg.user.school,
                                "专业": cfg.user.major, "年级": cfg.user.grade,
                                "电话": cfg.user.phone, "邮箱": cfg.user.email}
    rendered = render_email(sample, user, data.get("body", cfg.body_template),
                            data.get("subject", cfg.subject_template))
    attachments = _requested_attachments(data, cfg)
    try:
        addr = send_test(cfg.email, rendered["subject"], rendered["body"],
                         rendered["html"], attachments)
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "msg": f"已发送到 {addr}，请到收件箱确认排版与附件名"}


@app.post("/api/send/start")
def send_start(data: dict):
    cfg = load_config()
    _check_ready(cfg)

    recipients = _requested_recipients(data, cfg)
    if not recipients:
        raise HTTPException(400, "收件人列表为空")
    if len(recipients) > 2000:
        raise HTTPException(400, "单批最多 2000 封，请拆分发送")

    mode = data.get("send_mode", "draft")
    if mode not in ("draft", "send"):
        raise HTTPException(400, "send_mode 只能是 draft 或 send")

    attachments = _requested_attachments(data, cfg)
    body = data.get("body", cfg.body_template)
    subject = data.get("subject", cfg.subject_template)
    rate = int(data.get("rate") or cfg.send_rate or 20)
    daily_limit = int(data.get("daily_limit", cfg.daily_limit) or 0)
    cc_self = bool(data.get("cc_self", cfg.cc_self))

    cfg.last_recipients = recipients
    cfg.last_attachments = attachments
    cfg.body_template = body
    cfg.subject_template = subject
    save_config(cfg)

    user = {"姓名": cfg.user.name, "学校": cfg.user.school, "专业": cfg.user.major,
            "年级": cfg.user.grade, "电话": cfg.user.phone, "邮箱": cfg.user.email}
    try:
        job_id = jobs.start_job(
            cfg_email=cfg.email, recipients=recipients, body=body,
            subject_template=subject, attachments=attachments, mode=mode,
            rate=rate, user_info=user, daily_limit=daily_limit, cc_self=cc_self)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "job_id": job_id, "total": len(recipients),
            "skipped_by_limit": max(0, len(recipients) - max(0, daily_limit - sent_today())) if daily_limit else 0}


@app.get("/api/send/status/{job_id}")
def send_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在（服务重启后任务不保留）")
    return job


@app.post("/api/send/cancel/{job_id}")
def send_cancel(job_id: str):
    ok = jobs.cancel_job(job_id)
    return {"ok": ok, "msg": "已请求取消，当前这封发完即停止" if ok else "任务已结束"}


# ── 日志 / 导出 ──

@app.get("/api/logs")
def get_logs():
    logs = load_log()
    return {"logs": logs[-300:]}


@app.delete("/api/logs")
def clear_logs():
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    return {"ok": True}


@app.get("/api/report/export")
def export_report():
    logs = load_log()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "投递记录"
    headers = ["时间", "公司", "收件人邮箱", "邮件主题", "方式", "结果", "备注"]
    ws.append(headers)
    widths = [20, 28, 34, 44, 10, 8, 40]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color="1A4B8C")
    for e in logs:
        ws.append([
            e.get("time", ""), e.get("company", ""), e.get("email", ""),
            e.get("subject", ""),
            "直接发送" if e.get("mode") == "send" else "存草稿",
            "成功" if e.get("success") else "失败",
            e.get("error", ""),
        ])
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    fname = quote(f"ResumeMailer投递记录-{date.today():%Y%m%d}.xlsx")
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"})


# ── 启动 ──

def start():
    import webbrowser
    port = int(os.environ.get("PORT", 8765))
    host = os.environ.get("HOST", "127.0.0.1")
    is_cloud = host == "0.0.0.0"
    print(f"🚀 ResumeMailer 已启动 → http://localhost:{port}")
    if is_cloud and not ACCESS_TOKEN:
        print("⚠️  公网监听但未设置 RESUMEMAILER_TOKEN，任何人可访问你的配置与附件")
    if not is_cloud:
        webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
