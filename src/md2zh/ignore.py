"""忽略列表:解析 .translateignore,提供精确路径与通配模式匹配。"""

import os


def _norm(p: str) -> str:
    """路径归一化:绝对化、折叠、小写、分隔符统一为 /。"""
    return os.path.normcase(os.path.abspath(os.path.normpath(p))).replace("\\", "/")


def _is_glob(line: str) -> bool:
    """含 *、? 或成对 [] 视为通配模式,否则为精确路径。"""
    return "*" in line or "?" in line or ("[" in line and "]" in line)


class IgnoreMatcher:
    """.translateignore 匹配器。"""

    def __init__(self, exact: set[str], patterns: list[str]):
        self._exact = exact

    def is_ignored(self, path: str) -> bool:
        """命中任一忽略规则返回 True(通配模式在任务 2 接入)。"""
        return _norm(path) in self._exact


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
            patterns.append(line)
        else:
            exact.add(_norm(line))
    return IgnoreMatcher(exact, patterns)
