"""ResumeMailer FastAPI 服务端"""
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import load_config, save_config, EmailConfig, AIConfig, ATTACH_DIR, LOG_FILE, DEFAULT_BODY_TEMPLATE
from engine.excel_parser import generate_template, parse_workbook, detect_placeholders
from engine.ai_filler import ai_chat, ai_fill_template, ai_generate_body, get_available_providers
from engine.sender import send_batch, test_connection

app = FastAPI(title="ResumeMailer · 简历投递助手")

# ── 挂载静态文件 ──
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


# ── 配置 API ──

@app.get("/api/config")
def get_config():
    cfg = load_config()
    return {
        "email": {
            "email": cfg.email.email,
            "smtp_host": cfg.email.smtp_host,
            "smtp_port": cfg.email.smtp_port,
            "imap_host": cfg.email.imap_host,
            "imap_port": cfg.email.imap_port,
            "use_ssl": cfg.email.use_ssl,
            "auth_code": bool(cfg.email.auth_code),  # 只返回是否有值
            "sender_name": cfg.email.sender_name,
        },
        "ai": {
            "provider": cfg.ai.provider,
            "api_key": bool(cfg.ai.api_key),
            "model": cfg.ai.model,
        },
        "user": {
            "name": cfg.user.name,
            "school": cfg.user.school,
            "major": cfg.user.major,
            "grade": cfg.user.grade,
            "phone": cfg.user.phone,
            "email": cfg.user.email,
        },
        "body_template": cfg.body_template,
        "send_rate": cfg.send_rate,
        "last_attachments": cfg.last_attachments,
        "ai_providers": get_available_providers(),
    }


@app.post("/api/config/email")
def save_email_config(data: dict):
    cfg = load_config()
    cfg.email.email = data.get("email", cfg.email.email)
    cfg.email.smtp_host = data.get("smtp_host", cfg.email.smtp_host)
    cfg.email.smtp_port = data.get("smtp_port", cfg.email.smtp_port)
    cfg.email.imap_host = data.get("imap_host", cfg.email.imap_host)
    cfg.email.imap_port = data.get("imap_port", cfg.email.imap_port)
    cfg.email.use_ssl = data.get("use_ssl", cfg.email.use_ssl)
    cfg.email.sender_name = data.get("sender_name", cfg.email.sender_name)
    if data.get("auth_code"):
        cfg.email.auth_code = data["auth_code"]
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/ai")
def save_ai_config(data: dict):
    cfg = load_config()
    cfg.ai.provider = data.get("provider", cfg.ai.provider)
    cfg.ai.model = data.get("model", cfg.ai.model)
    if data.get("api_key"):
        cfg.ai.api_key = data["api_key"]
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/body")
def save_body(data: dict):
    cfg = load_config()
    cfg.body_template = data.get("body_template", cfg.body_template)
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/rate")
def save_rate(data: dict):
    cfg = load_config()
    cfg.send_rate = data.get("send_rate", cfg.send_rate)
    save_config(cfg)
    return {"ok": True}


@app.post("/api/config/user")
def save_user_info(data: dict):
    cfg = load_config()
    cfg.user.name = data.get("name", cfg.user.name)
    cfg.user.school = data.get("school", cfg.user.school)
    cfg.user.major = data.get("major", cfg.user.major)
    cfg.user.grade = data.get("grade", cfg.user.grade)
    cfg.user.phone = data.get("phone", cfg.user.phone)
    cfg.user.email = data.get("email", cfg.user.email)
    save_config(cfg)
    return {"ok": True}


# ── 邮箱测试 ──

@app.post("/api/email/test")
def test_email(data: dict):
    ecfg = EmailConfig(
        email=data.get("email", ""),
        smtp_host=data.get("smtp_host", ""),
        smtp_port=data.get("smtp_port", 465),
        imap_host=data.get("imap_host", ""),
        imap_port=data.get("imap_port", 993),
        use_ssl=data.get("use_ssl", True),
        auth_code=data.get("auth_code", ""),
    )
    ok, err = test_connection(ecfg)
    if ok:
        return {"ok": True, "msg": "✅ SMTP + IMAP 连接成功"}
    return JSONResponse(status_code=400, content={"ok": False, "msg": err})


# ── Excel 模板 ──

@app.get("/api/template/download")
def download_template():
    content = generate_template()
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=resume_mailer_template.xlsx"})


@app.post("/api/template/parse")
async def parse_excel(file: UploadFile = File(...)):
    content = await file.read()
    result = parse_workbook(content, file.filename or "")
    return {
        "recipients": [r.__dict__ for r in result.recipients],
        "errors": result.errors,
        "total": len(result.recipients),
    }


# ── AI API ──

@app.post("/api/ai/chat")
def ai_chat_endpoint(data: dict):
    """AI 对话（用于自定义正文等）"""
    cfg = load_config()
    provider = data.get("provider", cfg.ai.provider)
    api_key = data.get("api_key", cfg.ai.api_key)
    model = data.get("model", cfg.ai.model)
    messages = data.get("messages", [])

    if not provider or not api_key or not model:
        raise HTTPException(400, "请先配置 AI 提供商、API Key 和模型")
    if not messages:
        raise HTTPException(400, "消息不能为空")

    try:
        result = ai_chat(provider, api_key, model, messages)
        return {"ok": True, "content": result}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/api/ai/fill-template")
def ai_fill(data: dict):
    """AI 自动填充收件人模板"""
    cfg = load_config()
    provider = data.get("provider", cfg.ai.provider)
    api_key = data.get("api_key", cfg.ai.api_key)
    model = data.get("model", cfg.ai.model)
    user_input = data.get("input", "")

    if not provider or not api_key or not model:
        raise HTTPException(400, "请先配置 AI 提供商、API Key 和模型")
    if not user_input:
        raise HTTPException(400, "输入内容不能为空")

    try:
        result = ai_fill_template(provider, api_key, model, user_input)
        return {"ok": True, "recipients": result}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/api/ai/generate-body")
def ai_gen_body(data: dict):
    """AI 生成正文"""
    cfg = load_config()
    provider = data.get("provider", cfg.ai.provider)
    api_key = data.get("api_key", cfg.ai.api_key)
    model = data.get("model", cfg.ai.model)
    instruction = data.get("instruction", "")

    if not provider or not api_key or not model:
        raise HTTPException(400, "请先配置 AI 提供商、API Key 和模型")
    if not instruction:
        raise HTTPException(400, "请输入修改要求")

    try:
        result = ai_generate_body(provider, api_key, model, instruction)
        return {"ok": True, "content": result}
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


# ── 附件管理 ──

@app.get("/api/attachments")
def list_attachments():
    files = []
    if ATTACH_DIR.exists():
        for f in sorted(ATTACH_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            files.append({"name": f.name, "path": str(f), "size": f.stat().st_size})
    return {"files": files}


@app.post("/api/attachments/upload")
async def upload_attachment(file: UploadFile = File(...)):
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    # 保留原始文件名，避免重名
    save_path = ATTACH_DIR / file.filename
    if save_path.exists():
        name_stem = save_path.stem
        name_suffix = save_path.suffix
        save_path = ATTACH_DIR / f"{name_stem}_{uuid.uuid4().hex[:8]}{name_suffix}"

    content = await file.read()
    save_path.write_bytes(content)

    # 更新 last_attachments
    cfg = load_config()
    if str(save_path) not in cfg.last_attachments:
        cfg.last_attachments.append(str(save_path))
        save_config(cfg)

    return {"ok": True, "file": {"name": save_path.name, "path": str(save_path), "size": len(content)}}


@app.delete("/api/attachments/{filename}")
def delete_attachment(filename: str):
    filepath = ATTACH_DIR / filename
    if filepath.exists():
        filepath.unlink()
        cfg = load_config()
        cfg.last_attachments = [p for p in cfg.last_attachments if Path(p).name != filename]
        save_config(cfg)
    return {"ok": True}


# ── 发送 ──

@app.post("/api/send")
def send_emails(data: dict):
    """批量发送邮件"""
    cfg = load_config()
    if not cfg.email.email or not cfg.email.auth_code:
        raise HTTPException(400, "请先配置邮箱和授权码")

    recipients = data.get("recipients", [])
    body = data.get("body", cfg.body_template)
    attachments = data.get("attachments", cfg.last_attachments)
    send_mode = data.get("send_mode", "draft")  # "draft" or "send"
    rate = data.get("rate", cfg.send_rate)

    if not recipients:
        raise HTTPException(400, "收件人列表为空")

    if send_mode == "send":
        # ⚠️ 前端已经做3次确认了，后端不再重复
        pass

    try:
        results = send_batch(
            cfg=cfg.email,
            recipients=recipients,
            body=body,
            attachments=attachments,
            send_mode=send_mode,
            rate=rate,
            user_info={
                "姓名": cfg.user.name,
                "学校": cfg.user.school,
                "专业": cfg.user.major,
                "年级": cfg.user.grade,
                "电话": cfg.user.phone,
                "邮箱": cfg.user.email,
            },
        )

        # 记录日志
        from config import append_log
        for r in results:
            append_log({
                "time": __import__("datetime").datetime.now().isoformat(),
                "company": r["company"],
                "email": r["email"],
                "success": r["success"],
                "error": r["error"],
                "mode": send_mode,
            })

        success_count = sum(1 for r in results if r["success"])
        return {
            "ok": True,
            "results": results,
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# ── 日志 ──

@app.get("/api/logs")
def get_logs():
    try:
        if LOG_FILE.exists():
            logs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        else:
            logs = []
        return {"logs": logs[-200:]}  # 最近200条
    except Exception:
        return {"logs": []}


@app.delete("/api/logs")
def clear_logs():
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    return {"ok": True}


# ── 启动 ──

def start():
    import webbrowser
    port = int(os.environ.get("PORT", 8765))
    print(f"🚀 ResumeMailer 已启动 → http://localhost:{port}")
    webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
