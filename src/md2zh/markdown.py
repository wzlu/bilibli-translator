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
