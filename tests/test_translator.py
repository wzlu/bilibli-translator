import io
import sys

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
    # 第一次译文加黑不成对,第二次修复
    outputs = iter(["好 **格式 好", "好 **格式** 好"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("好 **格式** 好", [], "http://x", "m", 4096)
    assert result == "好 **格式** 好"


def test_chunk_repair_exhausted_falls_back(monkeypatch):
    # 始终丢失链接:3 次尝试(1 次初译 + 2 次重译)后回退原文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096)
    assert result == "[a](https://x)"


def test_chunk_repair_warning_names_source(monkeypatch, capsys):
    # 修复警告必须携带文件路径,批量模式下才能定位问题文件
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, source="docs/a.md")
    assert result == "[a](https://x)"
    err = capsys.readouterr().err
    assert "md2zh: 警告: docs/a.md: 块校验失败,重译(1/2)" in err
    assert "md2zh: 警告: docs/a.md: 块重译耗尽,保留原文" in err


def test_chunk_repair_warning_without_source_keeps_format(monkeypatch, capsys):
    # 内部直接调用不带 source 时警告格式与现状一致,不出现空前缀
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096)
    err = capsys.readouterr().err
    assert "md2zh: 警告: 块重译耗尽,保留原文" in err
    assert "警告: :" not in err


def test_long_warning_names_source(monkeypatch, capsys):
    # 超长文本分段路径的块级警告同样携带 source
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "[a](https://x) " + "正文" * 2000  # 单段超 3000 字符,按不可分割块整段处理
    result = translator._translate_long(text, [], "http://x", "m", mapping={}, source="docs/a.md")
    assert result == text
    assert "md2zh: 警告: docs/a.md: 块重译耗尽,保留原文" in capsys.readouterr().err


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


def test_frontmatter_fallback_to_original(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("---\ntitle: Hello\n---\n\n正文", encoding="utf-8")
    # frontmatter 3 次尝试都改了 key,正文正常
    outputs = iter(["---\n标题: 错\n---", "---\n标题: 错\n---", "---\n标题: 错\n---", "译文"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator.translate_file(str(src), force=False, glossary=[],
                              api_base="http://x", model="m")
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "title: Hello" in content  # 原文 frontmatter 保留


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


def test_document_frontmatter_warning_names_source(monkeypatch, capsys):
    # 经 _translate_document 的 frontmatter 修复警告携带 source
    outputs = iter(["坏译文", "还是坏", "依然坏", "正文译文"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "---\ntitle: Hello\n---\n\nBody"
    result = translator._translate_document(text, [], "http://x", "m", source="docs/a.md")
    assert "title: Hello" in result  # frontmatter 回退原文,结构保留
    err = capsys.readouterr().err
    assert "md2zh: 警告: docs/a.md: frontmatter重译耗尽,保留原文" in err


def test_translate_file_warning_names_path(monkeypatch, tmp_path, capsys):
    # 端到端:文件模式的块级警告带源文件路径
    src = tmp_path / "A.md"
    src.write_text("[a](https://x)", encoding="utf-8")
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"  # 回退原文仍为成功
    assert f"md2zh: 警告: {src}: 块重译耗尽,保留原文" in capsys.readouterr().err


def test_run_stdin_warning_names_stdin(monkeypatch, capsys):
    # stdin 模式:块级警告用 <stdin> 标识
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(sys, "stdin", _FakeStdin("[a](https://x)".encode("utf-8")))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m") == translator.EX_OK
    assert "md2zh: 警告: <stdin>: 块重译耗尽,保留原文" in capsys.readouterr().err


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
