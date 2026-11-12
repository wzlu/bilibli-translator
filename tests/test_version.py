import re
import sys
from pathlib import Path

import pytest

from md2zh import __version__

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


# 刻意不比对已安装的包元数据版本:bump 之后未重装时元数据必然滞后,
# 那不是代码缺陷,却会让测试在每次发版后失败(失败的发版测试会被无视)。
# 「pyproject 不得再存静态版本号」由 PEP 621 / setuptools 自身强制:
# version 与 dynamic = ["version"] 并存会直接报错,无需测试兜底。


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib 需 Python 3.11+")
def test_commitizen_bump_map_is_pattern_to_increment():
    """bump_map 必须是 {正则模式: 增量名},写反会让自动定级静默失效。

    commitizen 4.x 的 cz_customize 按 `for pattern, increment in bump_map.items()`
    消费该表(见 cz/customize/customize.py);若写成 {增量名: 模式},它会把
    "MAJOR"/"MINOR"/"PATCH" 当正则去匹配提交信息、永不命中,cz bump 报
    NO_COMMITS_TO_BUMP。该缺陷可潜伏多个版本而不被发现——显式 --increment
    能正常工作,发版看起来一切正常。
    """
    import tomllib

    with PYPROJECT.open("rb") as f:
        cfg = tomllib.load(f)
    bump_map = cfg["tool"]["commitizen"]["customize"]["bump_map"]
    increments = {"MAJOR", "MINOR", "PATCH"}
    assert set(bump_map.values()) <= increments, f"值必须是增量名,实际: {bump_map}"
    assert not set(bump_map) & increments, f"键必须是正则模式,实际: {list(bump_map)}"
