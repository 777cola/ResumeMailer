"""收件箱扫描 — 退信（dead address）与回复（对方回信了）

只读 INBOX，不改邮件状态（用 BODY.PEEK），不会把未读改成已读。
"""
import imaplib
import re
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "mail-daemon", "mailerdaemon")
BOUNCE_SUBJECT = re.compile(
    r"(undeliver|delivery (status|failure|has failed)|mail delivery failed|"
    r"returned mail|failure notice|无法投递|投递失败|退信|未送达|退件|发送失败)",
    re.I)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _fetch_bytes(resp) -> bytes:
    for part in resp or []:
        if isinstance(part, tuple) and len(part) >= 2:
            return part[1] or b""
    return b""


def _iso_date(msg) -> str:
    raw = str(msg.get("Date", "") or "")
    try:
        return parsedate_to_datetime(raw).isoformat(timespec="seconds")
    except Exception:
        return raw[:40]


def looks_like_bounce(from_hdr: str, subject: str) -> bool:
    f = (from_hdr or "").lower()
    if any(s in f for s in BOUNCE_SENDERS):
        return True
    return bool(BOUNCE_SUBJECT.search(subject or ""))


def parse_dsn(msg) -> list:
    """从投递状态报告里取出失败地址"""
    out = []
    for part in msg.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        if not isinstance(payload, list):
            continue
        action, status = "", ""
        for sub in payload:
            try:
                a = str(sub.get("Action", "") or "").lower()
                st = str(sub.get("Status", "") or "")
                if a:
                    action = a
                if st:
                    status = st
                rec = sub.get("Final-Recipient") or sub.get("Original-Recipient") or ""
                if not rec:
                    continue
                addr = rec.split(";")[-1].strip().strip("<>").lower()
                if not _EMAIL_RE.fullmatch(addr):
                    continue
                if action in ("failed", "delayed") or status.startswith("5"):
                    diag = str(sub.get("Diagnostic-Code", "") or sub.get("Remote-MTA", "") or "")
                    out.append({"email": addr, "status": status or action,
                                "reason": diag.strip()[:300]})
            except Exception:
                continue
    return out


def _text_of(msg) -> str:
    chunks = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            try:
                chunks.append(part.get_content())
            except Exception:
                continue
    return "\n".join(chunks)


def parse_bounce_message(msg, own_addr: str = "") -> list:
    """DSN 解析失败时，从正文里兜底找地址"""
    found = parse_dsn(msg)
    if found:
        return found
    text = _text_of(msg)
    if not text:
        return []
    addrs = []
    for a in _EMAIL_RE.findall(text):
        a = a.lower()
        if a == own_addr.lower() or a in addrs:
            continue
        addrs.append(a)
    # 退信正文里通常只有一两个地址；取前两个，避免把整段名单都当成失败
    return [{"email": a, "status": "5.x", "reason": "退信邮件正文（未能解析 DSN）"}
            for a in addrs[:2]]


def _msg_ids(header_value) -> list:
    return re.findall(r"<[^<>\s]+>", str(header_value or ""))


def scan_inbox(cfg, contacted=None, days: int = 14, max_msgs: int = 200,
               conn=None, msgids: dict = None) -> dict:
    """
    扫描 INBOX：找出退信地址与对方回信。
    contacted: 已投递过的地址集合（只在这些地址里判断「回复」）
    msgids: {我们发出的 Message-ID: 收件人地址}，用于识别换了发件地址的回信
    返回 {scanned, bounces, replies, errors}
    """
    contacted = {a.lower() for a in (contacted or set())}
    msgids = msgids or {}
    own = (cfg.email or "").lower()
    errors, bounces, replies = [], [], []
    owns_conn = conn is None
    scanned = 0
    try:
        if conn is None:
            conn = imaplib.IMAP4_SSL(cfg.imap_host, int(cfg.imap_port), timeout=30)
            conn.login(cfg.email, cfg.auth_code)
        try:
            conn.select("INBOX", readonly=True)
        except Exception as e:
            errors.append(f"打开收件箱失败：{e}")
            return {"scanned": 0, "bounces": [], "replies": [], "errors": errors}

        since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = conn.search(None, f"(SINCE {since})")
        uids = (data[0].split() if data and data[0] else [])[-max_msgs:]

        for uid in uids:
            try:
                typ, resp = conn.fetch(uid, "(BODY.PEEK[HEADER])")
                raw = _fetch_bytes(resp)
                if not raw:
                    continue
                head = BytesParser(policy=policy.default).parsebytes(raw)
                scanned += 1
                from_hdr = str(head.get("From", "") or "")
                subject = str(head.get("Subject", "") or "")
                if looks_like_bounce(from_hdr, subject):
                    typ, full = conn.fetch(uid, "(BODY.PEEK[])")
                    msg = BytesParser(policy=policy.default).parsebytes(_fetch_bytes(full))
                    for b in parse_bounce_message(msg, own):
                        b["date"] = _iso_date(msg)
                        b["subject"] = subject[:120]
                        bounces.append(b)
                    continue
                addr = parseaddr(from_hdr)[1].lower()
                matched = ""
                if addr and addr in contacted and addr != own:
                    matched = addr
                if not matched and msgids:
                    for ref in (_msg_ids(head.get("In-Reply-To"))
                                + _msg_ids(head.get("References"))):
                        target = msgids.get(ref) or msgids.get(ref.strip("<>"))
                        if target:
                            matched = target.lower()
                            break
                if matched:
                    replies.append({"email": matched, "subject": subject[:200],
                                    "date": _iso_date(head)})
            except Exception as e:
                errors.append(f"处理第 {uid.decode(errors='ignore')} 封失败：{e}")
    except Exception as e:
        errors.append(f"IMAP 连接失败：{e}")
    finally:
        if owns_conn and conn is not None:
            try:
                conn.logout()
            except Exception:
                pass

    # 同一地址多次退信只留一条
    uniq = {}
    for b in bounces:
        uniq.setdefault(b["email"], b)
    return {"scanned": scanned, "bounces": list(uniq.values()),
            "replies": replies, "errors": errors}
