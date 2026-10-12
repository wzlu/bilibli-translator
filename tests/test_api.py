import pytest

from md2zh import api


def test_load_glossary_default_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DEFAULT_GLOSSARY", str(tmp_path / "no.json"))
    assert api.load_glossary(None) == []


def test_load_glossary_explicit_missing():
    with pytest.raises(FileNotFoundError):
        api.load_glossary("/nonexistent/glossary.json")


def test_load_glossary_ok(tmp_path):
    p = tmp_path / "g.json"
    p.write_text('{"carbon fiber": "碳纤维", "API": "API"}', encoding="utf-8")
    assert api.load_glossary(str(p)) == ["carbon fiber→碳纤维", "API→API"]


def test_load_glossary_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("不是 json", encoding="utf-8")
    with pytest.raises(ValueError):
        api.load_glossary(str(p))


def test_build_prompt_contains_constraints():
    prompt = api.build_prompt("Hello", [], "")
    assert "【源文】" in prompt and "Hello" in prompt
    assert "【约束要求】" in prompt
    assert "严格保留 markdown 语法结构" in prompt
    assert "不得翻译或修改 @@@...@@@ 占位符" in prompt
    assert "只输出译文,不要有任何额外说明。" in prompt


def test_build_prompt_glossary_and_fix():
    prompt = api.build_prompt("x", ["A→甲"], "加黑标记不成对")
    assert "【硬性要求】专名/术语对照: A→甲" in prompt
    assert "上次翻译存在以下问题,请修正: 加黑标记不成对" in prompt


def test_build_prompt_with_context():
    prompt = api.build_prompt("x", [], context="前文参考")
    assert "【上下文参考】" in prompt
    assert "前文参考" in prompt


def test_build_frontmatter_prompt():
    prompt = api.build_frontmatter_prompt("---\ntitle: Hi\n---", [], "")
    assert "key 保持不变,只翻译 value" in prompt
    assert "title: Hi" in prompt
    assert "保持首尾 --- 标记" in prompt


def test_build_frontmatter_prompt_glossary_and_fix():
    # 钉住共享约束装配逻辑在 frontmatter 侧的文本,防止两处漂移
    prompt = api.build_frontmatter_prompt("---\ntitle: Hi\n---", ["A→甲"], "缺 --- 标记")
    assert "【硬性要求】专名/术语对照: A→甲" in prompt
    assert "上次翻译存在以下问题,请修正: 缺 --- 标记" in prompt
