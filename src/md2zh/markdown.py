"""Markdown 块解析与保护:frontmatter 拆分、代码块占位符、文本分段。"""

import re


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """拆分开头的 frontmatter 块(含首尾 --- 行);无则返回 (None, 原文)。

    识别规则:首行是 ---,且在其与某个闭合 --- 行之间存在含 ":" 的键值行;
    否则视为水平分隔线,不拆分。
    """
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            # 闭合行之前至少一行含 ":",才认定为 frontmatter
            if any(":" in ln for ln in lines[1:i]):
                cut = sum(len(ln) for ln in lines[: i + 1])
                return text[:cut], text[cut:]
            return None, text
    return None, text


_FENCE_PREFIX = "```"
_INLINE_RE = re.compile(r"`[^`\n]+`")


def protect_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    """围栏代码块与行内代码替换为占位符,返回 (保护后文本, 占位符→原文 映射)。

    先处理围栏(其内部的行内代码不重复保护),再处理行内代码;
    未闭合的围栏视为普通文本。
    """
    text, fenced = _protect_fenced(text)
    text, inline = _protect_inline(text)
    return text, {**fenced, **inline}


def _protect_fenced(text: str) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    mapping: dict[str, str] = {}
    lines = text.splitlines(keepends=True)
    i, n = 0, 0
    while i < len(lines):
        if lines[i].lstrip().startswith(_FENCE_PREFIX):
            start = i
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith(_FENCE_PREFIX):
                i += 1
            if i >= len(lines):  # 未闭合:整段视为普通文本
                parts.append("".join(lines[start:]))
                break
            i += 1  # 包含闭合行
            block = "".join(lines[start:i])
            ph = f"@@@CODEBLOCK_{n}@@@"
            mapping[ph] = block
            parts.append(ph)
            n += 1
        else:
            parts.append(lines[i])
            i += 1
    return "".join(parts), mapping


def _protect_inline(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        ph = f"@@@INLINE_{n}@@@"
        mapping[ph] = m.group(0)
        n += 1
        return ph

    return _INLINE_RE.sub(repl, text), mapping


def restore_code_blocks(text: str, mapping: dict[str, str]) -> str:
    """将占位符还原为原始代码内容。"""
    for ph, original in mapping.items():
        text = text.replace(ph, original)
    return text
