"""AI API 调用 — DeepSeek / GLM / MIMO / ChatGPT / Claude / Kimi / 通义"""
import base64
import json
import re
import time
from typing import Optional

import httpx

from config import AI_PRESETS, ai_base_url


def _openai_chat(base_url: str, api_key: str, model: str, messages: list, timeout: int = 90) -> str:
    """OpenAI 兼容接口（DeepSeek / GLM / MIMO / ChatGPT / Kimi / 通义）"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.3}
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(_friendly_http_error(resp))
    return resp.json()["choices"][0]["message"]["content"]


def _claude_chat(api_key: str, model: str, messages: list, timeout: int = 90) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01",
               "Content-Type": "application/json"}
    system_msg, msgs = None, []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        elif m["role"] in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": m["content"]})
    payload = {"model": model, "max_tokens": 4096, "messages": msgs}
    if system_msg:
        payload["system"] = system_msg
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(_friendly_http_error(resp))
    return resp.json()["content"][0]["text"]


def _friendly_http_error(resp) -> str:
    """把 401/404/429 翻译成人话，别让用户对着 JSON 猜"""
    hint = {
        401: "API Key 无效或已过期",
        403: "该 Key 没有调用权限",
        404: "模型名不存在，检查一下拼写",
        429: "调用太频繁或余额不足",
    }.get(resp.status_code, "")
    body = resp.text[:200].replace("\n", " ")
    return f"AI 接口返回 {resp.status_code}{('：' + hint) if hint else ''}（{body}）"


def ai_chat(provider: str, api_key: str, model: str, messages: list,
            timeout: int = 90, base_url: str = "") -> str:
    if provider not in AI_PRESETS:
        raise ValueError(f"不支持的 AI 提供商: {provider}")
    if provider == "Claude":
        return _claude_chat(api_key, model, messages, timeout)
    base = ai_base_url(provider, base_url)
    if not base:
        raise ValueError("「自定义」需要填写 Base URL（形如 https://xxx/v1）")
    return _openai_chat(base, api_key, model, messages, timeout)


def ai_test(provider: str, api_key: str, model: str, base_url: str = "") -> dict:
    """用一句话验证 Key 能不能用，返回耗时"""
    started = time.time()
    reply = ai_chat(provider, api_key, model,
                    [{"role": "user", "content": "只回复两个字母：ok"}],
                    timeout=30, base_url=base_url)
    return {"reply": (reply or "").strip()[:40],
            "latency_ms": int((time.time() - started) * 1000)}


def _extract_json(content: str):
    """模型爱在 JSON 外面包一层 ``` 或客套话，这里剥掉"""
    text = (content or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 退一步：找第一个 [ ... ] 或 { ... }
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"AI 返回的内容无法解析为 JSON：\n{text[:500]}")


EXTRACT_SYSTEM = """你是求职投递助手。从用户提供的文本中提取收件人信息，返回 JSON 数组。
每条记录：
{"company": "公司名", "email": "邮箱", "subject": "邮件主题", "vars": {"岗位": "…", "HR": "…"}}
规则：
- 只提取文本里真实出现的信息，不要编造邮箱；找不到邮箱就留空字符串
- company 必填，取公司/单位名称
- subject 如果文本里没有，就留空
- vars 放其它有用的字段（岗位、城市、HR 姓名、渠道等），没有就省略
只返回 JSON 数组，不要任何说明文字。"""


def _normalize_rows(data) -> list:
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("AI 没有返回数组")
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        vars_ = item.get("vars")
        if not isinstance(vars_, dict):
            vars_ = {}
        for k in ("岗位", "职位", "position", "城市", "HR"):
            if item.get(k):
                vars_[k] = item[k]
        out.append({
            "company": str(item.get("company", "")).strip(),
            "email": str(item.get("email", "")).strip(),
            "subject": str(item.get("subject", "")).strip(),
            "vars": {str(k): str(v) for k, v in vars_.items() if v},
        })
    return out


def ai_fill_template(provider: str, api_key: str, model: str, user_input: str,
                     base_url: str = "") -> list:
    """从粘贴的乱七八糟文本里提取收件人；额外字段（岗位/城市/HR）进 vars"""
    content = ai_chat(provider, api_key, model, [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": f"从下面内容中提取收件人：\n\n{user_input}"},
    ], base_url=base_url)
    return _normalize_rows(_extract_json(content))


def ai_extract_images(provider: str, api_key: str, model: str,
                      images: list, hint: str = "", base_url: str = "") -> list:
    """从截图/照片里提取收件人。images: [(bytes, mime)]"""
    if not images:
        raise ValueError("没有图片")
    if provider not in AI_PRESETS:
        raise ValueError(f"不支持的 AI 提供商: {provider}")
    base = ai_base_url(provider, base_url)
    text = EXTRACT_SYSTEM + (f"\n补充说明：{hint}" if hint else "")

    if provider == "Claude":
        content = [{"type": "text", "text": text}]
        for data, mime in images:
            content.append({"type": "image",
                            "source": {"type": "base64",
                                       "media_type": mime or "image/png",
                                       "data": base64.b64encode(data).decode()}})
        resp = httpx.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": api_key,
                                   "anthropic-version": "2023-06-01",
                                   "Content-Type": "application/json"},
                          json={"model": model, "max_tokens": 4096,
                                "messages": [{"role": "user", "content": content}]},
                          timeout=180)
        if resp.status_code >= 400:
            raise RuntimeError(_friendly_http_error(resp))
        raw = resp.json()["content"][0]["text"]
    else:
        content = [{"type": "text", "text": text}]
        for data, mime in images:
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime or 'image/png'};base64,"
                                                 f"{base64.b64encode(data).decode()}"}})
        if not base:
            raise ValueError("「自定义」需要填写 Base URL")
        resp = httpx.post(f"{base}/chat/completions",
                          headers={"Authorization": f"Bearer {api_key}",
                                   "Content-Type": "application/json"},
                          json={"model": model, "temperature": 0.2,
                                "messages": [{"role": "user", "content": content}]},
                          timeout=180)
        if resp.status_code >= 400:
            raise RuntimeError(_friendly_http_error(resp))
        raw = resp.json()["choices"][0]["message"]["content"]

    return _normalize_rows(_extract_json(raw))


def ai_generate_body(provider: str, api_key: str, model: str, instruction: str,
                     current_body: str = "", user: Optional[dict] = None,
                     base_url: str = "") -> str:
    """改写/生成求职邮件正文。带上当前正文和个人信息，避免模型瞎编"""
    user = user or {}
    facts = "、".join(f"{k}：{v}" for k, v in user.items() if v) or "（用户未填写）"
    system_prompt = f"""你是求职邮件写作助手，帮中国学生写中文投递邮件正文。
要求：
- 直接输出可用的正文纯文本，不要 Markdown、不要解释、不要"以下是"之类的前缀
- 保留 {{姓名}} {{学校}} {{公司名}} {{岗位}} 这类占位符，程序会按每家公司替换
- 语气专业、简短，控制在 250 字以内，不要空话套话
- 用户信息：{facts}"""
    messages = [{"role": "system", "content": system_prompt}]
    if current_body.strip():
        messages.append({"role": "user", "content": f"当前正文：\n{current_body}"})
        messages.append({"role": "user", "content": f"按以下要求修改：{instruction}"})
    else:
        messages.append({"role": "user", "content": instruction})
    return ai_chat(provider, api_key, model, messages, base_url=base_url).strip()


def get_available_providers() -> list:
    return [{"name": name, "models": info["models"], "base_url": info["base_url"],
             "docs": info.get("docs", ""), "vision": info.get("vision", [])}
            for name, info in AI_PRESETS.items()]
