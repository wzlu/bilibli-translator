"""ignore 模块测试:解析与精确路径匹配。"""

from md2zh import ignore


def test_load_missing_returns_empty(tmp_path):
    m = ignore.load_ignore(str(tmp_path / "no.ti"))
    assert not m.is_ignored(str(tmp_path / "A.md"))


def test_load_skips_blank_and_comments(tmp_path):
    f = tmp_path / ".translateignore"
    f.write_text("# 注释\n\n  \nD:\\x\\a.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a.md")
    assert not m.is_ignored("D:\\x\\b.md")


def test_exact_match_normalized(tmp_path):
    # 大小写与分隔符形态归一:Windows 路径小写化,/ 与 \ 等价
    f = tmp_path / ".translateignore"
    f.write_text("D:\\X\\Sub\\A.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("d:/x/sub/a.md")


def test_exact_relative_entry_resolves_from_cwd(tmp_path, monkeypatch):
    # 相对条目按当前工作目录解析(与 cli 的 CWD 自动发现一致)
    monkeypatch.chdir(tmp_path)
    f = tmp_path / ".translateignore"
    f.write_text("docs\\a.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored(str(tmp_path / "docs" / "a.md"))
    assert not m.is_ignored(str(tmp_path / "docs" / "b.md"))


def test_load_default_cwd(tmp_path, monkeypatch):
    # 缺省路径 ".translateignore" 相对 CWD 打开
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".translateignore").write_text("D:\\x\\a.md\n", encoding="utf-8")
    m = ignore.load_ignore()
    assert m.is_ignored("D:\\x\\a.md")


def test_load_with_bom(tmp_path):
    # 带 BOM(Windows 记事本保存)首个条目不得被 ﻿ 污染
    f = tmp_path / ".translateignore"
    f.write_bytes("﻿D:\\x\\a.md\n".encode("utf-8"))
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a.md")


def test_glob_double_star_recursive(tmp_path):
    # ** 跨段递归:任意层级下的 i18n 目录直接子文件
    f = tmp_path / ".translateignore"
    f.write_text("**\\i18n\\*\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\any\\deep\\i18n\\x.md")
    assert not m.is_ignored("D:\\any\\deep\\i18n\\sub\\x.md")  # 段内 * 不跨分隔符
    assert not m.is_ignored("D:\\any\\deep\\xi18n\\x.md")     # 段边界不过匹配


def test_glob_relative_right_aligned(tmp_path):
    # 相对模式从右侧匹配:任意前缀下的 docs 直接子文件
    f = tmp_path / ".translateignore"
    f.write_text("docs\\*.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\proj\\docs\\a.md")


def test_glob_relative_overmatch_known_limitation(tmp_path):
    # 规格 §11 固化的已知限制:无 ** 相对模式前缀 .* 可能过匹配段边界
    f = tmp_path / ".translateignore"
    f.write_text("docs\\a*.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\proj\\xdocs\\a.md")


def test_glob_question_and_class(tmp_path):
    f = tmp_path / ".translateignore"
    f.write_text("**\\v?.md\n**\\a[0-9].md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\v1.md")
    assert not m.is_ignored("D:\\x\\v12.md")
    assert m.is_ignored("D:\\x\\a7.md")
    assert not m.is_ignored("D:\\x\\a7x.md")


def test_glob_trailing_separator_direct_children(tmp_path):
    # 目录形式(尾部 \)追加段内 *:只匹配直接子文件,不递归
    f = tmp_path / ".translateignore"
    f.write_text("**\\reports\\\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\reports\\a.md")
    assert not m.is_ignored("D:\\x\\reports\\sub\\a.md")


def test_glob_absolute_pattern(tmp_path):
    # 绝对模式(盘符开头)不加右对齐前缀:锚定盘符
    f = tmp_path / ".translateignore"
    f.write_text("D:\\x\\**\\*.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a\\b.md")
    assert not m.is_ignored("D:\\y\\a\\b.md")


def test_unpaired_bracket_treated_literal(tmp_path):
    # 不成对 [ 不视为通配符,按精确路径处理
    f = tmp_path / ".translateignore"
    f.write_text("D:\\x\\a[b.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a[b.md")


def test_load_gbk_fallback(tmp_path):
    # 与 ds-translator 对齐:UTF-8 失败回退 GBK(中文 Windows 常见)
    f = tmp_path / ".translateignore"
    f.write_bytes("D:\\x\\文档.md\n".encode("gbk"))
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\文档.md")


def test_load_undecodable_warns_empty(tmp_path, capsys):
    # 两种编码都无法解码:警告后视为空表,不中断翻译
    f = tmp_path / ".translateignore"
    f.write_bytes(b"\xff\xff\xff")
    m = ignore.load_ignore(str(f))
    assert not m.is_ignored("D:\\x\\a.md")
    assert "md2zh: 警告" in capsys.readouterr().err


def test_bare_directory_line_matches_children(tmp_path):
    # 裁决:裸目录行(不含通配符)按"直接子文件"语义生效,不静默空转
    f = tmp_path / ".translateignore"
    f.write_text("reports\\\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\reports\\a.md")
    assert not m.is_ignored("D:\\x\\reports\\sub\\a.md")


def test_invalid_char_class_warns_and_skips(tmp_path, capsys):
    # 非法字符类按 §8 降级:警告并跳过该规则,其余规则继续生效
    f = tmp_path / ".translateignore"
    f.write_text("src\\a[z-a]*.md\nD:\\x\\b.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert not m.is_ignored("D:\\x\\src\\a1.md")
    assert m.is_ignored("D:\\x\\b.md")
    assert "md2zh: 警告" in capsys.readouterr().err


def test_unpaired_bracket_in_wildcard_pattern(tmp_path):
    # 通配模式内不成对 [ 按字面处理(补齐 _pattern_regex 该分支覆盖)
    f = tmp_path / ".translateignore"
    f.write_text("**\\a[bc.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a[bc.md")
    assert not m.is_ignored("D:\\x\\ab.md")


def test_load_directory_warns_empty(tmp_path, capsys):
    # 忽略路径为目录等 OSError 场景:警告 + 空表(§8 降级)
    d = tmp_path / "asdir"
    d.mkdir()
    m = ignore.load_ignore(str(d))
    assert not m.is_ignored("D:\\x\\a.md")
    assert "md2zh: 警告" in capsys.readouterr().err
