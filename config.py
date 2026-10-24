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
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "docs": "https://platform.deepseek.com/api_keys",
        "vision": ["deepseek-flash"],
    },
    "MIMO（小米）": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.6-pro", "mimo-v2.6-flash"],
        "docs": "https://mimo.mi.com",
        "vision": ["mimo-v2.6-pro", "mimo-v2.6-flash"],
    },
    "ChatGPT": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-5.6", "gpt-5.6-terra", "gpt-5.5"],
        "docs": "https://platform.openai.com/api-keys",
        "vision": ["gpt-5.6", "gpt-5.6-terra", "gpt-5.5"],
    },
    "Claude": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
        "docs": "https://console.anthropic.com/settings/keys",
        "vision": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
    },
    "GLM（智谱）": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4.7", "glm-4.6", "glm-4.6-flash"],
        "docs": "https://open.bigmodel.cn/usercenter/apikeys",
        "vision": [],
    },
    "Kimi（月之暗面）": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6"],
        "docs": "https://platform.kimi.com",
        "vision": ["kimi-k3"],
    },
    "通义千问（阿里）": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.8-max", "qwen3-max", "qwen-plus"],
        "docs": "https://bailian.console.aliyun.com/",
        "vision": ["qwen3.8-max"],
    },
    "自定义（OpenAI 兼容）": {
        "base_url": "",
        "models": [],
        "docs": "",
        "vision": [],
    },
}

# 默认正文模板（通用示例）
_LEGACY_BODY_TEMPLATES = ("""尊敬的招聘负责人：

您好！

我是来自{学校}的{姓名}，{专业}专业{年级}学生。看到贵公司正在招聘实习生，我具备相关岗位所需的{技能}，特此投递简历，希望能获得面试机会。

随信附上我的简历，敬请查阅。期待您的回复！

此致
敬礼

{姓名}
{邮箱}
{电话}""",)   # 旧版默认正文；没改过的人才升级

DEFAULT_BODY_TEMPLATE = """尊敬的招聘负责人：

您好！

我是{姓名}，{学校}{专业}专业{年级}学生（2027年毕业），现申请贵公司的实习岗位。

我具备扎实的金融理论基础，熟练使用Wind、Choice等金融数据终端及Excel数据处理工具，有良好的英语读写能力和团队协作精神。希望能获得面试机会，进一步沟通我的背景与贵公司岗位的匹配度。

随信附上我的简历，敬请查阅。期待您的回复！

此致
敬礼

{姓名}
{邮箱}"""

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
    body_mode: str = "vars"        # "vars"=按收件人定制；"fixed"=所有邮件正文一模一样
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
        # 旧版默认正文（用户没动过）自动换成新版；用户自己写的一律不动
        if data.get("body_template", "").strip() in [x.strip() for x in _LEGACY_BODY_TEMPLATES]:
            data["body_template"] = DEFAULT_BODY_TEMPLATE
        cfg.email = EmailConfig(**data.get("email", {}))
        cfg.ai = AIConfig(**{k: v for k, v in data.get("ai", {}).items()
                             if k in ("provider", "api_key", "model", "base_url")})
        cfg.user = UserInfo(**data.get("user", {}))
        cfg.body_template = data.get("body_template", DEFAULT_BODY_TEMPLATE)
        cfg.body_mode = data.get("body_mode") if data.get("body_mode") in ("vars", "fixed") else "vars"
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
        "body_mode": cfg.body_mode,
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
