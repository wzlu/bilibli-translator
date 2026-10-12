import pytest

from md2zh import api
from md2zh import cli
from md2zh import translator


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "md2zh" in capsys.readouterr().out


def test_missing_args_exit_usage(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == translator.EX_USAGE
    assert "md2zh" in capsys.readouterr().err


def test_file_and_filelist_conflict(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["a.md", "--filelist", "l.txt"])
    assert e.value.code == translator.EX_USAGE


def test_single_file_missing_exit_66(tmp_path):
    assert cli.main([str(tmp_path / "no.md")]) == translator.EX_NOINPUT


def test_single_file_ok(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main([str(src)]) == translator.EX_OK


def test_glossary_missing_exit_66(tmp_path):
    assert cli.main([str(tmp_path / "a.md"),
                     "--glossary", "/nonexistent/g.json"]) == translator.EX_NOINPUT


def test_glossary_bad_json_exit_65(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("不是 json", encoding="utf-8")
    assert cli.main([str(tmp_path / "a.md"),
                     "--glossary", str(bad)]) == translator.EX_DATAERR


def test_filelist_mode(monkeypatch, tmp_path, capsys):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(str(src) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    assert str(tmp_path / "A_zh.md") in capsys.readouterr().out
