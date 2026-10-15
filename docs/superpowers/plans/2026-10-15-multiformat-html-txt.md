# md2zh v0.6.0 多格式支持(HTML/TXT)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** md2zh 支持 HTML/TXT 格式翻译,新增 `--format` 选项与 `txt2zh` 别名,版本升 0.6.0。

**Architecture:** 格式注册表(formats.py)+ 每格式适配器(markdown/html/txt):保护→翻译→校验→还原管线不变,仅按 Format 对象分派;HTML 用自研引号感知状态机占位保护(spike 实证 16/16,见 specs/2026-10-15-multiformat-html-txt-design.md §3.2)。

**Tech Stack:** Python ≥3.10;运行期依赖仅 requests;开发依赖 pytest;零新依赖(`html.entities` 为 stdlib)。

## Global Constraints

- 严格 TDD:先写失败测试 → 运行确认 RED → 最小实现 → 运行确认 GREEN → 提交;提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- 代码注释与用户可见输出一律中文;运行期依赖仅 requests
- 退出码契约不变:0/1/64/65/66/74/75/130/141(常量仅 translator.py 定义)
- 真实 API 不进自动化测试;API 全部 mock
- 版本 0.6.0 双处同步:src/md2zh/__init__.py:3 与 pyproject.toml:7
- 当前分支 v0.6.0-multiformat;SDD 台账 .superpowers/sdd/progress.md 记录任务与提交哈希
- 验收命令:`python -m pytest -v` 全绿;测试命名 tests/test_<模块>.py,函数 test_<场景描述>
- 导入方向单向无环:formats → {markdown, html, txt, checks};translator → {formats, api};api → markdown;禁止 html/txt 导入 formats

---

### Task 0:规格与实施计划文档(前置,已完成代码之外的文档)

**Files:**
- Create: `docs/superpowers/specs/2026-10-15-multiformat-html-txt-design.md`(已写)
- Create: `docs/superpowers/plans/2026-10-15-multiformat-html-txt.md`(本文件)
- Modify: `.superpowers/sdd/progress.md`(初始化本次计划记录)

- [x] Step 1: 规格文档已落盘(含方案选型与 spike 实证裁决)
- [ ] Step 2: 提交

```bash
git add docs/superpowers/ .superpowers/sdd/progress.md
git commit -m "docs: v0.6.0 多格式支持规格与实施计划

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 1:markdown.py 共享工具抽取 + formats.py 注册表(md 条目)

**Files:**
- Modify: `src/md2zh/markdown.py`(抽取 pack_blocks/split_blank_lines、新增 CONSTRAINTS)
- Create: `src/md2zh/formats.py`(仅 md 条目)
- Test: `tests/test_formats.py`(新)、`tests/test_markdown.py`(追加 5 例)

**Interfaces:**
- Produces: `markdown.CONSTRAINTS: tuple[str, ...]`(三条 md 约束,api.py 现 FORMAT_CONSTRAINTS 文案逐字迁移);`markdown.pack_blocks(blocks, max_chars) -> list[str]`;`markdown.split_blank_lines(text) -> list[str]`;`formats.Format`、`formats.FORMATS`、`formats.get_format(name)`、`formats.infer_format(path)`

- [ ] **Step 1: 写失败测试**

`tests/test_formats.py`(新文件,Task 1 仅测 md 与回落;html/txt 用例在 Task 3 追加):

```python
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
```

`tests/test_markdown.py` 末尾追加:

```python
def test_split_blank_lines_keeps_separators():
    blocks = markdown.split_blank_lines("a\n\nb")
    assert blocks == ["a\n\n", "b"]


def test_split_blank_lines_leading_blank():
    assert markdown.split_blank_lines("\n\na") == ["\n\n", "a"]


def test_pack_blocks_greedy_packing():
    assert markdown.pack_blocks(["aa", "bb", "cc"], 4) == ["aabb", "cc"]


def test_pack_blocks_oversized_kept_whole():
    assert markdown.pack_blocks(["aaaaa"], 3) == ["aaaaa"]


def test_pack_blocks_empty_blocks_merged_into_neighbor():
    # 空块并入相邻块(与 chunk_text 现行为一致),join 不变量不受影响
    assert markdown.pack_blocks(["", "a"], 10) == ["a"]
```

- [ ] **Step 2: 运行确认 RED**

Run: `python -m pytest -v tests/test_formats.py tests/test_markdown.py -k "formats or split_blank_lines or pack_blocks"`
Expected: FAIL(ModuleNotFoundError: No module named 'md2zh.formats')

- [ ] **Step 3: 实现 markdown.py 抽取**

修改 `src/md2zh/markdown.py`:

1. 模块 docstring 改为:`"""文本分段与占位符通用工具 + Markdown 适配实现。"""`

2. 在 import re 之后新增 CONSTRAINTS:

```python
# 每次请求携带的 markdown 格式约束(自 api.py 迁移,文案逐字不变)
CONSTRAINTS = (
    "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。",
    "不得翻译或修改 @@@...@@@ 占位符。",
    "表格保持行数与列数,分隔行保持。",
)
```

3. 将 `chunk_text`(现 122-139 行)拆为 `pack_blocks` + `split_blank_lines` + 组合调用,`_logical_blocks` 改用 `split_blank_lines`(行为不变):

```python
def split_blank_lines(text: str) -> list[str]:
    """按空行切分并保留分隔符(分隔符并入前段)。"""
    parts = re.split(r"(\n[ \t]*\n)", text)
    blocks: list[str] = []
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append(para + sep)
    return blocks


def pack_blocks(blocks: list[str], max_chars: int) -> list[str]:
    """贪心装包:按序装入不超过 max_chars 的块;超限块保持完整。"""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        if current and size + len(block) > max_chars:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        chunks.append("".join(current))
    return chunks


def _logical_blocks(text: str) -> list[str]:
    """空行切分后,连续的表格行/列表项合并为一块。"""
    merged: list[str] = []
    for block in split_blank_lines(text):
        if block and _is_table_or_list(block) and merged and _is_table_or_list(merged[-1]):
            merged[-1] += block
            continue
        merged.append(block)
    return merged


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """按逻辑边界切分文本;所有段按序拼接与原文完全一致。

    超出 max_chars 的不可分割块(如大表格)保持完整,不做切割。
    """
    return pack_blocks(_logical_blocks(text), max_chars)
```

- [ ] **Step 4: 创建 formats.py(md 条目)**

`src/md2zh/formats.py`(新文件):

```python
"""格式注册表:各文本格式适配器的统一入口,翻译管线按此分派。"""

from dataclasses import dataclass
from typing import Callable

from md2zh import checks, markdown

Validator = Callable[[str, str], list[str]]


@dataclass(frozen=True)
class Format:
    """一种文本格式的适配面:保护/还原/分段/校验/提示词约束。"""

    name: str
    extensions: tuple[str, ...]
    split_frontmatter: Callable[[str], tuple[str | None, str]]
    protect: Callable[[str], tuple[str, dict[str, str]]]
    restore: Callable[[str, dict[str, str]], str]
    chunk_text: Callable[[str, int], list[str]]
    validators: tuple[Validator, ...]
    constraints: tuple[str, ...]


FORMATS: dict[str, Format] = {
    "md": Format(
        name="md",
        extensions=(".md", ".markdown"),
        split_frontmatter=markdown.split_frontmatter,
        protect=markdown.protect_code_blocks,
        restore=markdown.restore_code_blocks,
        chunk_text=markdown.chunk_text,
        validators=(checks.check_links, checks.check_tables, checks.check_placeholders),
        constraints=markdown.CONSTRAINTS,
    ),
}


def get_format(name: str) -> Format:
    """按名称取格式;未知名抛 KeyError(CLI choices 已拦截,仅库级可达)。"""
    return FORMATS[name]


def infer_format(path: str) -> str:
    """按扩展名(小写)推断格式;未知扩展名回落 md(向后兼容)。"""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    for key, fmt in FORMATS.items():
        if "." + ext in fmt.extensions:
            return key
    return "md"
```

- [ ] **Step 5: 运行确认 GREEN**

Run: `python -m pytest -v tests/test_formats.py tests/test_markdown.py`
Expected: 全部 PASS(其中 test_markdown.py 18 项存量全绿,证明抽取无损)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/markdown.py src/md2zh/formats.py tests/test_formats.py tests/test_markdown.py
git commit -m "feat: 抽取共享分段工具并新增格式注册表(md 条目)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2:HTML 适配器状态机 + check_html_text

**Files:**
- Create: `src/md2zh/html.py`
- Modify: `src/md2zh/checks.py`(追加 check_html_text)
- Test: `tests/test_html.py`(新)、`tests/test_checks.py`(追加 4 例)

**Interfaces:**
- Consumes: `markdown.restore_code_blocks`、`markdown.pack_blocks`(Task 1)
- Produces: `html.CONSTRAINTS`;`html.split_frontmatter(text) -> (None, text)`;`html.protect(text) -> (protected, mapping)`;`html.restore(text, mapping)`;`html.chunk_text(text, max_chars=3000)`;`checks.check_html_text(src, dst)`

- [ ] **Step 1: 写失败测试**

`tests/test_html.py`(新文件):

```python
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


def test_find_close_unicode_casefold_safe():
    # U+0130 经 str.lower() 变 2 字符:定宽切片保证边界偏移不错位、往返恒等
    text = "İ<script>var a=1;</script><div>hi</div>"
    protected, mapping = html.protect(text)
    assert html.restore(protected, mapping) == text
    assert mapping["@@@HTMLBLOCK_0@@@"] == "<script>var a=1;</script>"
    assert "hi" in protected
    assert "div>hi" not in protected


def test_raw_block_ends_at_script_slash_close():
    # 终止符集合含 /:斜杠结束标签正确闭合原始文本块,tail 可译
    text = "<script>x</script/>tail"
    protected, mapping = html.protect(text)
    assert html.restore(protected, mapping) == text
    assert mapping["@@@HTMLBLOCK_0@@@"] == "<script>x</script/>"
    assert "tail" in protected


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
```

`tests/test_checks.py` 末尾追加:

```python
def test_check_html_text_ok():
    assert checks.check_html_text("你好", "你好") == []


def test_check_html_text_bare_lt_added():
    problems = checks.check_html_text("你好", "你好 <b>")
    assert problems


def test_check_html_text_bare_amp_added():
    problems = checks.check_html_text("你好", "你好 &amp; 世界")
    assert problems


def test_check_html_text_legit_bare_preserved():
    # 源文合法裸字符等量保留(如 "a < b")不误报
    assert checks.check_html_text("a < b", "甲 < 乙") == []
```

- [ ] **Step 2: 运行确认 RED**

Run: `python -m pytest -v tests/test_html.py tests/test_checks.py -k "html or check_html_text"`
Expected: FAIL(ModuleNotFoundError: No module named 'md2zh.html')

- [ ] **Step 3: 实现 checks.check_html_text**

`src/md2zh/checks.py` 末尾追加:

```python
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
```

- [ ] **Step 4: 实现 html.py**

`src/md2zh/html.py`(新文件):

```python
"""HTML 适配器:引号感知状态机占位保护,文本节点送译,还原字节级保真。

保护机制经 spike 实证(temp/html_spike.py):正则与 html.parser 方案在
属性内 >、无分号实体、原始文本块等真实网页盲区上均有缺陷,自研状态机
16/16 陷阱 + CRLF 完整页面全通过(见规格 §3.2)。
"""

import html.entities
import re

from md2zh import markdown

CONSTRAINTS = (
    "只输出纯文本译文:不得添加、修改任何 HTML 标签、属性、注释或 &xxx; 实体,不得使用任何文本格式标记。",
    "不得翻译或修改 @@@...@@@ 占位符。",
)

_ENTITIES = html.entities.html5
_ENTITIES_NO_SEMI = frozenset(k for k in _ENTITIES if not k.endswith(";"))
_RAW_TEXT_TAGS = frozenset({"script", "style", "pre", "code"})
# 分段切分点:占位符令牌边界或空行
_TOKEN_OR_BLANK_RE = re.compile(r"(@@@[A-Z]+_\d+@@@|\n[ \t]*\n)")


def split_frontmatter(text: str) -> tuple[None, str]:
    """HTML 无 frontmatter:恒返回 (None, 原文)。"""
    return None, text


def protect(text: str) -> tuple[str, dict[str, str]]:
    """标签/原始文本块/实体占位保护,返回 (保护后文本, 占位符→原文映射)。

    映射值永不包含占位符令牌(保护顺序:先块、再标签、后实体),
    朴素顺序 replace 还原往返安全。
    """
    out: list[str] = []
    mapping: dict[str, str] = {}
    i, n = 0, 0
    L = len(text)
    while i < L:
        c = text[i]
        if c == "<":
            if text.startswith("<!--", i):
                end = text.find("-->", i + 4)
                if end == -1:
                    out.append(text[i:])
                    break
                end += 3
                ph = f"@@@HTMLBLOCK_{n}@@@"
                mapping[ph] = text[i:end]
                out.append(ph)
                n += 1
                i = end
                continue
            if text.startswith("<!", i):
                end = text.find(">", i + 2)
                if end == -1:
                    out.append(text[i:])
                    break
                end += 1
                ph = f"@@@HTMLTAG_{n}@@@"
                mapping[ph] = text[i:end]
                out.append(ph)
                n += 1
                i = end
                continue
            if text.startswith("</", i):
                end = text.find(">", i + 2)
                if end == -1:
                    out.append(text[i:])
                    break
                end += 1
                ph = f"@@@HTMLTAG_{n}@@@"
                mapping[ph] = text[i:end]
                out.append(ph)
                n += 1
                i = end
                continue
            # 标签须以字母开头,否则 < 按字面文本(如 "5 < 10")
            if not (i + 1 < L and text[i + 1].isalpha()):
                out.append(c)
                i += 1
                continue
            # 开始标签:引号感知扫描(引号内 > 不结束标签)
            j = i + 1
            closed = True
            while j < L:
                ch = text[j]
                if ch == ">":
                    break
                if ch in "\"'":
                    q = ch
                    j += 1
                    while j < L and text[j] != q:
                        j += 1
                    if j >= L:
                        closed = False
                        break
                j += 1
            if not closed or j >= L:
                out.append(text[i:])
                break
            end = j + 1
            name = _tag_name(text, i + 1)
            if name.lower() in _RAW_TEXT_TAGS:
                close = _find_close(text, end, name)
                if close == -1:
                    ph = f"@@@HTMLBLOCK_{n}@@@"
                    mapping[ph] = text[i:]
                    out.append(ph)
                    n += 1
                    break
                ph = f"@@@HTMLBLOCK_{n}@@@"
                mapping[ph] = text[i:close]
                out.append(ph)
                n += 1
                i = close
                continue
            ph = f"@@@HTMLTAG_{n}@@@"
            mapping[ph] = text[i:end]
            out.append(ph)
            n += 1
            i = end
            continue
        if c == "&":
            end = _entity_end(text, i)
            if end == -1:
                out.append(c)
                i += 1
                continue
            ph = f"@@@HTMLENT_{n}@@@"
            mapping[ph] = text[i:end]
            out.append(ph)
            n += 1
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out), mapping


def restore(text: str, mapping: dict[str, str]) -> str:
    """委托通用朴素替换还原占位符。"""
    return markdown.restore_code_blocks(text, mapping)


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """占位符令牌边界 + 空行切分后贪心装包;令牌原子不跨块。

    minified HTML 无换行时靠令牌边界分段;还原在文档级全局拼回,
    跨块标签配对无影响。
    """
    parts = _TOKEN_OR_BLANK_RE.split(text)
    blocks: list[str] = []
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append(para + sep)
    return markdown.pack_blocks(blocks, max_chars)


def _tag_name(text: str, start: int) -> str:
    j = start
    while j < len(text) and text[j].isalnum():
        j += 1
    return text[start:j]


def _find_close(text: str, start: int, name: str) -> int:
    """查找 </name 的闭合 >(不区分大小写),返回 > 之后的偏移;找不到返回 -1。

    与 HTML 规范一致:原始文本块在首个 </name 处结束。
    定宽切片比较:索引始终取自原文(str.lower() 对 U+0130 等字符
    不保持长度,不可用其偏移切原文)。
    """
    token_lower = ("</" + name).lower()
    tlen = len(token_lower)
    L = len(text)
    i = start
    while i < L:
        # 先找 "<",再定宽不区分大小写比较 "</name";终止符为空白/斜杠/大于号
        if text[i] == "<" and text[i:i + tlen].lower() == token_lower:
            after = i + tlen
            if after >= L or text[after] in " \t\r\n\f/>":
                j = text.find(">", after)
                return -1 if j == -1 else j + 1
        i += 1
    return -1


def _entity_end(text: str, i: int) -> int:
    """按 HTML5 实体规则求实体结束偏移;非实体返回 -1。

    数字实体 &#n;/&#xH 分号可省;命名实体按 html.entities.html5 表
    最长匹配(无分号仅保护表内 legacy 名,未知 &xyz 保持字面)。
    """
    L = len(text)
    j = i + 1
    if j < L and text[j] == "#":
        j += 1
        if j < L and text[j] in "xX":
            j += 1
        start = j
        while j < L and text[j].isalnum():
            j += 1
        if j == start:
            return -1
        if j < L and text[j] == ";":
            j += 1
        return j
    start = j
    while j < L and text[j].isalnum():
        j += 1
    name = text[start:j]
    if not name:
        return -1
    if j < L and text[j] == ";":
        return j + 1 if name + ";" in _ENTITIES else -1
    k = len(name)
    while k > 0 and name[:k] not in _ENTITIES_NO_SEMI:
        k -= 1
    return start + k if k > 0 else -1
```

- [ ] **Step 5: 运行确认 GREEN**

Run: `python -m pytest -v tests/test_html.py tests/test_checks.py`
Expected: 全部 PASS(含 test_checks.py 存量 8 项)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/html.py src/md2zh/checks.py tests/test_html.py tests/test_checks.py
git commit -m "feat: HTML 适配器(引号感知状态机)与 check_html_text 校验

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3:TXT 适配器 + 注册表补全

**Files:**
- Create: `src/md2zh/txt.py`
- Modify: `src/md2zh/formats.py`(补 html/txt 条目)
- Test: `tests/test_txt.py`(新)、`tests/test_formats.py`(追加)

**Interfaces:**
- Consumes: `markdown.restore_code_blocks`、`markdown.pack_blocks`、`markdown.split_blank_lines`(Task 1);`html.*`、`checks.check_html_text`(Task 2)
- Produces: `txt.CONSTRAINTS`;`txt.split_frontmatter`;`txt.protect`;`txt.restore`;`txt.chunk_text`;`formats.FORMATS["html"/"txt"]`

- [ ] **Step 1: 写失败测试**

`tests/test_txt.py`(新文件):

```python
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
```

`tests/test_formats.py` 追加:

```python
from md2zh import checks, html, txt


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
```

- [ ] **Step 2: 运行确认 RED**

Run: `python -m pytest -v tests/test_txt.py tests/test_formats.py -k "txt or html"`
Expected: FAIL(ModuleNotFoundError: No module named 'md2zh.txt')

- [ ] **Step 3: 实现 txt.py**

`src/md2zh/txt.py`(新文件):

```python
"""TXT 适配器:纯文本直通,空行分段。"""

from md2zh import markdown

CONSTRAINTS = (
    "只输出纯文本译文,不得添加任何格式标记。",
    "不得翻译或修改 @@@...@@@ 占位符。",
)


def split_frontmatter(text: str) -> tuple[None, str]:
    """TXT 无 frontmatter:恒返回 (None, 原文)。"""
    return None, text


def protect(text: str) -> tuple[str, dict[str, str]]:
    """纯文本零保护:直通返回,空映射。"""
    return text, {}


def restore(text: str, mapping: dict[str, str]) -> str:
    """空映射下恒等还原(委托通用替换)。"""
    return markdown.restore_code_blocks(text, mapping)


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """空行切分后贪心装包(不合并表格/列表段)。"""
    return markdown.pack_blocks(markdown.split_blank_lines(text), max_chars)
```

- [ ] **Step 4: 补全 formats.py**

`src/md2zh/formats.py`:import 行改为 `from md2zh import checks, html, markdown, txt`;`FORMATS` 增两条目:

```python
    "html": Format(
        name="html",
        extensions=(".html", ".htm"),
        split_frontmatter=html.split_frontmatter,
        protect=html.protect,
        restore=html.restore,
        chunk_text=html.chunk_text,
        validators=(checks.check_placeholders, checks.check_html_text),
        constraints=html.CONSTRAINTS,
    ),
    "txt": Format(
        name="txt",
        extensions=(".txt",),
        split_frontmatter=txt.split_frontmatter,
        protect=txt.protect,
        restore=txt.restore,
        chunk_text=txt.chunk_text,
        validators=(checks.check_placeholders,),
        constraints=txt.CONSTRAINTS,
    ),
```

- [ ] **Step 5: 运行确认 GREEN**

Run: `python -m pytest -v tests/test_txt.py tests/test_formats.py`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/txt.py src/md2zh/formats.py tests/test_txt.py tests/test_formats.py
git commit -m "feat: TXT 适配器并补全格式注册表(html/txt 条目)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4:translator/api 管线按格式分派

**Files:**
- Modify: `src/md2zh/translator.py`、`src/md2zh/api.py`
- Test: `tests/test_translator.py`(重写 1 例、新增 5 例、改 2 行导入引用)、`tests/test_api.py`(追加 2 例)

**Interfaces:**
- Consumes: `formats.Format/ FORMATS / get_format / infer_format`(Task 1/3)
- Produces: `translator.translate_file(..., fmt: str | None = None)`;`translator.run_single/run_batch(..., fmt: str | None = None)`;`translator.run_stdin(..., fmt: str = "md")`;`api.build_prompt(..., constraints=None)`

- [ ] **Step 1: 写失败测试**

`tests/test_translator.py` 改动:

1. 文件头部 import 区(`from md2zh import api` 后)加一行:

```python
from md2zh import formats
from md2zh import markdown
```

2. 重写 `test_translate_file_not_md`(现 77-83 行):

```python
def test_translate_file_txt_inferred(monkeypatch, tmp_path):
    # 非 .md 文件按扩展名推断格式:a.txt → txt 适配器,生成 a_zh.txt
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "译文")
    result = translator.translate_file(str(p), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert (tmp_path / "a_zh.txt").read_text(encoding="utf-8") == "译文"
```

3. 文件末尾追加:

```python
def test_translate_file_html_roundtrip_end_to_end(monkeypatch, tmp_path):
    # .html 推断 html 适配器:真实标签/属性/实体不进 API 请求,还原字节级完好
    src = tmp_path / "page.html"
    src.write_text('<p title="a > b">Hello &amp; bye</p>', encoding="utf-8")

    def fake(*a, **k):
        prompt = a[2]
        # 模型视角:标签、属性、实体全部占位符化
        assert '<p title="a > b">' not in prompt
        assert "&amp;" not in prompt
        # 回传【源文】原文:占位符与本块一致,校验通过
        return prompt.split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "page_zh.html").read_text(encoding="utf-8")
    assert content == '<p title="a > b">Hello &amp; bye</p>'
    assert "@@@" not in content


def test_translate_file_fmt_override(monkeypatch, tmp_path):
    # 显式 fmt 覆盖扩展名推断:.xyz + fmt="html" 走 html 适配器
    p = tmp_path / "a.xyz"
    p.write_text("<p>Hi</p>", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text",
                        lambda *a, **k: "@@@HTMLTAG_0@@@你好@@@HTMLTAG_1@@@")
    result = translator.translate_file(str(p), force=False, glossary=[],
                                       api_base="http://x", model="m", fmt="html")
    assert result.status == "ok"
    assert (tmp_path / "a_zh.xyz").read_text(encoding="utf-8") == "<p>你好</p>"


def test_translate_file_unknown_ext_falls_back_md(monkeypatch, tmp_path):
    # 未知扩展名回落 md 适配器(向后兼容):不再拒绝,按 md 处理
    p = tmp_path / "a.xyz"
    p.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(p), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert (tmp_path / "a_zh.xyz").read_text(encoding="utf-8") == "# 你好"


def test_check_block_dispatch_by_format():
    # 校验器按格式分派:html 不跑链接/表格校验,多裸 < 出问题;txt 只跑占位符
    html_fmt = formats.get_format("html")
    assert translator._check_block("hi", "你好", html_fmt) == []
    assert translator._check_block("hi", "你好 <b>", html_fmt)
    assert translator._check_block("| a |\n", "甲", html_fmt) == []
    assert translator._check_block("| a |\n", "甲", formats.get_format("txt")) == []


def test_translate_long_uses_format_chunk(monkeypatch):
    # 超长 HTML 在占位符令牌边界分段:多次 API 调用且还原闭环
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        prompt = a[2]
        return prompt.split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]

    monkeypatch.setattr(api, "translate_text", fake)
    monkeypatch.setattr(translator, "SINGLE_CALL_LIMIT", 100)
    monkeypatch.setattr(translator, "CHUNK_SIZE", 100)
    text = "<b>x</b> " * 50
    html_fmt = formats.get_format("html")
    protected, mapping = html_fmt.protect(text)
    result = translator._translate_long(protected, [], "http://x", "m",
                                        mapping=mapping, fmt=html_fmt)
    assert html_fmt.restore(result, mapping) == text
    assert calls["n"] > 1
```

4. 修正 `test_long_context_restores_placeholders` 中两行(现 497、502 行):

```python
    protected, mapping = markdown.protect_code_blocks(text)
```

```python
    assert markdown.restore_code_blocks(result, mapping) == text
```

`tests/test_api.py` 追加:

```python
def test_build_prompt_custom_constraints():
    # 显式 constraints 替换默认 md 约束(html/txt 分派路径)
    prompt = api.build_prompt("x", [], "", constraints=["只输出纯文本译文。", "不得翻译占位符。"])
    assert "只输出纯文本译文。" in prompt
    assert "严格保留 markdown 语法结构" not in prompt


def test_build_prompt_default_is_md_constraints():
    # 缺省回落 markdown.CONSTRAINTS(等价断言,防 api 副本漂移——Task 1 审查 Important 流转)
    from md2zh import markdown
    prompt = api.build_prompt("x", [], "")
    assert all(c in prompt for c in markdown.CONSTRAINTS)
    assert "只输出纯文本译文" not in prompt  # html/txt 约束不得混入默认路径
    assert "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。" in prompt
    assert "表格保持行数与列数,分隔行保持。" in prompt
```

- [ ] **Step 2: 运行确认 RED**

Run: `python -m pytest -v tests/test_translator.py tests/test_api.py -k "inferred or html or fmt_override or unknown_ext or dispatch or format_chunk or custom_constraints or default_is_md"`
Expected: FAIL(先 TypeError: translate_file() got an unexpected keyword argument 'fmt' 或 test_translate_file_txt_inferred 断言失败)

- [ ] **Step 3: 实现 api.py**

`src/md2zh/api.py`:

1. import 区加一行 `from md2zh import markdown`(json 之后):

```python
from md2zh import markdown
```

2. 删除 FORMAT_CONSTRAINTS 块(现 23-28 行,含注释,已迁至 markdown.CONSTRAINTS)。

3. `build_prompt` 增参并改约束来源:

```python
def build_prompt(text: str, glossary: list[str], fix_notes: str = "", context: str = "",
                 constraints: list[str] | None = None) -> str:
    """构建翻译提示词:【源文】+【约束要求】(格式约束+术语表+修复说明)。

    constraints 缺省回落 markdown.CONSTRAINTS(保持既有默认行为);
    各格式经 formats 注册表传入自己的约束文本。
    """
    if constraints is None:
        constraints = list(markdown.CONSTRAINTS)
    _append_requirements(constraints, glossary, fix_notes)
    # 其余逻辑不变(上下文隔离约束、提示词装配)
```

- [ ] **Step 4: 实现 translator.py**

`src/md2zh/translator.py` 逐处修改:

1. 第 10 行 import 改为:

```python
from md2zh import api, formats, ignore
```

2. `translate_file`(现 70-98 行):签名增 `fmt: str | None = None`,删除扩展名门,加格式解析与透传:

```python
def translate_file(src_path: str, *, force: bool, glossary: list[str],
                   api_base: str, model: str, repair: int = 0,
                   ollama: bool = False, fmt: str | None = None) -> TranslateResult:
    """翻译单个文件;已存在译文且未 --force 时跳过。

    fmt 缺省按扩展名推断(未知扩展名回落 md);显式指定时覆盖推断。
    """
    fmt_obj = formats.get_format(fmt or formats.infer_format(src_path))
    if not os.path.isfile(src_path):
        return TranslateResult("failed", "文件不存在", EX_NOINPUT)
    dst_path = _zh_path(src_path)
    if os.path.exists(dst_path) and not force:
        return TranslateResult("skipped", "译文已存在(使用 --force 覆盖)")
    try:
        # newline="" 关闭读取期行尾翻译,保留源文件行尾风格供检测;内部管线随后统一为 LF
        with open(src_path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
        # 保持源文件行尾风格:CRLF 源输出 CRLF,LF 源输出 LF
        newline = "\r\n" if "\r\n" in text else "\n"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        translated = _translate_document(text, glossary, api_base, model,
                                         fmt=fmt_obj, source=src_path,
                                         repair=repair, ollama=ollama)
        _atomic_write(dst_path, translated.replace("\r\n", "\n"), newline=newline)
    except api.TranslateError as e:
        return TranslateResult("failed", f"翻译 API 错误: {e}", EX_TEMPFAIL)
    except UnicodeDecodeError as e:
        return TranslateResult("failed", f"源文件不是 UTF-8 编码: {e}", EX_DATAERR)
    except OSError as e:
        return TranslateResult("failed", f"读写文件失败: {e}", EX_IOERR)
    return TranslateResult("ok", dst_path)
```

3. `_translate_document`(现 101-124 行):增 `fmt` 关键字参(缺省回落 md),改派四调用:

```python
def _translate_document(text: str, glossary: list[str], api_base: str, model: str,
                        *, fmt: formats.Format | None = None, source: str = "",
                        repair: int = 0, ollama: bool = False) -> str:
    """文档级翻译:frontmatter 独立翻译,正文按单次/分段策略处理。"""
    if fmt is None:
        fmt = formats.get_format("md")
    fm, rest = fmt.split_frontmatter(text)
    protected, mapping = fmt.protect(rest)

    if fm is None:
        head = ""
    else:
        head = _translate_frontmatter(fm, glossary, api_base, model, ollama=ollama)

    if len(protected) <= SINGLE_CALL_LIMIT:
        body = _translate_chunk(protected, glossary, api_base, model, MAX_TOKENS_SINGLE,
                                source=source, repair=repair, ollama=ollama, fmt=fmt)
    else:
        body = _translate_long(protected, glossary, api_base, model,
                               mapping=mapping, source=source, repair=repair,
                               ollama=ollama, fmt=fmt)

    body = fmt.restore(body, mapping)
    if head:
        return f"{head.rstrip()}\n\n{body.lstrip()}"
    return body
```

4. `_check_block`(现 127-132 行):

```python
def _check_block(src: str, dst: str, fmt: formats.Format | None = None) -> list[str]:
    """块级校验汇总:按格式取校验器(链接/表格为 md 专有)。"""
    if fmt is None:
        fmt = formats.get_format("md")
    problems: list[str] = []
    for fn in fmt.validators:
        problems.extend(fn(src, dst))
    return problems
```

5. `_translate_chunk`(现 166-177 行):关键字参增 `fmt: formats.Format | None = None`,函数体加回落与分派:

```python
def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "", *, source: str = "",
                     repair: int = 0, ollama: bool = False,
                     fmt: formats.Format | None = None) -> str:
    """翻译一段文本:校验失败按 repair 可选重译,始终采用译文。"""
    if fmt is None:
        fmt = formats.get_format("md")
    dst = _repair(
        make_prompt=lambda fix: api.build_prompt(src, glossary, fix_notes=fix,
                                                 context=context,
                                                 constraints=list(fmt.constraints)),
        check=lambda d: _check_block(src, d, fmt),
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
        source=source, retries=repair, ollama=ollama,
    )
    # 译文经 API strip,回挂源块尾随空白,保持分段边界与文件末尾布局
    return dst + _trailing_whitespace(src)
```

6. `_translate_long`(现 180-203 行):关键字参增 `fmt`,函数体改派:

```python
def _translate_long(text: str, glossary: list[str], api_base: str, model: str,
                    *, mapping: dict[str, str], source: str = "",
                    repair: int = 0, ollama: bool = False,
                    fmt: formats.Format | None = None) -> str:
    """超长文本:分段翻译,每段附前段上下文参考保证术语延续。

    上下文发送前还原占位符:占位符令牌不进入 API 请求,防止模型把
    上一块的占位符带入输出而触发「未知占位符」校验失败。
    """
    if fmt is None:
        fmt = formats.get_format("md")
    parts: list[str] = []
    prev_context = ""
    half = CONTEXT_TAIL // 2
    for chunk in fmt.chunk_text(text, CHUNK_SIZE):
        # 不可分割的超限块(如大表格)按块长放大输出预算,避免确定性截断
        budget = max(MAX_TOKENS_CHUNK, len(chunk) * 2 + 200)
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context, source=source,
                                      repair=repair, ollama=ollama, fmt=fmt)
        parts.append(translated)
        # 前段上下文:上一段(原文+译文)尾部,先还原占位符再切尾部——
        # 上下文与文件原文同形,且不可能切出半截占位符令牌
        src_tail = fmt.restore(chunk, mapping)[-half:]
        dst_tail = fmt.restore(translated, mapping)[-half:]
        prev_context = f"原文: {src_tail}\n译文: {dst_tail}"
    return "".join(parts)
```

7. `run_single`(现 227-241 行)签名与调用增 `fmt`:

```python
def run_single(path: str, *, force: bool, glossary: list[str],
               api_base: str, model: str, repair: int = 0,
               ollama: bool = False, fmt: str | None = None) -> int:
    """单文件模式:失败返回具体退出码(65/66/74/75)。"""
    result = translate_file(path, force=force, glossary=glossary,
                            api_base=api_base, model=model, repair=repair,
                            ollama=ollama, fmt=fmt)
```

8. `run_batch`(现 244-293 行)签名增 `fmt: str | None = None`,提交线程池时透传:

```python
def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str, repair: int = 0,
              ignore_matcher: ignore.IgnoreMatcher | None = None,
              max_threads: int = 10, ollama: bool = False,
              fmt: str | None = None) -> int:
    """批量模式:线程池并行翻译,主线程乱序输出并汇总;存在失败返回 EX_PARTIAL。

    忽略列表命中优先于扩展名与存在性检查,且不受 --force 影响;
    命中文件在主线程前置处理,不提交线程池。fmt 显式时全局覆盖,缺省逐文件推断。
    """
    ...
        futures = {executor.submit(translate_file, p, force=force, glossary=glossary,
                                   api_base=api_base, model=model, repair=repair,
                                   ollama=ollama, fmt=fmt): p
                   for p in todo}
```

9. `run_stdin`(现 296-322 行)签名增 `fmt: str = "md"`,传入 `_translate_document`:

```python
def run_stdin(*, glossary: list[str], api_base: str, model: str, repair: int = 0,
              ollama: bool = False, fmt: str = "md") -> int:
    """stdin 模式:读入文本,译文写 stdout(管道过滤器);fmt 缺省 md。"""
    ...
        translated = _translate_document(text, glossary, api_base, model,
                                         fmt=formats.get_format(fmt), source="<stdin>",
                                         repair=repair, ollama=ollama)
```

- [ ] **Step 5: 运行确认 GREEN**

Run: `python -m pytest -v tests/test_translator.py tests/test_api.py`
Expected: 全部 PASS(存量+新增;`test_long_context_restores_placeholders` 经 markdown 直导通过)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/translator.py src/md2zh/api.py tests/test_translator.py tests/test_api.py
git commit -m "feat: 翻译管线按格式分派(fmt 贯穿 translator/api)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5:CLI(--format/_prog/别名)+ 版本 bump

**Files:**
- Modify: `src/md2zh/cli.py`、`pyproject.toml`、`src/md2zh/__init__.py`
- Test: `tests/test_cli.py`(追加 7 例、三处 fake 签名加 `fmt=None`)、`tests/test_version.py`(改断言)

**Interfaces:**
- Consumes: `translator.run_single/run_batch/run_stdin` 的 `fmt` 参数(Task 4)
- Produces: `cli._prog()`;`--format {md,html,txt}` 选项;`txt2zh` 入口

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py` 改动:

1. 三处 `fake_run_batch` 签名(现 209、268、290 行)各加 `fmt=None`:

```python
    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads, ollama=False, fmt=None):
```

2. 文件末尾追加:

```python
def test_format_invalid_exits_64(capsys):
    # --format 仅接受 md/html/txt,非法值按用法错误退出 64
    with pytest.raises(SystemExit) as e:
        cli.main(["--format", "xml", "a.md"])
    assert e.value.code == translator.EX_USAGE


def test_format_passed_to_stdin(monkeypatch):
    # stdin 模式:显式 --format txt 透传;缺省回落 md
    class _FakeStdin:
        def __init__(self, data: bytes):
            self.buffer = io.BytesIO(data)

    seen = {}
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"x"))
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])

    def fake_run_stdin(*, glossary, api_base, model, repair, ollama=False, fmt="md"):
        seen["fmt"] = fmt
        return translator.EX_OK

    monkeypatch.setattr(translator, "run_stdin", fake_run_stdin)
    assert cli.main(["-", "--format", "txt"]) == translator.EX_OK
    assert seen["fmt"] == "txt"
    assert cli.main(["-"]) == translator.EX_OK
    assert seen["fmt"] == "md"


def test_format_passed_to_single(monkeypatch, tmp_path):
    # 单文件模式:--format html 透传到 translate_file
    seen = {}
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])

    def fake_translate_file(src_path, *, force, glossary, api_base, model, repair,
                            ollama=False, fmt=None):
        seen["fmt"] = fmt
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake_translate_file)
    assert cli.main([str(tmp_path / "a.md"), "--format", "html"]) == translator.EX_OK
    assert seen["fmt"] == "html"


def test_format_global_override_batch(monkeypatch, tmp_path):
    # 批量模式:显式 --format 全局覆盖;缺省 None 由 translate_file 逐文件推断
    seen = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(translator, "parse_filelist", lambda p: ["a.md"])
    monkeypatch.setattr(ignore, "load_ignore", lambda *a, **k: None)

    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads, ollama=False, fmt=None):
        seen["fmt"] = fmt
        return translator.EX_OK

    monkeypatch.setattr(translator, "run_batch", fake_run_batch)
    assert cli.main(["--filelist", "l.txt", "--format", "txt"]) == translator.EX_OK
    assert seen["fmt"] == "txt"
    assert cli.main(["--filelist", "l.txt"]) == translator.EX_OK
    assert seen["fmt"] is None


def test_prog_follows_argv0(monkeypatch, capsys):
    # txt2zh 别名:--version 与用法错误显示 txt2zh;.exe 后缀剥离
    monkeypatch.setattr(sys, "argv", ["txt2zh.exe"])
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "txt2zh 0.6.0" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["--format", "xml", "a.md"])
    assert e.value.code == translator.EX_USAGE
    assert "txt2zh" in capsys.readouterr().err


def test_help_mentions_format_and_html_example(capsys):
    # --help 含 --format 选项与 html/txt 示例
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--format" in out
    assert "page.html" in out
    assert "txt2zh" in out
```

`tests/test_version.py`:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.6.0"
```

- [ ] **Step 2: 运行确认 RED**

Run: `python -m pytest -v tests/test_cli.py tests/test_version.py -k "format or prog or help_mentions or version" `
Expected: FAIL(--format 选项不存在/TypeError/版本断言 0.5.0≠0.6.0)

- [ ] **Step 3: 实现 cli.py**

`src/md2zh/cli.py`:

1. `_Parser` 类后新增:

```python
def _prog() -> str:
    """程序名随入口名显示:txt2zh 别名时 usage/--version 显示 txt2zh。

    pytest 等环境下 sys.argv[0] 非本工具入口,回落 md2zh 保兼容。
    """
    name = os.path.basename(sys.argv[0])
    if name.endswith(".exe"):
        name = name[:-4]
    return name if name in ("md2zh", "txt2zh") else "md2zh"
```

2. `parse_args` 中:

```python
    parser = _Parser(
        prog=_prog(),
        description="将英文 Markdown/HTML/TXT 文件翻译为中文,保存为 *_zh.<原扩展名>(同目录)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,  # 保留 epilog 示例的换行
    )
    parser.add_argument("file", nargs="?", metavar="FILE",
                        help="要翻译的文件(格式按扩展名推断:.md/.html/.txt;可用 --format 覆盖)")
    parser.add_argument("--filelist", metavar="LIST",
                        help="文件列表(每行一个文件,# 开头的行被忽略)")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的 *_zh.<扩展名>(默认跳过)")
    parser.add_argument("--format", choices=("md", "html", "txt"), default=None,
                        metavar="FMT",
                        help="输入格式 md/html/txt(默认按扩展名推断;stdin 模式缺省 md)")
```

3. `--version` 行改为:

```python
    parser.add_argument("--version", action="version", version=f"{_prog()} {__version__}")
```

4. epilog 改为:

```python
    parser.epilog = (
        "示例:\n"
        "  {prog} ABC.md                      翻译单个 Markdown 文件,生成 ABC_zh.md\n"
        "  {prog} page.html                  翻译 HTML 文件(格式按扩展名推断)\n"
        "  {prog} note.txt                   翻译纯文本文件(格式按扩展名推断)\n"
        "  txt2zh note.txt                  txt2zh 别名(等价 {prog} --format txt)\n"
        "  {prog} --filelist list.txt        批量翻译(每行一个文件,# 开头忽略)\n"
        "  {prog} --filelist list.txt -c 5    批量翻译,最多 5 个线程并行(默认 10)\n"
        "  {prog} ABC.md --force              覆盖已存在的译文\n"
        "  {prog} ABC.md --glossary g.json    指定术语表\n"
        "  {prog} ABC.md --ollama             使用本地 ollama 离线翻译(强制单线程)\n"
        "  cat ABC.md | {prog} -              管道过滤器(stdin → stdout)\n"
        "  cat page.html | {prog} - --format html  管道过滤器(HTML,stdin 无扩展名需显式 --format)\n"
        "  {prog} ABC.md --repair 2            校验失败后重译至多 2 次(默认不重译)"
    ).format(prog=_prog())
```

5. `main` 三分支透传 fmt:

```python
        if args.file == "-":
            return translator.run_stdin(glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        repair=args.repair, ollama=args.ollama,
                                        fmt=args.format or "md")
        ...
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        ignore_matcher=matcher, repair=args.repair,
                                        max_threads=args.max_threads,
                                        ollama=args.ollama, fmt=args.format)
        return translator.run_single(args.file, force=args.force, glossary=glossary,
                                     api_base=args.api_base, model=args.model,
                                     repair=args.repair, ollama=args.ollama,
                                     fmt=args.format)
```

- [ ] **Step 4: 版本与别名**

`src/md2zh/__init__.py`:`__version__ = "0.6.0"`(docstring 改 `"""md2zh:英文文本翻译 CLI(多格式)。"""`)

`pyproject.toml`:

```toml
version = "0.6.0"
description = "将英文 Markdown/HTML/TXT 文件翻译为中文的命令行工具"
```

```toml
[project.scripts]
md2zh = "md2zh.cli:main"
txt2zh = "md2zh.cli:main"
```

- [ ] **Step 5: 运行确认 GREEN**

Run: `python -m pytest -v tests/test_cli.py tests/test_version.py` → 全量 `python -m pytest -v`
Expected: 全部 PASS(约 209 项)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/cli.py src/md2zh/__init__.py pyproject.toml tests/test_cli.py tests/test_version.py
git commit -m "feat: CLI --format 选项、txt2zh 别名与版本 0.6.0

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6:样例、发布文档与收尾

**Files:**
- Create: `data/sample_en.html`、`data/sample_en.txt`
- Modify: `README.md`、`CHANGELOG.md`、`CLAUDE.md`

- [ ] **Step 1: 样例文件**

`data/sample_en.html`(手工验证样例,含标签/属性/实体/script/style/pre):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sample Page &amp; Guide</title>
<style>body { color: #333; } a > b { top: 0; }</style>
<script>var msg = "hello &amp; world";</script>
</head>
<body>
<h1>Getting Started</h1>
<p title="a &gt; b example">This is a <b>sample</b> paragraph with <a href="/docs?a=1&b=2">a link</a>.</p>
<pre>if (a &lt; b) { return a; }</pre>
<ul><li>First item</li><li>Second item</li></ul>
</body>
</html>
```

`data/sample_en.txt`:

```text
Plain Text Translation Sample

This is the first paragraph.

This is the second paragraph with some technical terms: API, SDK.
```

- [ ] **Step 2: 全量回归 + 报告**

Run: `python -m pytest -v --junitxml=reports/junit.xml`
Expected: 全部 PASS

- [ ] **Step 3: 文档同步**

- README.md:简介行与徽章(版本/测试数)、特性(加多格式条目)、快速开始(html/txt/txt2zh/--format 示例)、行为约定(格式推断规则、--format 全局覆盖、stdin 缺省 md、未知扩展回落 md)、项目结构(加 formats/html/txt)、已知限制(加 HTML 限制清单,见规格 §7)、参考(追加新 spec/plan 链接)。
- CHANGELOG.md:`## [0.6.0] - 2026-10-15`——「新增」:多格式支持(HTML/TXT、`--format`)、txt2zh 别名、HTML 状态机占位保护与 check_html_text;「变更」:非 .md 文件不再拒绝(未知扩展回落 md)。
- CLAUDE.md:Overview 版本与描述;Architecture 加 formats/html/txt 模块与 HTML 保护策略;CLI 接口加 `--format` 与 txt2zh;测试计数同步;Recent Updates 顶部回填 v0.6.0 条目。
- `.superpowers/sdd/progress.md`:回填任务 1-6 提交哈希与审查记录。

- [ ] **Step 4: 手工验证(真实 API,不进自动化;清单见规格 §6)**

```bash
python -m pip install -e ".[dev]"
md2zh data/sample_en.html --force
md2zh data/sample_en.txt
cat data/sample_en.html | md2zh - --format html
txt2zh --version
```

检查项:译文标签/属性/实体字节级完好、无 `@@@` 残留、零警告;txt 直通;stdin 输出正确;`txt2zh 0.6.0`。

- [ ] **Step 5: 提交与发布收尾**

```bash
git add data/ README.md CHANGELOG.md CLAUDE.md .superpowers/
git commit -m "docs: v0.6.0 样例、README/CHANGELOG/CLAUDE.md 同步

Co-Authored-By: Claude Code <noreply@anthropic.com>"
git switch main && git merge --ff-only v0.6.0-multiformat && git push origin main
git tag v0.6.0 && git push origin v0.6.0
```

(发布后 CLAUDE.md Recent Updates 回填真实 API 手工验证结果。)

## 自审记录

- 规格覆盖:§2 需求 R1-R10 全部落任务(Task 1 推断、Task 2 HTML、Task 3 TXT、Task 4 管线、Task 5 CLI/别名/版本、Task 6 文档与验证)。
- 类型一致性:全计划统一 `Format`(frozen dataclass)、`fmt: str | None`(对外)/`fmt: formats.Format | None`(内部)、`constraints`(list 入 api,tuple 存适配器)。
- 破坏面:内部函数 `fmt=None` 默认回落 md 保 11 处直调测试;`_prog()` 回落保 `"md2zh"` 断言;`markdown.CONSTRAINTS` 逐字迁移保 test_api 22 项;抽取行为不变保 test_markdown 18 项。
