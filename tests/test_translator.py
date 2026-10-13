import io
import os
import sys
import threading
import time

import pytest

from md2zh import api
from md2zh import ignore
from md2zh import translator


def test_zh_path():
    assert translator._zh_path("/tmp/ABC.md") == "/tmp/ABC_zh.md"


def test_translate_file_writes_zh(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("# Hello\n\n正文", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好\n\n译文")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    out = tmp_path / "ABC_zh.md"
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "# 你好\n\n译文"


def test_translate_file_skips_existing(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("# Hello", encoding="utf-8")
    zh = tmp_path / "ABC_zh.md"
    zh.write_text("已有", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "skipped"
    assert zh.read_text(encoding="utf-8") == "已有"


def test_translate_file_force_overwrites(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("# Hello", encoding="utf-8")
    zh = tmp_path / "ABC_zh.md"
    zh.write_text("已有", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=True, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert zh.read_text(encoding="utf-8") == "# 你好"


def test_translate_file_preserves_code_block(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("前文\n```python\nprint(1)\n```\n后文", encoding="utf-8")

    def fake(api_base, model, prompt, max_tokens):
        return "译文前\n@@@CODEBLOCK_0@@@\n译文后"

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "ABC_zh.md").read_text(encoding="utf-8")
    assert "print(1)" in content
    assert "```python" in content


def test_translate_file_missing(monkeypatch, tmp_path):
    result = translator.translate_file(str(tmp_path / "no.md"), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_NOINPUT


def test_translate_file_not_md(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    result = translator.translate_file(str(p), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_NOINPUT


def test_translate_file_api_error(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")

    def fake(*a, **k):
        raise api.TranslateError("网络错误")

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_TEMPFAIL


def test_translate_file_preserves_crlf(monkeypatch, tmp_path):
    # CRLF 源文件输出必须保持 CRLF(格式一致)
    src = tmp_path / "A.md"
    src.write_bytes(b"# Hello\r\n\r\nBody\r\n")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert (tmp_path / "A_zh.md").read_bytes() == "# 你好\r\n".encode("utf-8")


def test_translate_file_preserves_lf(monkeypatch, tmp_path):
    # LF 源文件输出必须保持 LF(格式一致)
    src = tmp_path / "A.md"
    src.write_bytes(b"# Hello\n\nBody\n")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert (tmp_path / "A_zh.md").read_bytes() == "# 你好\n".encode("utf-8")


def test_chunk_repair_then_success(monkeypatch):
    # 第一次译文丢失链接,第二次修复(repair=1)
    outputs = iter(["没有链接的译文", "[译文](https://x)"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[text](https://x)", [], "http://x", "m", 4096, repair=1)
    assert result == "[译文](https://x)"


def test_chunk_repair_exhausted_accepts_translation(monkeypatch, capsys):
    # 始终丢失链接:3 次尝试(1 次初译 + 2 次重译)后采用最后一次译文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, repair=2)
    assert result == "依然坏"


def test_chunk_repair_warning_names_source(monkeypatch, capsys):
    # 修复警告必须携带文件路径,批量模式下才能定位问题文件
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096,
                                         source="docs/a.md", repair=2)
    assert result == "依然坏"
    err = capsys.readouterr().err
    assert "md2zh: 警告: docs/a.md: 块校验失败,重译(1/2)" in err
    assert "md2zh: 警告: docs/a.md: 块重译耗尽,采用译文" in err


def test_chunk_repair_warning_without_source_keeps_format(monkeypatch, capsys):
    # 内部直接调用不带 source 时警告格式与现状一致,不出现空前缀
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, repair=2)
    err = capsys.readouterr().err
    assert "md2zh: 警告: 块重译耗尽,采用译文" in err
    assert "警告: :" not in err


def test_long_warning_names_source(monkeypatch, capsys):
    # 超长文本分段路径的块级警告同样携带 source,耗尽后采用译文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "[a](https://x) " + "正文" * 2000  # 单段超 3000 字符,按不可分割块整段处理
    result = translator._translate_long(text, [], "http://x", "m", mapping={},
                                        source="docs/a.md", repair=2)
    assert result == "依然坏"
    assert "md2zh: 警告: docs/a.md: 块重译耗尽,采用译文" in capsys.readouterr().err


def test_frontmatter_translated(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("---\ntitle: Hello\n---\n\n正文", encoding="utf-8")
    outputs = iter(["---\ntitle: 你好\n---", "译文正文"])

    def fake(*a, **k):
        return next(outputs)

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "title: 你好" in content
    assert "译文正文" in content


def test_frontmatter_key_changed_accepted(monkeypatch, tmp_path):
    # frontmatter 不再校验:模型改了 key 也直接采用,不回退原文、不重译
    src = tmp_path / "A.md"
    src.write_text("---\ntitle: Hello\n---\n\n正文", encoding="utf-8")
    calls = {"n": 0}
    # 3 份同款改 key 译文 + 正文:旧实现 3 次校验失败后回退原文(共 4 次调用)
    outputs = iter(["---\n标题: 错\n---"] * 3 + ["译文"])

    def fake(*a, **k):
        calls["n"] += 1
        return next(outputs)

    monkeypatch.setattr(api, "translate_text", fake)
    translator.translate_file(str(src), force=False, glossary=[],
                              api_base="http://x", model="m")
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "标题: 错" in content        # 译文 frontmatter 直接采用
    assert "title: Hello" not in content  # 不回退原文
    assert calls["n"] == 2               # frontmatter + 正文各一次,无重译


def test_long_document_chunked(monkeypatch, tmp_path):
    src = tmp_path / "long.md"
    paras = "\n\n".join(f"第 {i} 段内容" for i in range(100))
    src.write_text(paras, encoding="utf-8")
    monkeypatch.setattr(translator, "SINGLE_CALL_LIMIT", 100)
    monkeypatch.setattr(translator, "CHUNK_SIZE", 100)
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "译文段"

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert calls["n"] > 1  # 发生了分段,多次调用
    # 每块译文回挂源块尾随空白(末块无尾随空白),分段边界不得焊接
    assert (tmp_path / "long_zh.md").read_text(encoding="utf-8") == ("译文段" + "\n\n") * (calls["n"] - 1) + "译文段"


def test_translate_file_non_utf8(tmp_path):
    # 非 UTF-8 源文件应返回 EX_DATAERR,而不是让 UnicodeDecodeError 崩溃
    src = tmp_path / "A.md"
    src.write_bytes("# 标题".encode("gbk"))
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_DATAERR


def test_oversized_chunk_budget_scaled(monkeypatch, tmp_path):
    # 不可分割的超限块(大表格)按块长放大输出预算,避免确定性截断
    big_table = "| " + "a" * 5000 + " | b |\n"
    src = tmp_path / "big.md"
    src.write_text(big_table, encoding="utf-8")
    monkeypatch.setattr(translator, "SINGLE_CALL_LIMIT", 100)
    budgets = []

    def fake(api_base, model, prompt, max_tokens):
        budgets.append(max_tokens)
        return big_table.rstrip()  # 原样返回(API 层 strip 后的形态)

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert budgets[0] > translator.MAX_TOKENS_CHUNK  # 预算被放大
    assert budgets[0] >= len(big_table) * 2  # 覆盖两倍块长的输出需求


def test_parse_filelist(tmp_path):
    lst = tmp_path / "list.txt"
    lst.write_text("# 注释\n\na.md\n  b.md  \n\n", encoding="utf-8")
    assert translator.parse_filelist(str(lst)) == ["a.md", "b.md"]


def test_parse_filelist_with_bom(tmp_path):
    # 带 BOM 的文件列表(Windows 记事本保存)首个条目不得被 ﻿ 污染
    lst = tmp_path / "list.txt"
    lst.write_bytes("﻿a.md\nb.md\n".encode("utf-8"))
    assert translator.parse_filelist(str(lst)) == ["a.md", "b.md"]


def test_run_single_ok_prints_path(monkeypatch, tmp_path, capsys):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_single(str(src), force=False, glossary=[],
                               api_base="http://x", model="m")
    assert rc == translator.EX_OK
    assert str(tmp_path / "A_zh.md") in capsys.readouterr().out


def test_run_single_missing_returns_66(tmp_path, capsys):
    rc = translator.run_single(str(tmp_path / "no.md"), force=False, glossary=[],
                               api_base="http://x", model="m")
    assert rc == translator.EX_NOINPUT
    assert "md2zh:" in capsys.readouterr().err


def test_run_batch_partial_success(monkeypatch, tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    # 坏文件在前:钉住"失败后继续处理"语义
    paths = [str(tmp_path / "missing.md"), str(good)]
    rc = translator.run_batch(paths, force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_PARTIAL
    captured = capsys.readouterr()
    assert "成功 1" in captured.err
    assert "失败 1" in captured.err
    assert str(tmp_path / "good_zh.md") in captured.out
    assert (tmp_path / "good_zh.md").exists()


def test_run_batch_all_ok_returns_0(monkeypatch, tmp_path):
    files = []
    for name in ("a.md", "b.md"):
        p = tmp_path / name
        p.write_text("# Hi", encoding="utf-8")
        files.append(str(p))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_batch(files, force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_OK


class _FakeStdin:
    """仅提供 run_stdin 需要的 .buffer 字节流。"""

    def __init__(self, data: bytes):
        self.buffer = io.BytesIO(data)


def test_run_stdin_ok(monkeypatch, capsys):
    # stdin 模式:BOM 容忍,译文写 stdout,stderr 无输出
    monkeypatch.setattr(sys, "stdin", _FakeStdin("﻿# Hi".encode("utf-8")))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m") == translator.EX_OK
    captured = capsys.readouterr()
    assert captured.out == "# 你好\n"
    assert captured.err == ""


def test_run_stdin_empty_skips_api(monkeypatch, capsys):
    # 空输入直接成功退出,不调用 API
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return ""

    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"   \n"))
    monkeypatch.setattr(api, "translate_text", fake)
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m") == translator.EX_OK
    assert calls["n"] == 0
    assert capsys.readouterr().out == ""


def test_run_stdin_non_utf8_exit_65(monkeypatch, capsys):
    # 非 UTF-8 stdin 返回 EX_DATAERR,不打印堆栈
    monkeypatch.setattr(sys, "stdin", _FakeStdin("文档".encode("gbk")))
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m") == translator.EX_DATAERR
    assert "Traceback" not in capsys.readouterr().err


def test_run_stdin_preserves_trailing_newline(monkeypatch, capsys):
    # 源文以换行结尾时输出以 \n\n 结尾(与文件模式字节一致),不得再多补一个空行
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"# Hi\n"))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好\n")
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m") == translator.EX_OK
    assert capsys.readouterr().out == "# 你好\n\n"


def test_run_stdin_folds_mid_text_crlf(monkeypatch, capsys):
    # API 中途混入 CRLF 时输出前折叠为 LF,保证 LF 源输出 LF(与文件模式一致)
    monkeypatch.setattr(sys, "stdin", _FakeStdin(b"# Hi"))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好\r\n世界")
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m") == translator.EX_OK
    assert capsys.readouterr().out == "# 你好\n世界\n"


def test_run_batch_ignored_files_skipped(monkeypatch, tmp_path, capsys):
    # 忽略命中:不调用翻译 API,计入「忽略」数
    good = tmp_path / "good.md"
    good.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(good) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "# 你好"

    monkeypatch.setattr(api, "translate_text", fake)
    rc = translator.run_batch([str(good)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert calls["n"] == 0
    captured = capsys.readouterr()
    assert "md2zh: 忽略 " in captured.err
    assert "成功 0" in captured.err


def test_run_batch_all_ignored_returns_0(tmp_path, capsys):
    # 全部被忽略 → 退出 0(符合"0 成功含全部跳过"契约)
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    rc = translator.run_batch([str(p)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert "汇总: 成功 0,跳过 0,忽略 1,失败 0" in capsys.readouterr().err


def test_run_batch_ignored_and_failed_returns_1(monkeypatch, tmp_path, capsys):
    # 忽略与失败混合:忽略不算失败,存在失败仍退出 1;mock API 防退化路径真实请求
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_batch([str(p), str(tmp_path / "missing.md")], force=False,
                              glossary=[], api_base="http://x", model="m",
                              ignore_matcher=matcher)
    assert rc == translator.EX_PARTIAL
    assert "汇总: 成功 0,跳过 0,忽略 1,失败 1" in capsys.readouterr().err


def test_run_batch_ignore_wins_over_force(monkeypatch, tmp_path):
    # --force 不覆盖忽略:被忽略文件即使已有译文也不翻译
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "# 你好"

    monkeypatch.setattr(api, "translate_text", fake)
    rc = translator.run_batch([str(p)], force=True, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert calls["n"] == 0


def test_document_frontmatter_no_repair_warning(monkeypatch, capsys):
    # frontmatter 不再校验:经 _translate_document 无重译、无警告,译文直接采用
    outputs = iter(["---\n标题: 你好\n---"] * 3 + ["正文译文"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "---\ntitle: Hello\n---\n\nBody"
    result = translator._translate_document(text, [], "http://x", "m", source="docs/a.md")
    assert "标题: 你好" in result
    assert "title: Hello" not in result
    err = capsys.readouterr().err
    assert "frontmatter" not in err


def test_translate_file_warning_names_path(monkeypatch, tmp_path, capsys):
    # 端到端:文件模式的块级警告带源文件路径;耗尽后译文文件内容为最后一次译文
    src = tmp_path / "A.md"
    src.write_text("[a](https://x)", encoding="utf-8")
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m", repair=2)
    assert result.status == "ok"
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert content == "依然坏"
    assert f"md2zh: 警告: {src}: 块重译耗尽,采用译文" in capsys.readouterr().err


def test_run_stdin_warning_names_stdin(monkeypatch, capsys):
    # stdin 模式:块级警告用 <stdin> 标识,stdout 为最后一次译文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(sys, "stdin", _FakeStdin("[a](https://x)".encode("utf-8")))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m", repair=2) == translator.EX_OK
    cap = capsys.readouterr()
    assert cap.out == "依然坏\n"
    assert "md2zh: 警告: <stdin>: 块重译耗尽,采用译文" in cap.err


def test_long_context_restores_placeholders(monkeypatch):
    # 分段上下文不得携带占位符令牌:上一块尾部的行内代码在上下文中必须是还原后的真实代码,
    # 否则模型会把上一块的占位符带入输出,被判「未知占位符」而整块回退
    prompts = []

    def fake(*a, **k):
        prompt = a[2]  # translate_text(api_base, model, prompt, max_tokens)
        prompts.append(prompt)
        # 伪译文:回传【源文】原文(占位符与本块一致),校验必然通过
        return prompt.split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]

    monkeypatch.setattr(api, "translate_text", fake)
    chunk1 = "正文段落。" * 570 + " 结尾代码 `code_tail`。"
    chunk2 = "后续正文。" * 200 + " 代码 `code_2`。"
    text = chunk1 + "\n\n" + chunk2
    protected, mapping = translator.markdown.protect_code_blocks(text)

    result = translator._translate_long(protected, [], "http://x", "m", mapping=mapping)

    # 文档级路径:保护 → 分段翻译 → 还原,闭环应还原出原始文本
    assert translator.markdown.restore_code_blocks(result, mapping) == text
    assert len(prompts) == 2
    # 第二块请求携带上下文:截取【上下文参考】与【源文】之间的段落
    ctx = prompts[1].split("【上下文参考】(仅供术语一致参考,不要翻译本段)\n", 1)[1].split("\n【源文】", 1)[0]
    assert "`code_tail`" in ctx          # 上一块尾部代码已还原
    assert "@@@INLINE" not in ctx        # 上下文中无占位符令牌
    assert "@@@CODEBLOCK" not in ctx
    # 本块【源文】仍保持占位符保护(代码不出现在源文、占位符在)
    src = prompts[1].split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]
    assert "@@@INLINE_" in src
    assert "`code_2`" not in src


def test_translate_file_link_url_restored(monkeypatch, tmp_path):
    # 链接 URL 占位符化:模型只能看到占位符,译文还原后 url 原样、无占位符残留
    src = tmp_path / "A.md"
    src.write_text("# 标题\n\n见 [官方文档](https://docs.example.com/a) 了解。", encoding="utf-8")

    def fake(*a, **k):
        prompt = a[2]
        # 模型视角:真实 url 不得出现在任何 API 请求中
        assert "https://docs.example.com/a" not in prompt
        # 回传【源文】原文:占位符与本块一致,校验通过
        return prompt.split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "https://docs.example.com/a" in content
    assert "[官方文档]" in content
    assert "@@@URL" not in content


def test_chunk_repair_warning_retry_counter_bounded(monkeypatch, capsys):
    # 重译计数器不得越界:耗尽路径恰为 重译(1/2)、重译(2/2),无 重译(3/2)
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, repair=2)
    err = capsys.readouterr().err
    assert "重译(1/2)" in err
    assert "重译(2/2)" in err
    assert "重译(3/2)" not in err
    assert "块重译耗尽,采用译文" in err


def test_chunk_bold_drift_accepted(monkeypatch):
    # 加黑不再校验:译文丢失 ** 标记仍被接受,不回退原文
    outputs = iter(["粗体内容", "粗体内容", "粗体内容"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("**bold** 内容", [], "http://x", "m", 4096)
    assert result == "粗体内容"


def test_chunk_default_no_repair_accepts_translation(monkeypatch, capsys):
    # 默认不重译:校验失败仅警告一次并采用译文,不回退原文
    calls = {"n": 0}
    outputs = iter(["坏译文"] * 3)

    def fake(*a, **k):
        calls["n"] += 1
        return next(outputs)

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096)
    assert result == "坏译文"
    assert calls["n"] == 1
    err = capsys.readouterr().err
    assert "块校验失败,采用译文" in err
    assert "重译" not in err


def test_chunk_repair_one_attempts_twice(monkeypatch, capsys):
    # repair=1:恰 2 次调用,耗尽后采用最后一次译文
    calls = {"n": 0}
    outputs = iter(["坏译文", "还是坏", "还是坏"])

    def fake(*a, **k):
        calls["n"] += 1
        return next(outputs)

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, repair=1)
    assert result == "还是坏"
    assert calls["n"] == 2
    err = capsys.readouterr().err
    assert "块校验失败,重译(1/1)" in err
    assert "块重译耗尽,采用译文" in err


def test_run_stdin_default_no_repair_accepts(monkeypatch, capsys):
    # stdin 模式默认不重译:校验失败采用译文,stdout 为译文
    monkeypatch.setattr(sys, "stdin", _FakeStdin("[a](https://x)".encode("utf-8")))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "坏译文")
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m",
                                repair=0) == translator.EX_OK
    cap = capsys.readouterr()
    assert cap.out == "坏译文\n"
    assert "md2zh: 警告: <stdin>: 块校验失败,采用译文" in cap.err


def test_run_batch_parallel_submits_all(monkeypatch, capsys):
    # 三个文件的门闩全部到达后才放行:证明并发提交(顺序版会卡在第一个门闩上)
    started: list[str] = []
    gate = threading.Event()

    def fake(src_path, *, force, glossary, api_base, model, repair):
        started.append(src_path)
        gate.wait()
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    paths = ["f0.md", "f1.md", "f2.md"]
    out: dict[str, int] = {}

    def run():
        out["rc"] = translator.run_batch(paths, force=False, glossary=[],
                                         api_base="http://x", model="m", max_threads=3)

    t = threading.Thread(target=run)
    t.start()
    try:
        deadline = time.time() + 5
        while len(started) < 3 and time.time() < deadline:
            time.sleep(0.01)
        assert len(started) == 3, "线程池未同时启动全部任务"
    finally:
        gate.set()  # 无论断言成败都放行,避免后台线程悬挂
    t.join(10)
    assert not t.is_alive()
    assert out["rc"] == translator.EX_OK
    assert set(capsys.readouterr().out.splitlines()) == {"f0.md_zh", "f1.md_zh", "f2.md_zh"}


def test_run_batch_completed_first_printed_first(monkeypatch, capsys):
    # 慢文件先提交、快文件后提交:完成即输出,快文件路径先出现(乱序)
    def fake(src_path, *, force, glossary, api_base, model, repair):
        time.sleep(0.5 if src_path.endswith("slow.md") else 0.05)
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch(["slow.md", "fast.md"], force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=2)
    assert rc == translator.EX_OK
    assert capsys.readouterr().out.splitlines() == ["fast.md_zh", "slow.md_zh"]


def test_run_batch_ignored_not_submitted(monkeypatch, tmp_path, capsys):
    # 忽略命中的文件不进入线程池(顺序版语义保留)
    def fake(src_path, **k):
        raise AssertionError(f"忽略文件不应提交翻译: {src_path}")

    monkeypatch.setattr(translator, "translate_file", fake)
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    rc = translator.run_batch([str(p)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert "汇总: 成功 0,跳过 0,忽略 1,失败 0" in capsys.readouterr().err


def test_run_batch_unexpected_error_continues(monkeypatch, capsys):
    # 未知异常兜底:计入失败并继续处理其余文件
    def fake(src_path, *, force, glossary, api_base, model, repair):
        if src_path == "bad.md":
            raise RuntimeError("模拟未知回归")
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch(["bad.md", "good.md"], force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=2)
    assert rc == translator.EX_PARTIAL
    err = capsys.readouterr().err
    assert "失败 bad.md" in err
    assert "汇总: 成功 1,跳过 0,忽略 0,失败 1" in err


def test_run_batch_keyboard_interrupt_reraises(monkeypatch):
    # 中断从 fut.result() 传出后经外层 shutdown 不等待关停并重新抛出
    def fake(src_path, *, force, glossary, api_base, model, repair):
        raise KeyboardInterrupt

    monkeypatch.setattr(translator, "translate_file", fake)
    with pytest.raises(KeyboardInterrupt):
        translator.run_batch(["a.md"], force=False, glossary=[],
                             api_base="http://x", model="m", max_threads=1)


def test_run_batch_max_threads_one_matches_sequential(monkeypatch, tmp_path, capsys):
    # max_threads=1 与顺序版行为一致(回归对照)
    good = tmp_path / "good.md"
    good.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    paths = [str(tmp_path / "missing.md"), str(good)]
    rc = translator.run_batch(paths, force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=1)
    assert rc == translator.EX_PARTIAL
    captured = capsys.readouterr()
    assert "成功 1" in captured.err
    assert "失败 1" in captured.err
    assert str(good)[:-3] + "_zh.md" in captured.out


def test_run_batch_threads_write_zh_files(monkeypatch, tmp_path):
    # 真实线程小规模集成:多线程并行写盘,全部译文生成且内容正确
    files = []
    for name in ("a.md", "b.md", "c.md"):
        p = tmp_path / name
        p.write_text("# Hi", encoding="utf-8")
        files.append(str(p))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_batch(files, force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=4)
    assert rc == translator.EX_OK
    for p in files:
        zh = p[:-3] + "_zh.md"
        assert os.path.exists(zh)
        with open(zh, encoding="utf-8") as f:
            assert "# 你好" in f.read()


def test_run_batch_keyboard_interrupt_does_not_wait(monkeypatch):
    # KI 时不等待运行中任务:run_batch 应在第二个任务仍在运行期间重新抛出
    task2_running = threading.Event()
    release = threading.Event()
    ki_raised = threading.Event()

    def fake(src_path, *, force, glossary, api_base, model, repair):
        if src_path == "first.md":
            # 等第二个任务进入运行态再抛 KI,消除取队竞态:确保中断时确有运行中任务
            task2_running.wait(5)
            raise KeyboardInterrupt
        task2_running.set()
        release.wait(10)
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)

    def run():
        try:
            translator.run_batch(["first.md", "second.md"], force=False, glossary=[],
                                 api_base="http://x", model="m", max_threads=2)
        except KeyboardInterrupt:
            ki_raised.set()

    t = threading.Thread(target=run)
    t.start()
    try:
        assert task2_running.wait(5), "第二个任务未开始运行"
        # 关键断言:task2 仍在运行时 KI 已重新抛出(不等待关停)
        assert ki_raised.wait(5), "run_batch 等待了运行中任务才重新抛出"
    finally:
        release.set()
    t.join(10)
    assert not t.is_alive()


def test_warn_writes_message(capsys):
    # _warn 串行化 stderr 写入;锁行为难以直接断言,此处钉住消息格式
    translator._warn("md2zh: 警告: 测试警告")
    assert "md2zh: 警告: 测试警告" in capsys.readouterr().err


class _SplitWriter:
    """把每次 write 拆两半并让出 GIL:无锁并发下必然交错,有锁则行完整。"""

    def __init__(self):
        self.buf = ""

    def write(self, s):
        half = len(s) // 2
        self.buf += s[:half]
        time.sleep(0.001)  # 让出 GIL,给另一线程交错窗口
        self.buf += s[half:]
        return len(s)

    def flush(self):
        pass


def test_warn_serializes_concurrent_lines(monkeypatch):
    # 两个线程并发 _warn:锁保证每行完整(守卫测试,钉住 _warn 串行化)
    writer = _SplitWriter()
    monkeypatch.setattr(sys, "stderr", writer)
    msg_a = "md2zh: 警告: " + "A" * 200
    msg_b = "md2zh: 警告: " + "B" * 200

    def spam(msg):
        for _ in range(100):
            translator._warn(msg)

    threads = [threading.Thread(target=spam, args=(m,)) for m in (msg_a, msg_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert writer.buf, "并发 _warn 无输出,断言失效"
    for line in writer.buf.split("\n"):
        if line:
            assert line in (msg_a, msg_b), "并发 _warn 行间交错"


def test_run_batch_stderr_goes_through_warn(monkeypatch):
    # run_batch 主线程的 stderr 打印全部经 _warn 串行化(路由契约)
    seen: list[str] = []

    def fake_warn(message):
        seen.append(message)

    def fake_translate(src_path, *, force, glossary, api_base, model, repair):
        return translator.TranslateResult("failed", "模拟失败", translator.EX_TEMPFAIL)

    monkeypatch.setattr(translator, "_warn", fake_warn)
    monkeypatch.setattr(translator, "translate_file", fake_translate)
    rc = translator.run_batch(["a.md"], force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_PARTIAL
    assert any("失败 a.md" in m for m in seen)
    assert any("汇总: 成功 0,跳过 0,忽略 0,失败 1" in m for m in seen)


def test_run_batch_stderr_routes_all_branches(monkeypatch, tmp_path):
    # 路由契约补全:忽略/跳过/兜底三条分支同样经 _warn
    seen: list[str] = []

    def fake_warn(message):
        seen.append(message)

    monkeypatch.setattr(translator, "_warn", fake_warn)
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))

    def fake_translate(src_path, *, force, glossary, api_base, model, repair):
        if src_path == "skip.md":
            return translator.TranslateResult("skipped", "译文已存在", 0)
        if src_path == "boom.md":
            raise RuntimeError("模拟未知回归")
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake_translate)
    rc = translator.run_batch([str(p), "skip.md", "boom.md"], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_PARTIAL
    assert any("忽略" in m and "a.md" in m for m in seen)
    assert any("跳过 skip.md" in m for m in seen)
    assert any("失败 boom.md" in m for m in seen)
    assert any("汇总: 成功 0,跳过 1,忽略 1,失败 1" in m for m in seen)
