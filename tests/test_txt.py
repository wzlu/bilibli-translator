"""TXT 适配器测试:直通与空行分段。"""

from md2zh import txt


def test_split_frontmatter_returns_none():
    assert txt.split_frontmatter("abc") == (None, "abc")


def test_protect_passthrough_empty_mapping():
    assert txt.protect("abc") == ("abc", {})


def test_restore_identity():
    assert txt.restore("abc", {}) == "abc"


def test_chunk_text_by_blank_lines():
    text = "a\n\n" + "b" * 4000 + "\n\nc"
    chunks = txt.chunk_text(text, 3000)
    assert "".join(chunks) == text
    assert chunks == ["a\n\n", "b" * 4000 + "\n\n", "c"]


def test_chunk_text_oversized_paragraph_kept_whole():
    text = "x" * 3500
    assert txt.chunk_text(text, 3000) == [text]


def test_constraints_text():
    assert any("纯文本" in c for c in txt.CONSTRAINTS)
    assert any("@@@...@@@" in c for c in txt.CONSTRAINTS)
