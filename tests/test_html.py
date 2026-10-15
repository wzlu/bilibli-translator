"""HTML 适配器测试:陷阱语料、往返恒等、映射不变量与分段不变量。"""

import re

import pytest

from md2zh import html

# (名称, 输入, 期望可译片段, 是否要求保护文本无 < 与 &)
TRAPS = [
    ("引号内 >", '<div title="a > b">hello</div>', ["hello"], True),
    ("转义实体", "<p>5 &lt; 10 and 3 &gt; 2</p>", ["5 ", " 10 and 3 ", " 2"], True),
    ("文本裸 <", "5 < 10 and 3 > 2", ["5 < 10 and 3 > 2"], False),
    ("无分号实体", "a&nbspb", ["a", "b"], True),
    ("十六进制实体", "&#x27;ok&#x27;", ["ok"], True),
    ("属性内 &", '<a href="/x?a=1&b=2">link</a>', ["link"], True),
    ("跨行标签", '<div\n  class="x">text</div>', ["text"], True),
    ("大写标签", '<SCRIPT src="x.js"></SCRIPT>after', ["after"], True),
    ("script 内 </script> 字面量",
     '<script>if (a < b) { x = "</script>" + y; }</script>tail', [], True),
    ("style 内 >", "<style>a > b { color: red; }</style>text", ["text"], True),
    ("注释内 -->", "<!-- note: a --> b --><p>hi</p>", [" b -->", "hi"], True),
    ("doctype+minified",
     '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></head>'
     "<body><h1>Title</h1><p>Hello <b>world</b>!</p></body></html>",
     ["Title", "Hello ", "!"], True),
    ("void 元素", '<img src="x.png" alt="A > B">', [], True),
    ("无引号属性 >", "<input value=a>b>", ["b>"], True),
    ("pre 整块保护", "<pre>if (a < b) {}</pre>after", ["after"], True),
    ("code 整块保护", "<p>use <code>if (a &lt; b)</code> now</p>",
     ["use ", " now"], True),
]

PAGE = "\r\n".join([
    '<!DOCTYPE html>',
    '<html lang="en">',
    '<head>',
    '<meta charset="utf-8">',
    '<title>Page Title &amp; More</title>',
    '<style>body { color: red; } a > b { top: 0; }</style>',
    '<script>var s = "<div title=\'a > b\'>"; // &nbsp; raw</script>',
    '</head>',
    '<body>',
    '<h1>Main Heading</h1>',
    '<p>First paragraph with <b>bold</b> and <a href="/x?a=1&b=2">link</a>.</p>',
    '<pre>if (x < y) { return x; }</pre>',
    '<ul><li>Item one</li><li>Item two</li></ul>',
    '</body>',
    '</html>',
])


@pytest.mark.parametrize("name,text,want_frags,no_leak", TRAPS)
def test_roundtrip_identity(name, text, want_frags, no_leak):
    # 保护→还原必须字节级恒等(全部陷阱语料)
    protected, mapping = html.protect(text)
    assert html.restore(protected, mapping) == text


@pytest.mark.parametrize("name,text,want_frags,no_leak", TRAPS)
def test_protected_form(name, text, want_frags, no_leak):
    # 保护形态:无 < 与 & 泄漏(裸文本用例除外),可译片段完整保留
    protected, mapping = html.protect(text)
    if no_leak:
        assert "<" not in protected and "&" not in protected
    for frag in want_frags:
        assert frag in protected


def test_page_roundtrip_crlf():
    # CRLF 完整页面:往返恒等、无泄漏、文本节点可译
    protected, mapping = html.protect(PAGE)
    assert html.restore(protected, mapping) == PAGE
    assert "<" not in protected and "&" not in protected
    assert "Page Title " in protected
    assert "Main Heading" in protected
    assert "Item one" in protected


def test_mapping_values_never_contain_tokens():
    # 嵌套不变量:script 内含 <、属性内含实体——映射值只含原文,不含任何 @@@ 令牌
    src = '<script>if (a < b) {}</script><div title="x &amp; y">t</div>'
    protected, mapping = html.protect(src)
    for original in mapping.values():
        assert "@@@" not in original
    assert html.restore(protected, mapping) == src


def test_find_close_unicode_casefold_safe():
    # U+0130("İ")lower 后变 2 字符:闭合查找索引必须取自原文,否则块边界错位吞字符
    text = "İ<script>var a=1;</script><div>hi</div>"
    protected, mapping = html.protect(text)
    assert html.restore(protected, mapping) == text
    assert mapping["@@@HTMLBLOCK_0@@@"] == "<script>var a=1;</script>"
    assert "hi" in protected
    assert "div>hi" not in protected


def test_raw_block_ends_at_script_slash_close():
    # </script/>:斜杠亦是合法终止符(HTML5 appropriate end tag 语义)
    text = "<script>x</script/>tail"
    protected, mapping = html.protect(text)
    assert html.restore(protected, mapping) == text
    assert mapping["@@@HTMLBLOCK_0@@@"] == "<script>x</script/>"
    assert "tail" in protected


def test_split_frontmatter_returns_none():
    assert html.split_frontmatter("<p>x</p>") == (None, "<p>x</p>")


def test_chunk_join_invariant_and_token_atomicity():
    # 令牌/空行边界切分:拼接恒等;逐块回收的令牌序列 == 保护态全文令牌序列(令牌被切开即漏配)
    text = "<p>hello</p>\n\n<div>world</div>"
    protected, _ = html.protect(text)
    chunks = html.chunk_text(protected, 4)
    assert "".join(chunks) == protected
    pat = re.compile(r"@@@[A-Z]+_\d+@@@")
    assert [t for c in chunks for t in pat.findall(c)] == pat.findall(protected)


def test_chunk_minified_long_multi_chunk():
    # minified 长文:先 protect 再分段(管线契约),令牌边界分段,多块且每块不超限
    text = "<b>x</b> " * 50
    protected, mapping = html.protect(text)
    chunks = html.chunk_text(protected, 100)
    assert "".join(chunks) == protected
    assert len(chunks) > 1
    assert max(len(c) for c in chunks) <= 100


def test_constraints_text():
    assert any("实体" in c for c in html.CONSTRAINTS)
    assert any("@@@...@@@" in c for c in html.CONSTRAINTS)
