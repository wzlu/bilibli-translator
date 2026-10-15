"""格式注册表测试:md/html/txt 条目、推断规则与未知回落。"""

import pytest

from md2zh import checks, formats, html, markdown, txt


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


def test_get_format_html_entry():
    fmt = formats.get_format("html")
    assert fmt.split_frontmatter is html.split_frontmatter
    assert fmt.protect is html.protect
    assert fmt.restore is html.restore
    assert fmt.chunk_text is html.chunk_text
    assert fmt.validators == (checks.check_placeholders, checks.check_html_text)
    assert fmt.constraints == html.CONSTRAINTS


def test_get_format_txt_entry():
    fmt = formats.get_format("txt")
    assert fmt.protect is txt.protect
    assert fmt.validators == (checks.check_placeholders,)
    assert fmt.constraints == txt.CONSTRAINTS


@pytest.mark.parametrize("path", ["a.html", "a.HTM", "a.htm"])
def test_infer_format_html_variants(path):
    assert formats.infer_format(path) == "html"


def test_infer_format_txt():
    assert formats.infer_format("a.txt") == "txt"
