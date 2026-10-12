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
