import re
from importlib.metadata import version as pkg_version

from md2zh import __version__


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_version_matches_package_metadata():
    # 版本单一来源是 __init__.py,pyproject 经 dynamic 取值;
    # 两者不一致说明 dynamic 配置失效(如 attr 路径写错),发版会带错版本号
    assert __version__ == pkg_version("md2zh")
