import io
import sys

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

def test_filelist_non_utf8_exit_65(tmp_path, capsys):
    # 非 UTF-8 文件列表应返回 EX_DATAERR,而不是让 UnicodeDecodeError 崩溃
    lst = tmp_path / "list.txt"
    lst.write_bytes("文档.md\n".encode("gbk"))
    assert cli.main(["--filelist", str(lst)]) == translator.EX_DATAERR
    assert "Traceback" not in capsys.readouterr().err

def test_broken_pipe_exit_141(monkeypatch, tmp_path):
    # 下游管道提前关闭(如 md2zh x | head)不得打印堆栈,按 128+SIGPIPE 静默退出
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")

    class _BrokenStdout:
        def write(self, s):
            raise BrokenPipeError

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _BrokenStdout())
    assert cli.main([str(src)]) == translator.EX_SIGPIPE

def test_help_contains_examples(capsys):
    # --help 应包含实用示例,加速上手
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "示例:\n  md2zh ABC.md" in out  # 示例逐行展示,不被折叠成一段

def test_stdin_mode(monkeypatch, capsys):
    # md2zh - 从 stdin 读入,译文写 stdout,stderr 无输出
    class _FakeStdin:
        def __init__(self, data: bytes):
            self.buffer = io.BytesIO(data)

    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"# Hi"))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["-"]) == translator.EX_OK
    captured = capsys.readouterr()
    assert captured.out == "# 你好\n"
    assert captured.err == ""
