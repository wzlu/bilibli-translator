"""HTML 适配器:引号感知状态机占位保护,文本节点送译,还原字节级保真。

保护机制经 spike 实证(temp/html_spike.py):正则与 html.parser 方案在
属性内 >、无分号实体、原始文本块等真实网页盲区上均有缺陷,自研状态机
16/16 陷阱 + CRLF 完整页面全通过(见规格 §3.2)。
"""

import html.entities
import re

from md2zh import markdown

CONSTRAINTS = (
    "只输出纯文本译文:不得添加、修改任何 HTML 标签、属性、注释或 &xxx; 实体,不得使用任何文本格式标记。",
    "不得翻译或修改 @@@...@@@ 占位符。",
)

_ENTITIES = html.entities.html5
_ENTITIES_NO_SEMI = frozenset(k for k in _ENTITIES if not k.endswith(";"))
_RAW_TEXT_TAGS = frozenset({"script", "style", "pre", "code"})
# 分段切分点:占位符令牌边界或空行
_TOKEN_OR_BLANK_RE = re.compile(r"(@@@[A-Z]+_\d+@@@|\n[ \t]*\n)")


def split_frontmatter(text: str) -> tuple[None, str]:
    """HTML 无 frontmatter:恒返回 (None, 原文)。"""
    return None, text


def protect(text: str) -> tuple[str, dict[str, str]]:
    """标签/原始文本块/实体占位保护,返回 (保护后文本, 占位符→原文映射)。

    映射值永不包含占位符令牌(保护顺序:先块、再标签、后实体),
    朴素顺序 replace 还原往返安全。
    """
    out: list[str] = []
    mapping: dict[str, str] = {}
    i, n = 0, 0
    L = len(text)
    while i < L:
        c = text[i]
        if c == "<":
            if text.startswith("<!--", i):
                end = text.find("-->", i + 4)
                if end == -1:
                    out.append(text[i:])
                    break
                end += 3
                ph = f"@@@HTMLBLOCK_{n}@@@"
                mapping[ph] = text[i:end]
                out.append(ph)
                n += 1
                i = end
                continue
            if text.startswith("<!", i):
                end = text.find(">", i + 2)
                if end == -1:
                    out.append(text[i:])
                    break
                end += 1
                ph = f"@@@HTMLTAG_{n}@@@"
                mapping[ph] = text[i:end]
                out.append(ph)
                n += 1
                i = end
                continue
            if text.startswith("</", i):
                end = text.find(">", i + 2)
                if end == -1:
                    out.append(text[i:])
                    break
                end += 1
                ph = f"@@@HTMLTAG_{n}@@@"
                mapping[ph] = text[i:end]
                out.append(ph)
                n += 1
                i = end
                continue
            # 标签须以字母开头,否则 < 按字面文本(如 "5 < 10")
            if not (i + 1 < L and text[i + 1].isalpha()):
                out.append(c)
                i += 1
                continue
            # 开始标签:引号感知扫描(引号内 > 不结束标签)
            j = i + 1
            closed = True
            while j < L:
                ch = text[j]
                if ch == ">":
                    break
                if ch in "\"'":
                    q = ch
                    j += 1
                    while j < L and text[j] != q:
                        j += 1
                    if j >= L:
                        closed = False
                        break
                j += 1
            if not closed or j >= L:
                out.append(text[i:])
                break
            end = j + 1
            name = _tag_name(text, i + 1)
            if name.lower() in _RAW_TEXT_TAGS:
                close = _find_close(text, end, name)
                if close == -1:
                    ph = f"@@@HTMLBLOCK_{n}@@@"
                    mapping[ph] = text[i:]
                    out.append(ph)
                    n += 1
                    break
                ph = f"@@@HTMLBLOCK_{n}@@@"
                mapping[ph] = text[i:close]
                out.append(ph)
                n += 1
                i = close
                continue
            ph = f"@@@HTMLTAG_{n}@@@"
            mapping[ph] = text[i:end]
            out.append(ph)
            n += 1
            i = end
            continue
        if c == "&":
            end = _entity_end(text, i)
            if end == -1:
                out.append(c)
                i += 1
                continue
            ph = f"@@@HTMLENT_{n}@@@"
            mapping[ph] = text[i:end]
            out.append(ph)
            n += 1
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out), mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """委托通用朴素替换还原占位符。"""
    return markdown.restore_code_blocks(text, mapping)


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """占位符令牌边界 + 空行切分后贪心装包;令牌原子不跨块。

    minified HTML 无换行时靠令牌边界分段;还原在文档级全局拼回,
    跨块标签配对无影响。
    """
    parts = _TOKEN_OR_BLANK_RE.split(text)
    blocks: list[str] = []
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append(para + sep)
    return markdown.pack_blocks(blocks, max_chars)


def _tag_name(text: str, start: int) -> str:
    j = start
    while j < len(text) and text[j].isalnum():
        j += 1
    return text[start:j]


def _find_close(text: str, start: int, name: str) -> int:
    """查找 </name 的闭合 >(不区分大小写),返回 > 之后的偏移;找不到返回 -1。

    与 HTML 规范一致:原始文本块在首个 </name 处结束。
    定宽切片比较:索引始终取自原文(str.lower() 对 U+0130 等字符
    不保持长度,不可用其偏移切原文)。
    """
    token_lower = ("</" + name).lower()
    tlen = len(token_lower)
    L = len(text)
    i = start
    while i < L:
        # 先找 "<",再定宽不区分大小写比较 "</name";终止符为空白/斜杠/大于号
        if text[i] == "<" and text[i:i + tlen].lower() == token_lower:
            after = i + tlen
            if after >= L or text[after] in " \t\r\n\f/>":
                j = text.find(">", after)
                return -1 if j == -1 else j + 1
        i += 1
    return -1


def _entity_end(text: str, i: int) -> int:
    """按 HTML5 实体规则求实体结束偏移;非实体返回 -1。

    数字实体 &#n;/&#xH 分号可省;命名实体按 html.entities.html5 表
    最长匹配(无分号仅保护表内 legacy 名,未知 &xyz 保持字面)。
    """
    L = len(text)
    j = i + 1
    if j < L and text[j] == "#":
        j += 1
        if j < L and text[j] in "xX":
            j += 1
        start = j
        while j < L and text[j].isalnum():
            j += 1
        if j == start:
            return -1
        if j < L and text[j] == ";":
            j += 1
        return j
    start = j
    while j < L and text[j].isalnum():
        j += 1
    name = text[start:j]
    if not name:
        return -1
    if j < L and text[j] == ";":
        return j + 1 if name + ";" in _ENTITIES else -1
    k = len(name)
    while k > 0 and name[:k] not in _ENTITIES_NO_SEMI:
        k -= 1
    return start + k if k > 0 else -1
