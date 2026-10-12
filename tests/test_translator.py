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
