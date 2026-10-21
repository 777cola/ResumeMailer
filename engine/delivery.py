"""投递状态 — 谁投过、谁回信了、谁的地址是死的

只存"事件"（退信 / 回复），"已投递"从发送日志里算，避免两份数据打架。
状态优先级：已回复 > 退信 > 已投递。
"""
import json
import os
from datetime import datetime
from pathlib import Path

from config import CONFIG_DIR

FILE = CONFIG_DIR / "delivery.json"
MAX_SEEN = 2000


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict:
    if not FILE.exists():
        return {"bounced": {}, "replied": {}, "seen": [], "last_scan": ""}
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"bounced": {}, "replied": {}, "seen": [], "last_scan": ""}
    data.setdefault("bounced", {})
    data.setdefault("replied", {})
    data.setdefault("seen", [])
    data.setdefault("last_scan", "")
    return data


def _save(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, FILE)
    try:
        os.chmod(FILE, 0o600)   # 里面是 HR 的邮箱地址，按隐私数据对待
    except OSError:
        pass


def dead_emails() -> dict:
    """退信过的地址 → 原因"""
    return {a: v.get("reason", "") for a, v in _load()["bounced"].items()}


def last_scan() -> str:
    return _load().get("last_scan", "")


def apply_scan(bounces: list, replies: list) -> dict:
    """把一次扫描结果并入状态库，返回新增数量"""
    data = _load()
    new_bounce = new_reply = 0
    for b in bounces:
        addr = (b.get("email") or "").lower()
        if not addr:
            continue
        if addr not in data["bounced"]:
            new_bounce += 1
        data["bounced"][addr] = {
            "reason": (b.get("reason") or "")[:300],
            "status": b.get("status", ""),
            "at": b.get("date") or _now(),
        }
        data["replied"].pop(addr, None)   # 退信说明地址死了，不算回复
    for r in replies:
        addr = (r.get("email") or "").lower()
        if not addr:
            continue
        if addr not in data["replied"]:
            new_reply += 1
        # 对方回信说明地址是活的，之前那次退信作废
        data["bounced"].pop(addr, None)
        data["replied"][addr] = {"at": r.get("date") or _now(),
                                 "subject": (r.get("subject") or "")[:200]}
    data["last_scan"] = _now()
    _save(data)
    return {"new_bounced": new_bounce, "new_replied": new_reply}


def contacts_view(logs: list) -> list:
    """合并发送日志与退信/回复事件，给界面用"""
    data = _load()
    table = {}
    for e in logs or []:
        if not e.get("success"):
            continue
        for addr in str(e.get("email", "")).lower().split(","):
            addr = addr.strip()
            if not addr:
                continue
            row = table.setdefault(addr, {"email": addr, "company": e.get("company", ""),
                                          "sent_at": "", "sent_count": 0})
            row["sent_count"] += 1
            row["sent_at"] = max(row["sent_at"], str(e.get("time", "")))
            if not row["company"]:
                row["company"] = e.get("company", "")

    for addr, info in data["bounced"].items():
        row = table.setdefault(addr, {"email": addr, "company": "", "sent_at": "", "sent_count": 0})
        row.update(status="bounced", detail=info.get("reason", ""),
                   event_at=info.get("at", ""))
    for addr, info in data["replied"].items():
        row = table.setdefault(addr, {"email": addr, "company": "", "sent_at": "", "sent_count": 0})
        row.update(status="replied", detail=info.get("subject", ""),
                   event_at=info.get("at", ""))

    for row in table.values():
        if "status" not in row:
            row["status"] = "sent"
            row["detail"] = ""
            row["event_at"] = ""
    return sorted(table.values(), key=lambda r: (r["status"] != "replied",
                                                 r["sent_at"]), reverse=True)
