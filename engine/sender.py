"""发送引擎 — SMTP 直接发送 + IMAP 存草稿 + 频率控制"""
import smtplib
import imaplib
import email
import time
import asyncio
import json
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import List, Optional, Callable

from config import EmailConfig


def _build_message(
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    attachments: List[str] = None,
    sender_name: str = "",
) -> MIMEMultipart:
    """构建 MIME 邮件"""
    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{from_addr}>" if sender_name else from_addr
    msg["To"] = to_addr
    msg["Subject"] = Header(subject, "utf-8")

    # 正文
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # 附件
    for filepath in (attachments or []):
        path = Path(filepath)
        if not path.exists():
            continue
        with open(path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename=\"{Header(path.name, 'utf-8').encode()}\"",
            )
            msg.attach(part)

    return msg


def _send_via_smtp(cfg: EmailConfig, msg: MIMEMultipart) -> None:
    """通过 SMTP 直接发送"""
    if cfg.use_ssl:
        server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        server.starttls()

    server.login(cfg.email, cfg.auth_code)
    server.send_message(msg)
    server.quit()


def _save_as_draft(cfg: EmailConfig, msg: MIMEMultipart) -> None:
    """通过 IMAP 保存到草稿箱"""
    conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
    conn.login(cfg.email, cfg.auth_code)
    conn.append("Drafts", "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    conn.logout()


# 发送状态回调: (current, total, company, status, error_msg)
ProgressCallback = Callable[[int, int, str, str, Optional[str]], None]


def send_batch(
    cfg: EmailConfig,
    recipients: list,
    body: str,
    attachments: List[str],
    send_mode: str = "draft",      # "draft" or "send"
    rate: int = 20,                # 封/分钟
    user_info: dict = None,        # 用户个人信息变量
    progress: ProgressCallback = None,
) -> list:
    """
    批量发送邮件。
    recipients: [{"company":..., "email":..., "subject":...}, ...]
    send_mode: "draft"=存草稿, "send"=直接发送
    rate: 每分钟发送上限
    返回: [{"company":..., "email":..., "success":bool, "error":str}, ...]
    """
    results = []
    total = len(recipients)
    interval = 60.0 / rate  # 每封间隔秒数

    for idx, r in enumerate(recipients):
        # 变量替换：收件人级别的 {公司名}
        rendered_body = body.replace("{公司名}", r.get("company", ""))
        # 变量替换：用户个人信息（跨所有收件人一致）
        if user_info:
            for key, val in user_info.items():
                rendered_body = rendered_body.replace("{" + key + "}", val or "")
        rendered_subject = r.get("subject", "")

        msg = _build_message(
            from_addr=cfg.email,
            to_addr=r["email"],
            subject=rendered_subject,
            body=rendered_body,
            attachments=attachments,
            sender_name=cfg.sender_name,
        )

        result = {"company": r.get("company", ""), "email": r["email"], "success": False, "error": ""}
        try:
            if send_mode == "send":
                _send_via_smtp(cfg, msg)
            else:
                _save_as_draft(cfg, msg)
            result["success"] = True
            if progress:
                progress(idx + 1, total, r.get("company", ""), "✅ 成功" if send_mode == "send" else "✅ 已存草稿", None)
        except smtplib.SMTPAuthenticationError:
            result["error"] = "SMTP 认证失败，请检查邮箱和授权码"
            if progress:
                progress(idx + 1, total, r.get("company", ""), "❌ 认证失败", result["error"])
        except imaplib.IMAP4.error as e:
            result["error"] = f"IMAP 错误: {e}"
            if progress:
                progress(idx + 1, total, r.get("company", ""), "❌ IMAP失败", result["error"])
        except Exception as e:
            result["error"] = str(e)
            if progress:
                progress(idx + 1, total, r.get("company", ""), "❌ 失败", result["error"])

        results.append(result)

        # 频率控制：除最后一封外，按间隔等待
        if idx < total - 1 and interval > 0:
            time.sleep(interval)

    return results


async def send_batch_async(
    cfg: EmailConfig,
    recipients: list,
    body: str,
    attachments: List[str],
    send_mode: str = "draft",
    rate: int = 20,
) -> list:
    """异步包装，将同步发送放到线程中"""
    loop = asyncio.get_event_loop()
    # 使用 Queue 进行进度通信
    return await loop.run_in_executor(
        None,
        send_batch,
        cfg, recipients, body, attachments, send_mode, rate, None,
    )


def test_connection(cfg: EmailConfig) -> tuple:
    """测试 SMTP 和 IMAP 连接，返回 (success, error_msg)"""
    # 测试 SMTP
    try:
        if cfg.use_ssl:
            s = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=10)
        else:
            s = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10)
            s.starttls()
        s.login(cfg.email, cfg.auth_code)
        s.quit()
    except Exception as e:
        return (False, f"SMTP 连接失败: {e}")

    # 测试 IMAP
    try:
        conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port, timeout=10)
        conn.login(cfg.email, cfg.auth_code)
        conn.logout()
    except Exception as e:
        return (False, f"IMAP 连接失败: {e}")

    return (True, "")
