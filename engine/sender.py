"""发送引擎 — SMTP 直发 / IMAP 存草稿

相对旧版的改动（每一条都对应一个真实翻车场景）：
1. 主题也做变量替换（旧版只替换正文，HR 看到的是 {公司名}）
2. 整个批次复用一条 SMTP / IMAP 连接（旧版每封登录一次，50 封就被限流）
3. 草稿箱自动探测（Gmail=[Gmail]/Drafts、163=草稿箱、QQ=Drafts）
4. Date / Message-ID 头齐全，中文发件人和中文附件名按标准编码
5. 正文同时发纯文本 + HTML（客户端排版不会挤成一坨）
6. 临时性网络错误自动重连重试，认证/拒收错误立即失败，不浪费额度
7. 每日上限（QQ 个人邮箱约 50 封/天）到顶就停下并说明原因
8. 支持取消
"""
import base64
import imaplib
import mimetypes
import random
import re
import smtplib
import socket
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Callable, List, Optional

from config import EmailConfig
from engine.render import render_email

MAX_ATTACH_MB = 25          # 多数邮箱单封上限 25MB（base64 后约 33MB）
MAX_MESSAGES_PER_CONN = 50  # 单条连接发多少封后主动重连一次


class SendCancelled(Exception):
    pass


def _imap_utf7(name: str) -> str:
    """IMAP 文件夹名的 modified UTF-7 编码（163 的「草稿箱」需要）"""
    if all(0x20 <= ord(c) <= 0x7E for c in name):
        return name
    out, buf = [], []

    def flush():
        if buf:
            raw = "".join(buf).encode("utf-16-be")
            b64 = base64.b64encode(raw).decode().rstrip("=").replace("/", ",")
            out.append("&" + b64 + "-")
            buf.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def _imap_utf7_decode(name: str) -> str:
    """modified UTF-7 → Unicode，用于识别 &Xxx- 形式的草稿箱名"""
    out, i = [], 0
    while i < len(name):
        if name[i] != "&":
            out.append(name[i])
            i += 1
            continue
        j = name.find("-", i)
        if j == -1:
            out.append(name[i:])
            break
        chunk = name[i + 1:j]
        if not chunk:
            out.append("&")
        else:
            try:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            except Exception:
                out.append(name[i:j + 1])
        i = j + 1
    return "".join(out)


def _attachment_total_mb(paths: List[str]) -> float:
    total = 0
    for p in paths or []:
        try:
            total += Path(p).stat().st_size
        except OSError:
            continue
    return total / 1024 / 1024


def build_message(cfg: EmailConfig, to_addr: str, subject: str, body: str, html: str,
                  attachments: List[str], cc_self: bool = False) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.sender_name.strip(), cfg.email))
    msg["To"] = to_addr
    if cc_self:
        msg["Cc"] = cfg.email
    msg["Subject"] = subject or "(无主题)"
    msg["Date"] = formatdate(localtime=True)
    domain = cfg.email.split("@")[-1] if "@" in cfg.email else "resumemailer.local"
    msg["Message-ID"] = make_msgid(domain=domain)

    msg.set_content(body or "")
    if html and html.strip() != (body or "").strip():
        msg.add_alternative(html, subtype="html")

    for filepath in attachments or []:
        path = Path(filepath)
        if not path.is_file():
            continue
        ctype, _ = mimetypes.guess_type(path.name)
        if ctype and "/" in ctype:
            maintype, subtype = ctype.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=path.name)
    return msg


class _SmtpLink:
    """一条可复用的 SMTP 连接"""

    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        self.conn = None
        self.count = 0

    def _connect(self):
        c = self.cfg
        if c.use_ssl:
            conn = smtplib.SMTP_SSL(c.smtp_host, int(c.smtp_port), timeout=30)
        else:
            conn = smtplib.SMTP(c.smtp_host, int(c.smtp_port), timeout=30)
            conn.ehlo()
            conn.starttls()
        conn.login(c.email, c.auth_code)
        self.conn, self.count = conn, 0
        return conn

    def get(self):
        if self.conn is None or self.count >= MAX_MESSAGES_PER_CONN:
            self.close()
            self._connect()
        return self.conn

    def close(self):
        if self.conn is not None:
            try:
                self.conn.quit()
            except Exception:
                try:
                    self.conn.close()
                except Exception:
                    pass
            self.conn = None

    def send(self, msg: EmailMessage):
        last = None
        for attempt in range(3):
            try:
                self.get().send_message(msg)
                self.count += 1
                return
            except smtplib.SMTPAuthenticationError:
                raise                       # 授权码错了，重试没意义
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
                raise                       # 地址被拒，重试没意义
            except smtplib.SMTPDataError as e:
                if e.smtp_code >= 500 or attempt >= 2:
                    raise
                last = e
                self.close()
                time.sleep(2 + attempt * 2)
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                    smtplib.SMTPHeloError,
                    socket.timeout, TimeoutError, ConnectionError) as e:
                last = e
                self.close()
                if attempt < 2:
                    time.sleep(2 + attempt * 2)
        raise last if last else RuntimeError("SMTP 发送失败")


class _DraftSink:
    """IMAP 草稿箱，自动探测真实文件夹名"""

    CANDIDATES = ["Drafts", "草稿箱", "Draft", "[Gmail]/Drafts", "INBOX.Drafts", "已草稿"]

    def __init__(self, cfg: EmailConfig):
        self.cfg = cfg
        self.conn = None
        self.box = None

    def _connect(self):
        c = self.cfg
        conn = imaplib.IMAP4_SSL(c.imap_host, int(c.imap_port), timeout=30)
        conn.login(c.email, c.auth_code)
        self.conn = conn
        return conn

    def _boxes(self):
        """按可能性排序的草稿箱候选名（已做 UTF-7 编码）"""
        found = []
        try:
            typ, data = self.conn.list()
            for raw in data or []:
                line = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
                m = re.search(r'"([^"]*)"\s*$', line) or re.search(r"(\S+)\s*$", line)
                if not m:
                    continue
                raw_name = m.group(1)
                name = _imap_utf7_decode(raw_name)   # &g0l6P3ux- → 草稿箱
                low = name.lower()
                if any(k in low for k in ("draft", "草稿", "下書き", "borrador", "brouillon")):
                    found.append(name)
        except Exception:
            pass
        ordered = found + [b for b in self.CANDIDATES if b not in found]
        seen, out = set(), []
        for b in ordered:
            enc = _imap_utf7(b)
            if enc not in seen:
                seen.add(enc)
                out.append(enc)
        return out

    def append(self, msg: EmailMessage):
        if self.conn is None:
            self._connect()
        raw = msg.as_bytes()
        date_str = imaplib.Time2Internaldate(time.time())
        candidates = [self.box] if self.box else self._boxes()
        last = None
        for name in candidates:
            for attempt in range(2):
                try:
                    typ, data = self.conn.append(f'"{name}"', "\\Draft", date_str, raw)
                    if typ == "OK":
                        self.box = name
                        return
                    last = data
                    break
                except imaplib.IMAP4.abort:
                    # 长批次中途连接被服务端断开：重连后把这一封补存一次
                    try:
                        self._connect()
                    except Exception as e:
                        raise imaplib.IMAP4.error(f"IMAP 重连失败：{e}")
                    last = "连接中断"
                    if attempt == 1:
                        break
                except imaplib.IMAP4.error as e:
                    last = e
                    break
        raise imaplib.IMAP4.error(
            f"没有找到草稿箱（试过 {', '.join(candidates[:4])}）。"
            f"该邮箱可能未开启 IMAP，或草稿箱名称特殊。详情：{last}")

    def close(self):
        if self.conn is not None:
            try:
                self.conn.logout()
            except Exception:
                pass
            self.conn = None


def test_connection(cfg: EmailConfig) -> tuple:
    """测试 SMTP + IMAP 连接，返回 (ok, msg)"""
    try:
        if cfg.use_ssl:
            s = smtplib.SMTP_SSL(cfg.smtp_host, int(cfg.smtp_port), timeout=10)
        else:
            s = smtplib.SMTP(cfg.smtp_host, int(cfg.smtp_port), timeout=10)
            s.starttls()
        s.login(cfg.email, cfg.auth_code)
        s.quit()
    except smtplib.SMTPAuthenticationError:
        return (False, "SMTP 认证失败：邮箱或授权码不对（注意不是登录密码，要用授权码）")
    except Exception as e:
        return (False, f"SMTP 连接失败：{e}")

    try:
        conn = imaplib.IMAP4_SSL(cfg.imap_host, int(cfg.imap_port), timeout=10)
        conn.login(cfg.email, cfg.auth_code)
        conn.logout()
    except Exception as e:
        return (False, f"SMTP 正常，IMAP 连接失败：{e}（只发不存草稿可忽略）")

    return (True, "SMTP + IMAP 连接成功")


def _friendly_error(e: Exception) -> str:
    """把底层网络异常翻译成用户能动手解决的话"""
    text = str(e)
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "认证失败：邮箱或授权码不对（不是登录密码，要去邮箱设置里生成授权码）"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return f"收件人地址被服务器拒绝：{text[:200]}"
    if isinstance(e, socket.gaierror):
        return "服务器地址解析失败，检查 SMTP/IMAP 主机名是否填错"
    if isinstance(e, ConnectionRefusedError) or "Errno 61" in text or "Connection refused" in text:
        return "连接被拒绝：主机或端口不对（SSL 一般 465，STARTTLS 一般 587/25）"
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in text:
        return "连接超时：网络不通或端口被防火墙拦截，换个网络试试"
    return text[:300]


def send_test(cfg: EmailConfig, subject: str, body: str, html: str,
              attachments: List[str] = None, cc_self: bool = False) -> str:
    """发给自己一封，用于确认排版/附件名。返回收件地址。"""
    link = _SmtpLink(cfg)
    try:
        msg = build_message(cfg, cfg.email, f"[测试] {subject}", body, html,
                            attachments or [], cc_self)
        link.send(msg)
    except Exception as e:
        raise RuntimeError(_friendly_error(e))
    finally:
        link.close()
    return cfg.email


def send_batch(
    cfg: EmailConfig,
    recipients: list,
    body: str,
    subject_template: str = "",
    attachments: List[str] = None,
    send_mode: str = "draft",          # "draft" | "send"
    rate: int = 20,
    user_info: dict = None,
    daily_limit: int = 0,
    daily_sent: int = 0,
    cc_self: bool = False,
    progress: Optional[Callable[[dict], None]] = None,
    cancel=None,
) -> dict:
    """
    批量投递。返回 {"results": [...], "stopped": str, "draft_box": str}
    单封结果：{company,email,subject,success,status,error}
    status: sent / draft / failed / skipped
    """
    attachments = attachments or []
    total = len(recipients)
    results = []
    stopped = ""
    draft_box = ""

    if _attachment_total_mb(attachments) > MAX_ATTACH_MB:
        raise ValueError(f"附件总大小超过 {MAX_ATTACH_MB}MB（{_attachment_total_mb(attachments):.1f}MB），"
                         f"多数邮箱会直接退回，请压缩后重试")

    is_dry = send_mode == "dry"
    interval = 0 if is_dry else 60.0 / max(1, int(rate or 20))
    link = _SmtpLink(cfg) if send_mode == "send" else None
    sink = _DraftSink(cfg) if send_mode == "draft" else None
    sent_this_run = 0
    started = time.monotonic()

    def emit(result):
        results.append(result)
        if progress:
            try:
                progress(result)
            except Exception:
                pass

    try:
        for idx, r in enumerate(recipients):
            if cancel is not None and cancel.is_set():
                stopped = "已取消"
                for rest in recipients[idx:]:
                    emit({"company": rest.get("company", ""), "email": rest.get("email", ""),
                          "subject": "", "success": False, "status": "skipped",
                          "error": "已取消，未发送"})
                break

            if not is_dry and daily_limit and (daily_sent + sent_this_run) >= daily_limit:
                stopped = f"已达每日上限 {daily_limit} 封，剩余 {total - idx} 封未发"
                for rest in recipients[idx:]:
                    emit({"company": rest.get("company", ""), "email": rest.get("email", ""),
                          "subject": "", "success": False, "status": "skipped",
                          "error": stopped})
                break

            if r.get("skip_reason"):
                emit({"company": r.get("company", ""), "email": r.get("email", ""),
                      "subject": "", "success": False, "status": "skipped",
                      "error": r["skip_reason"]})
                continue

            rendered = render_email(r, user_info or {}, body, subject_template)
            to_addr = r.get("email", "")
            result = {"company": r.get("company", ""), "email": to_addr,
                      "subject": rendered["subject"], "success": False,
                      "status": "failed", "error": ""}
            try:
                msg = build_message(cfg, to_addr, rendered["subject"], rendered["body"],
                                    rendered["html"], attachments, cc_self)
                result["message_id"] = msg.get("Message-ID", "")
                if is_dry:
                    # 试跑：消息真的组装好了（附件可读、编码正确），但不发出去
                    result.update(success=True, status="dry")
                    time.sleep(0.15)
                elif send_mode == "send":
                    link.send(msg)
                    result.update(success=True, status="sent")
                    sent_this_run += 1
                else:
                    sink.append(msg)
                    result.update(success=True, status="draft")
                    draft_box = sink.box or ""
            except smtplib.SMTPAuthenticationError:
                result["error"] = "认证失败：邮箱或授权码不对，整批已停止"
                emit(result)
                stopped = result["error"]
                for rest in recipients[idx + 1:]:
                    emit({"company": rest.get("company", ""), "email": rest.get("email", ""),
                          "subject": "", "success": False, "status": "skipped",
                          "error": "前一封认证失败，已停止"})
                break
            except Exception as e:
                result["error"] = _friendly_error(e)
            emit(result)

            # 限速：按整批起点排程，不累积漂移；±15% 抖动，别像机器人
            if idx < total - 1 and interval > 0:
                target = started + (idx + 1) * interval
                wait = target - time.monotonic()
                if wait > 0:
                    wait *= random.uniform(0.85, 1.15)
                    end = time.monotonic() + wait
                    while time.monotonic() < end:
                        if cancel is not None and cancel.is_set():
                            break
                        time.sleep(min(0.3, end - time.monotonic()))
    finally:
        if link:
            link.close()
        if sink:
            sink.close()

    return {"results": results, "stopped": stopped, "draft_box": draft_box}
