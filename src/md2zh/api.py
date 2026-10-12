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
        return []
    return [f"{k.strip()}→{str(v).strip()}" for k, v in data.items()]


def build_prompt(text: str, glossary: list[str], fix_notes: str = "", context: str = "") -> str:
    """构建翻译提示词:【源文】+【约束要求】(格式约束+术语表+修复说明)。"""
    constraints = list(FORMAT_CONSTRAINTS)
    if glossary:
        constraints.append("【硬性要求】专名/术语对照: " + "、".join(glossary))
    if fix_notes:
        constraints.append(f"【硬性要求】上次翻译存在以下问题,请修正: {fix_notes}")
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
        "只输出译文,不要有任何额外说明。",
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
    if glossary:
        constraints.append("【硬性要求】专名/术语对照: " + "、".join(glossary))
    if fix_notes:
        constraints.append(f"【硬性要求】上次翻译存在以下问题,请修正: {fix_notes}")
    req_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(constraints))
    return (
        "请将以下 YAML frontmatter 翻译为中文,并且严格遵循所有约束要求。\n\n"
        f"【源文】\n{text.strip()}\n\n"
        f"【约束要求】\n{req_lines}\n\n"
        "只输出译文,不要有任何额外说明。"
    )
