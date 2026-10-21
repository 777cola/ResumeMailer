"""后台发送任务

旧版把整个批次塞在 HTTP 请求里同步跑：50 封 = 2 分钟，浏览器转圈，
Render 30 秒就断，还没法看进度、没法取消。这里改成线程 + 轮询。
"""
import threading
import uuid
from datetime import datetime

from config import append_logs, sent_today
from engine.sender import send_batch

_JOBS = {}
_LOCK = threading.Lock()
_ACTIVE = {"id": None}
MAX_JOBS = 20


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _snapshot(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],
        "mode": job["mode"],
        "total": job["total"],
        "done": job["done"],
        "success": job["success"],
        "failed": job["failed"],
        "skipped": job["skipped"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "error": job["error"],
        "stopped": job["stopped"],
        "draft_box": job["draft_box"],
        "results": job["results"][-200:],
    }


def active_job_id():
    return _ACTIVE["id"]


def get_job(job_id: str):
    job = _JOBS.get(job_id)
    return _snapshot(job) if job else None


def cancel_job(job_id: str) -> bool:
    job = _JOBS.get(job_id)
    if not job or job["status"] != "running":
        return False
    job["cancel"].set()
    return True


def _run(job: dict, cfg_email, recipients, body, subject_template, attachments,
         rate, user_info, daily_limit, cc_self):
    logs = []

    def on_result(r):
        if r["status"] in ("sent", "draft", "dry"):
            job["success"] += 1
        elif r["status"] == "skipped":
            job["skipped"] += 1
        else:
            job["failed"] += 1
        job["done"] += 1
        job["results"].append(r)
        logs.append({
            "time": _now_iso(),
            "company": r.get("company", ""),
            "email": r.get("email", ""),
            "subject": r.get("subject", ""),
            "message_id": r.get("message_id", ""),
            "success": r.get("success", False),
            "status": r.get("status", ""),
            "error": r.get("error", ""),
            "mode": job["mode"],
            "job": job["id"],
        })

    try:
        out = send_batch(
            cfg=cfg_email,
            recipients=recipients,
            body=body,
            subject_template=subject_template,
            attachments=attachments,
            send_mode=job["mode"],
            rate=rate,
            user_info=user_info,
            daily_limit=daily_limit,
            daily_sent=sent_today(),
            cc_self=cc_self,
            progress=on_result,
            cancel=job["cancel"],
        )
        job["stopped"] = out.get("stopped") or ""
        job["draft_box"] = out.get("draft_box") or ""
        job["status"] = "cancelled" if job["cancel"].is_set() else "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)[:500]
    finally:
        if job["mode"] != "dry":
            append_logs(logs)
        job["finished_at"] = _now_iso()
        with _LOCK:
            if _ACTIVE["id"] == job["id"]:
                _ACTIVE["id"] = None


def start_job(cfg_email, recipients, body, subject_template="", attachments=None,
              mode="draft", rate=20, user_info=None, daily_limit=0, cc_self=False) -> str:
    with _LOCK:
        if _ACTIVE["id"]:
            cur = _JOBS.get(_ACTIVE["id"])
            if cur and cur["status"] == "running":
                raise RuntimeError("已有批次正在发送，请等它结束或先取消")
        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "status": "running", "mode": mode,
            "total": len(recipients), "done": 0, "success": 0,
            "failed": 0, "skipped": 0,
            "started_at": _now_iso(), "finished_at": "", "error": "",
            "stopped": "", "draft_box": "", "results": [],
            "cancel": threading.Event(),
        }
        _JOBS[job_id] = job
        _ACTIVE["id"] = job_id
        # 只保留最近若干个，防止长时间运行后内存堆积
        if len(_JOBS) > MAX_JOBS:
            for old in sorted(_JOBS.values(), key=lambda j: j["started_at"])[:-MAX_JOBS]:
                if old["status"] != "running":
                    _JOBS.pop(old["id"], None)

    t = threading.Thread(
        target=_run,
        args=(job, cfg_email, recipients, body, subject_template,
              attachments or [], rate, user_info, daily_limit, cc_self),
        daemon=True,
    )
    t.start()
    return job_id
