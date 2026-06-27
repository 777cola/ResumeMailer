"""ResumeMailer 配置管理 — 本地 JSON 存储"""
import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

CONFIG_DIR = Path.home() / ".resumemailer"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "send_log.json"
ATTACH_DIR = CONFIG_DIR / "attachments"

# 常见邮箱预设
EMAIL_PRESETS = {
    "QQ邮箱":     {"smtp_host": "smtp.qq.com",     "smtp_port": 465, "imap_host": "imap.qq.com",     "imap_port": 993, "use_ssl": True},
    "163邮箱":    {"smtp_host": "smtp.163.com",    "smtp_port": 465, "imap_host": "imap.163.com",    "imap_port": 993, "use_ssl": True},
    "126邮箱":    {"smtp_host": "smtp.126.com",    "smtp_port": 465, "imap_host": "imap.126.com",    "imap_port": 993, "use_ssl": True},
    "Gmail":      {"smtp_host": "smtp.gmail.com",  "smtp_port": 465, "imap_host": "imap.gmail.com",  "imap_port": 993, "use_ssl": True},
    "Outlook":    {"smtp_host": "smtp.office365.com","smtp_port": 587,"imap_host": "outlook.office365.com","imap_port": 993,"use_ssl": False},
    "Foxmail":    {"smtp_host": "smtp.qq.com",     "smtp_port": 465, "imap_host": "imap.qq.com",     "imap_port": 993, "use_ssl": True},
}

# AI 模型预设（2026年6月更新）
AI_PRESETS = {
    "DeepSeek":  {"base_url": "https://api.deepseek.com/v1",         "models": ["deepseek-chat","deepseek-reasoner"]},
    "GLM (智谱)":{"base_url": "https://open.bigmodel.cn/api/paas/v4","models": ["glm-4-plus","glm-4-air-0111","glm-4-flash"]},
    "MIMO":      {"base_url": "https://api.xiaomimimo.com/v1",       "models": ["mimo-v2.5","mimo-v2.5-turbo","mimo-pro"]},
    "ChatGPT":   {"base_url": "https://api.openai.com/v1",          "models": ["gpt-4.1","gpt-4o","gpt-4o-mini","o3","o4-mini"]},
    "Claude":    {"base_url": "https://api.anthropic.com/v1",       "models": ["claude-sonnet-4","claude-4-opus","claude-haiku-3-5"]},
}

# 默认正文模板（通用示例）
DEFAULT_BODY_TEMPLATE = """尊敬的招聘负责人：

您好！

我是来自{学校}的{姓名}，{专业}专业{年级}学生。看到贵公司正在招聘实习生，我具备相关岗位所需的{技能}，特此投递简历，希望能获得面试机会。

随信附上我的简历，敬请查阅。期待您的回复！

此致
敬礼

{姓名}
{邮箱}
{电话}"""

# 默认发送速度（封/分钟）
DEFAULT_RATE = 20


@dataclass
class EmailConfig:
    email: str = ""
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    imap_host: str = "imap.qq.com"
    imap_port: int = 993
    use_ssl: bool = True
    auth_code: str = ""
    sender_name: str = ""


@dataclass
class AIConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""


@dataclass
class UserInfo:
    name: str = ""
    school: str = ""
    major: str = ""
    grade: str = ""
    phone: str = ""
    email: str = ""


@dataclass
class AppConfig:
    email: EmailConfig = None
    ai: AIConfig = None
    user: UserInfo = None
    body_template: str = ""
    send_rate: int = DEFAULT_RATE
    last_attachments: list = None

    def __post_init__(self):
        if self.email is None:
            self.email = EmailConfig()
        if self.ai is None:
            self.ai = AIConfig()
        if self.user is None:
            self.user = UserInfo()
        if self.last_attachments is None:
            self.last_attachments = []


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    _ensure_dir()
    if not CONFIG_FILE.exists():
        cfg = AppConfig()
        cfg.body_template = DEFAULT_BODY_TEMPLATE
        return cfg
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cfg = AppConfig()
        cfg.email = EmailConfig(**data.get("email", {}))
        cfg.ai = AIConfig(**data.get("ai", {}))
        cfg.user = UserInfo(**data.get("user", {}))
        cfg.body_template = data.get("body_template", DEFAULT_BODY_TEMPLATE)
        cfg.send_rate = data.get("send_rate", DEFAULT_RATE)
        cfg.last_attachments = data.get("last_attachments", [])
        return cfg
    except Exception:
        cfg = AppConfig()
        cfg.body_template = DEFAULT_BODY_TEMPLATE
        return cfg


def save_config(cfg: AppConfig):
    _ensure_dir()
    data = {
        "email": asdict(cfg.email),
        "ai": asdict(cfg.ai),
        "user": asdict(cfg.user),
        "body_template": cfg.body_template,
        "send_rate": cfg.send_rate,
        "last_attachments": cfg.last_attachments,
    }
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_log() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def append_log(entry: dict):
    logs = load_log()
    logs.append(entry)
    LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
