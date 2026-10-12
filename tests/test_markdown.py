from md2zh import markdown


def test_no_frontmatter():
    fm, rest = markdown.split_frontmatter("# 标题\n\n正文\n")
    assert fm is None
    assert rest == "# 标题\n\n正文\n"


def test_frontmatter_split():
    text = "---\ntitle: Hello\n---\n\n# 正文\n"
    fm, rest = markdown.split_frontmatter(text)
    assert fm == "---\ntitle: Hello\n---\n"
    assert rest == "\n# 正文\n"


def test_closing_marker_detection():
    text = "---\ntitle: 测试\n---\n正文"
    fm, rest = markdown.split_frontmatter(text)
    assert fm == "---\ntitle: 测试\n---\n"
    assert rest == "正文"


def test_hr_not_frontmatter():
    # 仅一个 --- 行(水平分隔线),不应识别为 frontmatter
    text = "---\n\n# 正文\n"
    fm, rest = markdown.split_frontmatter(text)
    assert fm is None
    assert rest == text


def test_no_kv_not_frontmatter():
    # 首尾 --- 之间没有键值行,视为水平分隔线
    text = "---\n无冒号内容\n---\n\n# 正文\n"
    fm, rest = markdown.split_frontmatter(text)
    assert fm is None
    assert rest == text


def test_fenced_block_protected():
    src = "前文\n```python\nprint(1)\n```\n后文"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "```" not in protected
    assert "print(1)" not in protected
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_inline_code_protected():
    src = "使用 `os.replace` 完成替换"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "`" not in protected
    assert "os.replace" not in protected
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_unclosed_fence_left_as_text():
    src = "```\n未闭合"
    protected, mapping = markdown.protect_code_blocks(src)
    assert protected == src
    assert mapping == {}


def test_multiple_blocks_roundtrip():
    src = "# 标题\n\n```bash\nls\n```\n\n正文 `code` 结束\n"
    protected, mapping = markdown.protect_code_blocks(src)
    assert len(mapping) == 2
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_nested_fence_not_split():
    # 4 反引号围栏内含 3 反引号围栏:不得在内层处截断
    src = "````markdown\n```py\nprint(1)\n```\n````\n"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "print(1)" not in protected
    assert len(mapping) == 1
    assert markdown.restore_code_blocks(protected, mapping) == src
