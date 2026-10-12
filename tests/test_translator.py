from md2zh import api
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
    assert (tmp_path / "long_zh.md").read_text(encoding="utf-8") == "译文段" * calls["n"]


def test_translate_file_non_utf8(tmp_path):
    # 非 UTF-8 源文件应返回 EX_DATAERR,而不是让 UnicodeDecodeError 崩溃
    src = tmp_path / "A.md"
    src.write_bytes("# 标题".encode("gbk"))
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_DATAERR
