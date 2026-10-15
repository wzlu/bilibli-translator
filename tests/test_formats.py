"""格式注册表测试:md 条目、推断规则与未知回落。"""

import pytest

from md2zh import formats, markdown


def test_get_format_md_points_to_markdown_functions():
    fmt = formats.get_format("md")
    assert fmt.split_frontmatter is markdown.split_frontmatter
    assert fmt.protect is markdown.protect_code_blocks
    assert fmt.restore is markdown.restore_code_blocks
    assert fmt.chunk_text is markdown.chunk_text
    assert fmt.constraints == markdown.CONSTRAINTS


def test_get_format_unknown_name_raises_key_error():
    with pytest.raises(KeyError):
        formats.get_format("xml")


@pytest.mark.parametrize("path", ["A.md", "A.MD", "a.markdown"])
def test_infer_format_md_variants(path):
    assert formats.infer_format(path) == "md"


@pytest.mark.parametrize("path", ["a.rst", "noext", "a.tar.gz"])
def test_infer_format_unknown_falls_back_md(path):
    assert formats.infer_format(path) == "md"
