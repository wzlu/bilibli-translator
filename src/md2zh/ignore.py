"""忽略列表:解析 .translateignore,提供精确路径与通配模式匹配。"""

import os
import re


def _norm(p: str) -> str:
    """路径归一化:绝对化、折叠、小写、分隔符统一为 /。"""
    return os.path.normcase(os.path.abspath(os.path.normpath(p))).replace("\\", "/")


def _is_glob(line: str) -> bool:
    """含 *、? 或成对 [] 视为通配模式,否则为精确路径。"""
    return "*" in line or "?" in line or ("[" in line and "]" in line)


def _is_absolute_pattern(p: str) -> bool:
    """归一化后的模式以盘符或 / 开头视为绝对,不加右对齐前缀。"""
    return p.startswith("/") or (len(p) >= 3 and p[1:3] == ":/")


def _pattern_regex(pattern: str) -> str:
    """通配模式转正则:** 跨段递归;段内 *、? 不跨分隔符;字符类原样保留。"""
    parts: list[str] = []
    for i, seg in enumerate(pattern.split("**")):
        if i > 0:
            parts.append(".*")
        out: list[str] = []
        j = 0
        while j < len(seg):
            ch = seg[j]
            if ch == "*":
                out.append("[^/]*")
                j += 1
            elif ch == "?":
                out.append("[^/]")
                j += 1
            elif ch == "[":
                end = seg.find("]", j + 1)
                if end == -1:  # 不成对的 [ 按字面处理
                    out.append(re.escape(ch))
                    j += 1
                else:
                    out.append(seg[j:end + 1])
                    j = end + 1
            else:
                out.append(re.escape(ch))
                j += 1
        parts.append("".join(out))
    return "".join(parts)


class IgnoreMatcher:
    """.translateignore 匹配器:精确路径集合 + 预编译通配正则。"""

    def __init__(self, exact: set[str], patterns: list[str]):
        self._exact = exact
        self._regexes = [
            re.compile(("" if _is_absolute_pattern(p) else ".*") + _pattern_regex(p))
            for p in patterns
        ]

    def is_ignored(self, path: str) -> bool:
        """命中任一忽略规则返回 True。"""
        norm = _norm(path)
        if norm in self._exact:
            return True
        return any(rx.fullmatch(norm) for rx in self._regexes)


def load_ignore(path: str = ".translateignore") -> IgnoreMatcher:
    """读取忽略列表;文件不存在返回空匹配器。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return IgnoreMatcher(set(), [])
    exact: set[str] = set()
    patterns: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _is_glob(line):
            p = os.path.normcase(line).replace("\\", "/")
            if p.endswith("/"):
                p += "*"  # 目录形式:追加段内 * 表示直接子文件
            patterns.append(p)
        else:
            exact.add(_norm(line))
    return IgnoreMatcher(exact, patterns)
