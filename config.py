"""ResumeMailer 配置管理 — 本地 JSON 存储"""
import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

# 数据目录（支持环境变量覆盖，用于 Docker 部署）
_DATA_DIR = os.environ.get("RESUMEMAILER_DATA")
CONFIG_DIR = Path(_DATA_DIR) if _DATA_DIR else (Path.home() / ".resumemailer")
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "send_log.json"
ATTACH_DIR = CONFIG_DIR / "attachments"

# 常见邮箱预设
EMAIL_PRESETS = {
    "QQ邮箱":     {"smtp_host": "smtp.qq.com",     "smtp_port": 465, "imap_host": "imap.qq.com",     "imap_port": 993, "use_ssl": True,  "daily_hint": 50},
    "163邮箱":    {"smtp_host": "smtp.163.com",    "smtp_port": 465, "imap_host": "imap.163.com",    "imap_port": 993, "use_ssl": True,  "daily_hint": 100},
    "126邮箱":    {"smtp_host": "smtp.126.com",    "smtp_port": 465, "imap_host": "imap.126.com",    "imap_port": 993, "use_ssl": True,  "daily_hint": 100},
    "Gmail":      {"smtp_host": "smtp.gmail.com",  "smtp_port": 465, "imap_host": "imap.gmail.com",  "imap_port": 993, "use_ssl": True,  "daily_hint": 500},
    "Outlook":    {"smtp_host": "smtp.office365.com","smtp_port": 587,"imap_host": "outlook.office365.com","imap_port": 993,"use_ssl": False,"daily_hint": 300},
    "Foxmail":    {"smtp_host": "smtp.qq.com",     "smtp_port": 465, "imap_host": "imap.qq.com",     "imap_port": 993, "use_ssl": True,  "daily_hint": 50},
}

# AI 模型预设（2026年10月更新）
# docs = 申请 API Key 的页面；vision = 能看图的模型（截图导入收件人要用）
AI_PRESETS = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "docs": "https://platform.deepseek.com/api_keys",
        "vision": [],
    },
    "MIMO（小米）": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.5", "mimo-v2.5-turbo", "mimo-pro"],
        "docs": "",
        "vision": [],
    },
    "ChatGPT": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4.1", "gpt-4o-mini", "o4-mini"],
        "docs": "https://platform.openai.com/api-keys",
        "vision": ["gpt-4o", "gpt-4.1"],
    },
    "Claude": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4", "claude-4-opus", "claude-haiku-3-5"],
        "docs": "https://console.anthropic.com/settings/keys",
        "vision": ["claude-sonnet-4", "claude-4-opus"],
    },
    "GLM（智谱）": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-plus", "glm-4-air-0111", "glm-4-flash", "glm-4v-plus"],
        "docs": "https://open.bigmodel.cn/usercenter/apikeys",
        "vision": ["glm-4v-plus"],
    },
    "Kimi（月之暗面）": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "kimi-k2-0905-preview"],
        "docs": "https://platform.moonshot.cn/console/api-keys",
        "vision": [],
    },
    "通义千问（阿里）": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-vl-max"],
        "docs": "https://bailian.console.aliyun.com/",
        "vision": ["qwen-vl-max"],
    },
    "自定义（OpenAI 兼容）": {
        "base_url": "",
        "models": [],
        "docs": "",
        "vision": [],
    },
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

# 默认主题模板：Excel 里没填主题时用它
DEFAULT_SUBJECT_TEMPLATE = "实习申请-{姓名}-{学校}-{专业}"

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
    base_url: str = ""      # 仅「自定义」需要


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
    subject_template: str = ""
    send_rate: int = DEFAULT_RATE
    daily_limit: int = 0            # 0 = 不限制
    cc_self: bool = False           # 抄送自己一份
    last_attachments: list = None
    last_recipients: list = None    # 刷新页面后仍在
    last_test_at: str = ""          # 上次「发给自己」的时间

    def __post_init__(self):
        if self.email is None:
            self.email = EmailConfig()
        if self.ai is None:
            self.ai = AIConfig()
        if self.user is None:
            self.user = UserInfo()
        if not self.subject_template:
            self.subject_template = DEFAULT_SUBJECT_TEMPLATE
        if self.last_attachments is None:
            self.last_attachments = []
        if self.last_recipients is None:
            self.last_recipients = []


def _ensure_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)


def ai_base_url(provider: str, custom: str = "") -> str:
    if provider == "自定义（OpenAI 兼容）":
        return (custom or "").strip().rstrip("/")
    return AI_PRESETS.get(provider, {}).get("base_url", "").rstrip("/")


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
        cfg.ai = AIConfig(**{k: v for k, v in data.get("ai", {}).items()
                             if k in ("provider", "api_key", "model", "base_url")})
        cfg.user = UserInfo(**data.get("user", {}))
        cfg.body_template = data.get("body_template", DEFAULT_BODY_TEMPLATE)
        cfg.subject_template = data.get("subject_template", DEFAULT_SUBJECT_TEMPLATE)
        cfg.send_rate = data.get("send_rate", DEFAULT_RATE)
        cfg.daily_limit = data.get("daily_limit", 0)
        cfg.cc_self = data.get("cc_self", False)
        cfg.last_attachments = data.get("last_attachments", [])
        cfg.last_recipients = data.get("last_recipients", [])
        cfg.last_test_at = data.get("last_test_at", "")
        return cfg
    except Exception as e:
        # 配置读坏了不要静默丢掉：留一份现场再回退默认值
        try:
            CONFIG_FILE.replace(CONFIG_FILE.with_suffix(f".broken-{int(__import__('time').time())}.json"))
            print(f"⚠️ 配置文件解析失败，已备份原文件：{e}")
        except OSError:
            pass
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
        "subject_template": cfg.subject_template,
        "send_rate": cfg.send_rate,
        "daily_limit": cfg.daily_limit,
        "cc_self": cfg.cc_self,
        "last_attachments": cfg.last_attachments,
        "last_recipients": cfg.last_recipients,
        "last_test_at": cfg.last_test_at,
    }
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    try:  # 授权码与 API Key 落盘，仅本人可读
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def load_log() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


MAX_LOG = 20000


def append_logs(entries: list):
    """批量落盘，避免每封信重写整个日志文件"""
    if not entries:
        return
    logs = load_log()
    logs.extend(entries)
    if len(logs) > MAX_LOG:
        logs = logs[-MAX_LOG:]
    try:
        LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def append_log(entry: dict):
    append_logs([entry])


def sent_today() -> int:
    """今天已成功发出的封数（草稿不计）"""
    from datetime import date
    today = date.today().isoformat()
    n = 0
    for e in load_log():
        if e.get("success") and e.get("mode") == "send" and str(e.get("time", "")).startswith(today):
            n += 1
    return n


def already_contacted() -> dict:
    """email(小写) -> 最近一次成功发送的时间，用于重复投递提醒"""
    out = {}
    for e in load_log():
        if not e.get("success") or e.get("mode") != "send":
            continue
        for a in str(e.get("email", "")).lower().split(","):
            a = a.strip()
            if a:
                out[a] = max(out.get(a, ""), str(e.get("time", "")))
    return out
