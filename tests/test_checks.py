from md2zh import checks


def test_check_bold_ok():
    assert checks.check_bold("**重要** 内容", "**重要** 内容") == []


def test_check_bold_count_mismatch():
    problems = checks.check_bold("**a** **b**", "**a** b")
    assert problems


def test_check_bold_unpaired():
    problems = checks.check_bold("", "**a")
    assert problems


def test_check_links_ok():
    assert checks.check_links("[文本](https://a.b)", "[译文](https://a.b)") == []


def test_check_links_url_changed():
    problems = checks.check_links("[a](https://a.b)", "[a](https://c.d)")
    assert problems


def test_check_tables_ok():
    src = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    dst = "| 甲 | 乙 |\n|---|---|\n| 一 | 二 |\n"
    assert checks.check_tables(src, dst) == []


def test_check_tables_row_mismatch():
    problems = checks.check_tables("| a |\n| b |\n", "| 甲 |\n")
    assert problems


def test_check_tables_col_mismatch():
    problems = checks.check_tables("| a | b |\n", "| 甲 |\n")
    assert problems


def test_check_frontmatter_ok():
    src = "---\ntitle: Hello\n---"
    dst = "---\ntitle: 你好\n---"
    assert checks.check_frontmatter(src, dst) == []


def test_check_frontmatter_key_changed():
    problems = checks.check_frontmatter("---\ntitle: Hello\n---", "---\n标题: 你好\n---")
    assert problems


def test_check_frontmatter_missing_markers():
    problems = checks.check_frontmatter("---\ntitle: Hello\n---", "title: 你好")
    assert problems


def test_check_placeholders_ok():
    src = "看 @@@CODEBLOCK_0@@@ 这里"
    assert checks.check_placeholders(src, src) == []


def test_check_placeholders_missing():
    problems = checks.check_placeholders("@@@CODEBLOCK_0@@@", "无")
    assert problems


def test_check_bold_odd_source_not_flagged():
    # 源文本身 ** 不成对时,不因译文奇偶性误报(否则该块永远无法通过校验)
    assert checks.check_bold("a ** b", "甲 ** 乙") == []
