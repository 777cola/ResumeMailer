"""AI API 调用 — 内置 DeepSeek / GLM / MIMO / ChatGPT / Claude"""
import json
from typing import List, Optional

import httpx

from config import AI_PRESETS


def _openai_chat(base_url: str, api_key: str, model: str, messages: list, timeout: int = 60) -> str:
    """OpenAI-compatible API call (DeepSeek, GLM, MIMO, ChatGPT)"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": 0.3}
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _claude_chat(api_key: str, model: str, messages: list, timeout: int = 60) -> str:
    """Claude-specific API (Anthropic messages API)"""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    # Convert OpenAI-style messages to Anthropic format
    system_msg = None
    anthropic_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        elif m["role"] in ("user", "assistant"):
            anthropic_msgs.append({"role": m["role"], "content": m["content"]})

    payload = {"model": model, "max_tokens": 4096, "messages": anthropic_msgs}
    if system_msg:
        payload["system"] = system_msg

    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def ai_chat(provider: str, api_key: str, model: str, messages: list, timeout: int = 60) -> str:
    """统一的 AI 对话接口"""
    preset = AI_PRESETS.get(provider)
    if not preset:
        raise ValueError(f"不支持的 AI 提供商: {provider}")

    if provider == "Claude":
        return _claude_chat(api_key, model, messages, timeout)
    else:
        return _openai_chat(preset["base_url"], api_key, model, messages, timeout)


def ai_fill_template(provider: str, api_key: str, model: str, user_input: str) -> list:
    """用 AI 从用户输入的文本中提取收件人信息，生成模板数据"""
    system_prompt = """你是一个邮件助手。请从用户提供的文本中提取收件人信息，返回 JSON 数组。
每条记录格式：{"company": "公司名", "email": "邮箱", "subject": "邮件主题"}
如果缺少某些信息，请合理推断或留空。
主题格式参考：实习申请-姓名-学校-专业-实习时长

只返回 JSON 数组，不要额外的文字说明。"""

    user_prompt = f"""请从以下内容中提取收件人信息：

{user_input}

返回 JSON 数组，格式：[{{"company": "...", "email": "...", "subject": "..."}}]"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    content = ai_chat(provider, api_key, model, messages)

    # Try to parse JSON from response
    content = content.strip()
    if content.startswith("```"):
        # Remove code fences
        lines = content.split("\n")
        content = "\n".join(l for l in lines if not l.startswith("```"))

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = [data]
        return data
    except json.JSONDecodeError:
        raise ValueError(f"AI 返回的内容无法解析为 JSON:\n{content}")


def ai_generate_body(provider: str, api_key: str, model: str, instruction: str) -> str:
    """用 AI 生成或修改正文"""
    messages = [
        {"role": "system", "content": "你是一封求职邮件的撰写助手。请根据用户要求生成专业、得体的求职邮件正文。注意：邮件中不要出现 {公司名} 这类占位符，直接写通用的内容。让用户自己后续替换。请用中文撰写。"},
        {"role": "user", "content": instruction},
    ]
    return ai_chat(provider, api_key, model, messages)


def get_available_providers() -> list:
    """返回可用的 AI 提供商列表"""
    return [
        {"name": name, "models": info["models"], "base_url": info["base_url"]}
        for name, info in AI_PRESETS.items()
    ]
