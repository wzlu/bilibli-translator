"""翻译 API 调用:术语表加载、提示词构建、流式请求与重试。"""

import json
import os
import sys
from time import sleep

import requests

from md2zh import markdown

DEFAULT_API_BASE = "https://index-translate.bilibili.com/v1"
DEFAULT_MODEL = "Index-Translate-35B-A3B"
OLLAMA_API_BASE = "http://localhost:11434/v1"
OLLAMA_MODEL = "index-translate-9b:latest"
DEFAULT_GLOSSARY = os.path.join(os.path.expanduser("~"), ".config", "md2zh", "glossary.json")

RETRY_TIMES = 2
# 首次重试前等待秒数,之后按 2 的幂翻倍(1s、2s)。取 1s 的依据:实测瞬时 412 在
# 用户手动稍后重试(数秒量级)即恢复,故秒级退避足够;再长会显著拖慢批量失败场景
# (单次请求最坏 3×120s + 3s,退避仅占 0.8%,不改变既有「约 6 分钟」口径)
RETRY_BACKOFF = 1.0
REQUEST_TIMEOUT = 120
# 可重试的 4xx:网关抖动/限流所致,稍后即恢复;其余 4xx 源于请求本身,重试无益。
# 412 除「缺 User-Agent」这一固定成因外,也会因网关侧瞬时状态间歇出现(实测稍后重试即成功)
RETRYABLE_STATUS = frozenset({408, 412, 429})


class TranslateError(Exception):
    """翻译 API 调用失败(网络错误/HTTP 错误/空结果,重试耗尽)。"""


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


def build_prompt(text: str, glossary: list[str], fix_notes: str = "", context: str = "",
                 constraints: list[str] | None = None) -> str:
    """构建翻译提示词:【源文】+【约束要求】(格式约束+术语表+修复说明)。

    constraints 缺省回落 markdown.CONSTRAINTS(保持既有默认行为);
    各格式经 formats 注册表传入自己的约束文本。
    """
    constraints = list(constraints) if constraints is not None else list(markdown.CONSTRAINTS)
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


def translate_text(api_base: str, model: str, prompt: str, max_tokens: int,
                   ollama: bool = False) -> str:
    """流式调用 chat/completions,失败自动重试,重试耗尽抛 TranslateError。

    采用流式请求规避非流式长文本的网关 504 超时(见 references/call_api.py)。
    ollama=True 走本地 OpenAI 兼容端点:省略 B 站特有的 chat_template_kwargs,
    网关 412 的 User-Agent 要求不适用。
    """
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if not ollama:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    # B 站网关要求非默认 User-Agent,否则返回 412(见 references/call_api.py);
    # 本地 ollama 无此要求,空 dict 让 requests 使用默认 UA
    headers = {"User-Agent": "Index-Translate-Client/1.0"} if not ollama else {}
    last_error: Exception | None = None
    for attempt in range(RETRY_TIMES + 1):
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
                    # 网关对参数错误(如 max_tokens 超限)返回 HTTP 200 + error 分片:
                    # 透出真实错误,防止被静默跳过后误报「API 返回空结果」
                    if chunk.get("error"):
                        err = chunk["error"]
                        msg = err.get("message", err) if isinstance(err, dict) else err
                        raise TranslateError(f"网关返回错误: {msg}")
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
        except requests.HTTPError as e:
            # 须排在 RequestException 之前(HTTPError 是其子类)。
            # 非可重试的 4xx 源于请求本身,立即失败:退避只会把必然失败拖得更慢
            status = e.response.status_code if e.response is not None else 0
            if 400 <= status < 500 and status not in RETRYABLE_STATUS:
                raise TranslateError(str(e)) from e
            last_error = e
        except (requests.RequestException, TranslateError) as e:
            last_error = e
        if attempt < RETRY_TIMES:
            # 指数退避:瞬时故障(网关抖动/限流/间歇 412)需要时间消退,
            # 无间隔连发会在同一故障窗口内打光全部重试次数
            sleep(RETRY_BACKOFF * 2 ** attempt)
    # from 保留原始异常链,便于排查根因
    raise TranslateError(str(last_error)) from last_error
