import re

from md2zh import __version__


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


# 刻意不比对已安装的包元数据版本:bump 之后未重装时元数据必然滞后,
# 那不是代码缺陷,却会让测试在每次发版后失败(失败的发版测试会被无视)。
# 「pyproject 不得再存静态版本号」由 PEP 621 / setuptools 自身强制:
# version 与 dynamic = ["version"] 并存会直接报错,无需测试兜底。
