import io
import sys

import pytest

from md2zh import api
from md2zh import cli
from md2zh import ignore
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
    monkeypatch.chdir(tmp_path)  # 隔离 CWD,避免加载项目根目录真实 .translateignore
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
    # 真实管道在 flush 时失败(缓冲写),故在 flush 上抛错以建模现实
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")

    class _BrokenStdout:
        def write(self, s):
            return len(s)  # 写入成功,进入缓冲

        def flush(self):
            raise BrokenPipeError

    monkeypatch.setattr(sys, "stdout", _BrokenStdout())
    assert cli.main([str(src)]) == translator.EX_SIGPIPE


def test_broken_pipe_einval_exit_141(monkeypatch, tmp_path):
    # MSYS 文本层管道断开可能抛 OSError EINVAL 而非 BrokenPipeError,同样按 141 静默退出
    import errno

    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")

    class _BrokenStdout:
        def write(self, s):
            return len(s)

        def flush(self):
            raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(sys, "stdout", _BrokenStdout())
    assert cli.main([str(src)]) == translator.EX_SIGPIPE

def test_help_contains_examples(capsys):
    # --help 应包含实用示例,加速上手
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "示例:\n  md2zh ABC.md" in out  # 示例逐行展示,不被折叠成一段
    assert "cat ABC.md | md2zh -" in out

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


def test_filelist_ignores_translateignore(monkeypatch, tmp_path, capsys):
    # 端到端:--filelist 自动读取 CWD 的 .translateignore,命中文件略过
    monkeypatch.chdir(tmp_path)
    kept = tmp_path / "keep.md"
    kept.write_text("# Hi", encoding="utf-8")
    skipped = tmp_path / "skip.md"
    skipped.write_text("# Hi", encoding="utf-8")
    (tmp_path / ".translateignore").write_text(str(skipped) + "\n", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(f"{kept}\n{skipped}\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    captured = capsys.readouterr()
    assert "md2zh: 忽略 " in captured.err
    assert "汇总: 成功 1,跳过 0,忽略 1,失败 0" in captured.err
    assert (tmp_path / "keep_zh.md").exists()
    assert not (tmp_path / "skip_zh.md").exists()


def test_filelist_no_ignore_file(monkeypatch, tmp_path, capsys):
    # 无 .translateignore 时行为不变:全部翻译,无「忽略」提示
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(str(src) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    captured = capsys.readouterr()
    assert "md2zh: 忽略" not in captured.err
    assert "汇总: 成功 1,跳过 0,忽略 0,失败 0" in captured.err


def test_filelist_ignore_gbk(monkeypatch, tmp_path, capsys):
    # GBK 编码的忽略文件可用(与 ds-translator 对齐);混入非 ASCII 注释强制走 GBK 回退分支
    monkeypatch.chdir(tmp_path)
    skipped = tmp_path / "skip.md"
    skipped.write_text("# Hi", encoding="utf-8")
    (tmp_path / ".translateignore").write_bytes(("# 注释:文档\n" + str(skipped) + "\n").encode("gbk"))
    lst = tmp_path / "list.txt"
    lst.write_text(str(skipped) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    assert "忽略 1" in capsys.readouterr().err


def test_repair_invalid_exits_usage(capsys):
    # --repair 仅接受 0-2 的整数,非法值走用法错误退出 64
    for bad in ("3", "-1", "x"):
        with pytest.raises(SystemExit) as e:
            cli.main(["--repair", bad, "a.md"])
        assert e.value.code == translator.EX_USAGE
    assert "md2zh" in capsys.readouterr().err


def test_repair_threads_to_translator(monkeypatch, tmp_path, capsys):
    # --repair 2 穿透到修复循环:恰 3 次调用;默认(不带选项)恰 1 次
    src = tmp_path / "A.md"
    src.write_text("[a](https://x)", encoding="utf-8")
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "坏译文"

    monkeypatch.setattr(api, "translate_text", fake)
    assert cli.main(["--repair", "2", str(src)]) == translator.EX_OK
    assert calls["n"] == 3
    calls["n"] = 0
    assert cli.main(["--force", str(src)]) == translator.EX_OK
    assert calls["n"] == 1


@pytest.mark.parametrize("argv, expected", [([], 10), (["-c", "5"], 5)])
def test_max_threads_passthrough(monkeypatch, tmp_path, argv, expected):
    # -c 透传到 run_batch:缺省 10,显式 5
    seen: dict = {}

    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads, ollama=False):
        seen["max_threads"] = max_threads
        return translator.EX_OK

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(translator, "parse_filelist", lambda p: ["a.md"])
    monkeypatch.setattr(translator, "run_batch", fake_run_batch)
    monkeypatch.setattr(ignore, "load_ignore", lambda *a, **k: None)
    assert cli.main(["--filelist", "l.txt", *argv]) == translator.EX_OK
    assert seen["max_threads"] == expected


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_max_threads_invalid_exits_64(bad, capsys):
    # 非正整数按用法错误退出 64
    with pytest.raises(SystemExit) as e:
        cli.main(["--filelist", "l.txt", "-c", bad])
    assert e.value.code == translator.EX_USAGE
    assert "-c/--max-threads 必须是正整数" in capsys.readouterr().err


def test_max_threads_ignored_in_single_file_mode(monkeypatch, tmp_path):
    # 单文件模式下 -c 被接受且不影响行为(静默忽略)
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main([str(src), "-c", "5"]) == translator.EX_OK
    assert (tmp_path / "A_zh.md").exists()


def test_help_contains_max_threads(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    assert "-c N, --max-threads N" in capsys.readouterr().out


@pytest.mark.parametrize("extra, msg", [
    (["--api-base", "http://x/v1"], "--ollama 与 --api-base 不能同时使用"),
    (["--model", "m"], "--ollama 与 --model 不能同时使用"),
    (["-c", "2"], "--ollama 强制单线程"),
])
def test_ollama_conflicts_exit_64(extra, msg, capsys):
    # --ollama 与显式后端参数冲突,按用法错误退出 64
    with pytest.raises(SystemExit) as e:
        cli.main(["--ollama", *extra, "a.md"])
    assert e.value.code == translator.EX_USAGE
    assert msg in capsys.readouterr().err


def test_ollama_resolves_defaults_and_single_thread(monkeypatch, tmp_path):
    # --ollama 缺省解析:本地端点 + index-translate-9b:latest + 单线程,标志透传
    seen = {}

    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads, ollama=False):
        seen.update(api_base=api_base, model=model,
                    max_threads=max_threads, ollama=ollama)
        return translator.EX_OK

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(translator, "parse_filelist", lambda p: ["a.md"])
    monkeypatch.setattr(translator, "run_batch", fake_run_batch)
    monkeypatch.setattr(ignore, "load_ignore", lambda *a, **k: None)
    assert cli.main(["--filelist", "l.txt", "--ollama"]) == translator.EX_OK
    assert seen["api_base"] == api.OLLAMA_API_BASE
    assert seen["model"] == api.OLLAMA_MODEL
    assert seen["max_threads"] == 1
    assert seen["ollama"] is True


def test_no_ollama_defaults_unchanged(monkeypatch, tmp_path):
    # 不带 --ollama 的缺省解析与现行一致:线上端点 + 默认模型 + 10 线程
    seen = {}

    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads, ollama=False):
        seen.update(api_base=api_base, model=model,
                    max_threads=max_threads, ollama=ollama)
        return translator.EX_OK

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(translator, "parse_filelist", lambda p: ["a.md"])
    monkeypatch.setattr(translator, "run_batch", fake_run_batch)
    monkeypatch.setattr(ignore, "load_ignore", lambda *a, **k: None)
    assert cli.main(["--filelist", "l.txt"]) == translator.EX_OK
    assert seen["api_base"] == api.DEFAULT_API_BASE
    assert seen["model"] == api.DEFAULT_MODEL
    assert seen["max_threads"] == 10
    assert seen["ollama"] is False


def test_ollama_with_c1_is_legal(monkeypatch, tmp_path):
    # -c 1 与 --ollama 不冲突(与强制单线程一致)
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main([str(src), "--ollama", "-c", "1"]) == translator.EX_OK
    assert (tmp_path / "A_zh.md").exists()


def test_ollama_single_file_end_to_end(monkeypatch, tmp_path):
    # 单文件 + --ollama:api_base/model 解析为本地值,ollama 透传到 API 层
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    calls = {}

    def fake_translate(api_base, model, prompt, max_tokens, ollama=False):
        calls.update(api_base=api_base, model=model, ollama=ollama)
        return "# 你好"

    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(api, "translate_text", fake_translate)
    assert cli.main([str(src), "--ollama"]) == translator.EX_OK
    assert calls["api_base"] == api.OLLAMA_API_BASE
    assert calls["model"] == api.OLLAMA_MODEL
    assert calls["ollama"] is True


def test_help_contains_ollama(capsys):
    # --help 输出含 --ollama 选项
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    assert "--ollama" in capsys.readouterr().out
