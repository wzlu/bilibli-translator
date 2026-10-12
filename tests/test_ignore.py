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
