"""变量渲染 — 预览与发送共用同一套逻辑

为什么单独一个文件：之前预览在前端 replace、发送在后端 replace，
两边规则不一致（主题根本没渲染），预览通过的信发出去是另一个样子。
"""
import html as _html
import re
from typing import Iterable

# 内置变量（来自个人信息 + 收件人行）
BUILTIN_KEYS = ["公司名", "公司", "姓名", "学校", "专业", "年级", "电话", "邮箱", "技能"]

# {xxx}，不允许跨行、不允许嵌套
_PLACEHOLDER = re.compile(r"\{([^{}\r\n]{1,24})\}")
# 粗略判断正文是否已是 HTML（要求块级标签或成对标签，避免把 a<b 误判成标签）
_HTMLISH = re.compile(r"</(p|div|table|span|strong|b|ul|ol|li|a|h[1-6])>|<(p|br|div|table|h[1-6]|ul|ol|li)\b[^>]*>", re.I)


def build_context(recipient: dict, user: dict) -> dict:
    """合并个人信息与收件人变量；Excel 额外列优先级最高"""
    ctx = {k: "" for k in BUILTIN_KEYS}
    for k in ("姓名", "学校", "专业", "年级", "电话", "邮箱"):
        ctx[k] = str((user or {}).get(k, "") or "")
    company = str(recipient.get("company", "") or "")
    ctx["公司名"] = company
    ctx["公司"] = company
    # Excel 里除四列之外的所有列名 → 变量，如 岗位 / HR / 城市
    for k, v in (recipient.get("vars") or {}).items():
        ctx[str(k).strip()] = "" if v is None else str(v)
    return ctx


def render(template: str, ctx: dict) -> str:
    """替换已知变量；未知变量原样保留（预览里能一眼看见）"""
    def sub(m):
        key = m.group(1)
        return ctx[key] if key in ctx else m.group(0)
    return _PLACEHOLDER.sub(sub, template or "")


def unknown_placeholders(text: str, ctx: dict) -> list:
    return sorted({m.group(1) for m in _PLACEHOLDER.finditer(text or "") if m.group(1) not in ctx})


def strip_tags(text: str) -> str:
    """HTML → 纯文本，给不支持 HTML 的客户端做兜底"""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def render_email(recipient: dict, user: dict, body_template: str, subject_template: str,
                 render_body: bool = True) -> dict:
    """返回 {subject, body, html}；主题优先用该行自己的，空则用主题模板

    render_body=False 用于「统一正文」模式：正文原样发，花括号也不替换（主题照旧替换）。
    """
    ctx = build_context(recipient, user)
    subject_src = (recipient.get("subject") or "").strip() or subject_template or ""
    subject = render(subject_src, ctx).strip()
    body = render(body_template or "", ctx) if render_body else (body_template or "")
    if _HTMLISH.search(body or ""):
        # 正文本身就是 HTML：HTML 部分原样发，纯文本部分去标签
        return {"subject": subject, "body": strip_tags(body), "html": body}
    return {"subject": subject, "body": body, "html": to_html(body)}


def to_html(text: str) -> str:
    """纯文本 → 邮件客户端友好的 HTML（保留换行）；已是 HTML 则原样使用"""
    if _HTMLISH.search(text or ""):
        return text
    escaped = _html.escape(text or "").replace("\r\n", "\n").replace("\n", "<br>\n")
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        '\'PingFang SC\',\'Microsoft YaHei\',sans-serif;font-size:14px;'
        'line-height:1.75;color:#222;max-width:680px;">' + escaped + "</div>"
    )


def collect_vars(recipients: Iterable[dict]) -> list:
    """收件人里出现过的自定义变量名，用于界面提示"""
    keys = set()
    for r in recipients or []:
        keys.update((r.get("vars") or {}).keys())
    return sorted(keys)
