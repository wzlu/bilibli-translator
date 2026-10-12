"""翻译 API 调用:术语表加载、提示词构建、流式请求与重试。"""

import json
import os
import sys

import requests

DEFAULT_API_BASE = "https://index-translate.bilibili.com/v1"
DEFAULT_MODEL = "Index-Translate-35B-A3B"
DEFAULT_GLOSSARY = os.path.join(os.path.expanduser("~"), ".config", "md2zh", "glossary.json")

RETRY_TIMES = 2
REQUEST_TIMEOUT = 120


class TranslateError(Exception):
    """翻译 API 调用失败(网络错误/HTTP 错误/空结果,重试耗尽)。"""


# 每次请求携带的 markdown 格式约束
FORMAT_CONSTRAINTS = [
    "严格保留 markdown 语法结构。",
    "不得翻译或修改 @@@...@@@ 占位符。",
    "** 加黑标记必须成对出现、包裹对应的译文词语。",
    "链接 [显示文本](url) 只翻译显示文本,url 原样保留。",
    "表格保持行数与列数,分隔行保持。",
]


def load_glossary(path: str | None) -> list[str]:
    """加载术语表,返回 "A→B" 列表。

    显式指定的文件不存在/格式错误时抛异常,由调用方映射退出码;
    默认文件缺失或格式错误时警告并返回空列表。
    """
    explicit = path is not None
    target = path if explicit else DEFAULT_GLOSSARY
    if not os.path.isfile(target):
        if explicit:
            raise FileNotFoundError(f"术语表文件不存在: {target}")
        return []
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        if explicit:
            raise ValueError(f"术语表文件格式错误: {target}: {e}") from e
        sys.stderr.write(f"md2zh: 警告: 默认术语表格式错误,已忽略: {e}\n")
        return []
    if not isinstance(data, dict):
        if explicit:
            raise ValueError(f"术语表文件必须是 JSON 对象: {target}")
        sys.stderr.write(f"md2zh: 警告: 默认术语表不是 JSON 对象,已忽略: {target}\n")
        return []
    return [f"{k.strip()}→{str(v).strip()}" for k, v in data.items()]


_OUTPUT_ONLY = "只输出译文,不要有任何额外说明。"


def _append_requirements(constraints: list[str], glossary: list[str], fix_notes: str) -> None:
    """向约束列表追加术语表与修复说明(两个提示词构建器共用)。"""
    if glossary:
        constraints.append("【硬性要求】专名/术语对照: " + "、".join(glossary))
    if fix_notes:
        constraints.append(f"【硬性要求】上次翻译存在以下问题,请修正: {fix_notes}")


def build_prompt(text: str, glossary: list[str], fix_notes: str = "", context: str = "") -> str:
    """构建翻译提示词:【源文】+【约束要求】(格式约束+术语表+修复说明)。"""
    constraints = list(FORMAT_CONSTRAINTS)
    _append_requirements(constraints, glossary, fix_notes)
    if context:
        # 上下文仅供术语参考:硬性禁止输出上下文内容,防止模型把参考段带入译文
        constraints.append("【硬性要求】输出仅包含【源文】的译文,不得翻译或输出【上下文参考】中的任何内容。")
    req_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(constraints))
    parts = ["请将以下文本翻译为中文,并且严格遵循所有约束要求。", ""]
    if context:
        parts += ["【上下文参考】(仅供术语一致参考,不要翻译本段)", context, ""]
    parts += [
        "【源文】",
        text.strip(),
        "",
        "【约束要求】",
        req_lines,
        "",
        _OUTPUT_ONLY,
    ]
    return "\n".join(parts)


def build_frontmatter_prompt(text: str, glossary: list[str], fix_notes: str = "") -> str:
    """构建 frontmatter 翻译提示词:key 不变、仅译 value、保留 --- 标记。"""
    constraints = [
        "这是 YAML frontmatter:key 保持不变,只翻译 value。",
        "保持首尾 --- 标记、行数与整体结构不变。",
        "不得翻译或修改 @@@...@@@ 占位符。",
        "** 加黑标记必须成对出现、包裹对应的译文词语。",
        "链接 [显示文本](url) 只翻译显示文本,url 原样保留。",
    ]
    _append_requirements(constraints, glossary, fix_notes)
    req_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(constraints))
    return (
        "请将以下 YAML frontmatter 翻译为中文,并且严格遵循所有约束要求。\n\n"
        f"【源文】\n{text.strip()}\n\n"
        f"【约束要求】\n{req_lines}\n\n"
        f"{_OUTPUT_ONLY}"
    )


def translate_text(api_base: str, model: str, prompt: str, max_tokens: int) -> str:
    """流式调用 chat/completions,失败自动重试,重试耗尽抛 TranslateError。

    采用流式请求规避非流式长文本的网关 504 超时(见 references/call_api.py)。
    """
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    # 网关要求非默认 User-Agent,否则返回 412(见 references/call_api.py)
    headers = {"User-Agent": "Index-Translate-Client/1.0"}
    last_error: Exception | None = None
    for _ in range(RETRY_TIMES + 1):
        try:
            with requests.post(url, json=payload, headers=headers,
                               timeout=REQUEST_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                parts = []
                for raw in resp.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    body = line[6:]
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    # 网关可能发送非对象分片,跳过而不是崩溃(见 references/call_api.py)
                    if not isinstance(chunk, dict):
                        continue
                    choices = chunk.get("choices") or []
                    if not choices or not isinstance(choices[0], dict):
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        parts.append(content)
                text = "".join(parts)
                if "</think>" in text:
                    text = text.split("</think>", 1)[1]
                if not text.strip():
                    raise TranslateError("API 返回空结果")
                return text.strip()
        except (requests.RequestException, TranslateError) as e:
            last_error = e
    # from 保留原始异常链,便于排查根因
    raise TranslateError(str(last_error)) from last_error
