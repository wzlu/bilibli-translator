"""块级格式校验:全部返回问题描述列表,空列表表示通过。"""

import re

_LINK_RE = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")
_PLACEHOLDER_RE = re.compile(r"@@@[A-Z]+_\d+@@@")


def check_links(src: str, dst: str) -> list[str]:
    """链接数量与 url 序列必须与原文一致。"""
    problems = []
    src_links = _LINK_RE.findall(src)
    dst_links = _LINK_RE.findall(dst)
    if len(src_links) != len(dst_links):
        problems.append(f"链接数量不一致(原文 {len(src_links)} 个,译文 {len(dst_links)} 个)")
    src_urls = [m.split("](", 1)[1][:-1] for m in src_links]
    dst_urls = [m.split("](", 1)[1][:-1] for m in dst_links]
    if src_urls != dst_urls:
        problems.append("链接 url 与原文不一致")
    return problems


def check_tables(src: str, dst: str) -> list[str]:
    """表格行的行数与每行列数必须一致。"""
    problems = []
    src_rows = [ln for ln in src.splitlines() if ln.lstrip().startswith("|")]
    dst_rows = [ln for ln in dst.splitlines() if ln.lstrip().startswith("|")]
    if len(src_rows) != len(dst_rows):
        problems.append(f"表格行数不一致(原文 {len(src_rows)} 行,译文 {len(dst_rows)} 行)")
        return problems
    for i, (s, d) in enumerate(zip(src_rows, dst_rows)):
        if s.count("|") != d.count("|"):
            problems.append(f"第 {i + 1} 个表格行列数不一致")
    return problems


def check_placeholders(src: str, dst: str) -> list[str]:
    """所有占位符必须原样出现在译文中。"""
    src_ph = sorted(_PLACEHOLDER_RE.findall(src))
    dst_ph = sorted(_PLACEHOLDER_RE.findall(dst))
    problems = []
    missing = sorted(set(src_ph) - set(dst_ph))
    extra = sorted(set(dst_ph) - set(src_ph))
    if missing:
        problems.append(f"占位符丢失: {missing}")
    if extra:
        problems.append(f"出现未知占位符: {extra}")
    return problems


def check_html_text(src: str, dst: str) -> list[str]:
    """HTML 文本校验:译文裸 < / & 计数不得超过源文(计数式,防模型自造标签/实体)。

    保护态源文中标签与实体已占位符化,合法裸字符可能残留(如文本 "a < b"),
    故仅当译文计数超出源文时计问题,等量保留不误报。
    """
    problems = []
    for ch in "<&":
        if dst.count(ch) > src.count(ch):
            problems.append(f"译文裸 '{ch}' 数量超过原文(原文 {src.count(ch)} 个,译文 {dst.count(ch)} 个)")
    return problems
