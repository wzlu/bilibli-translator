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

def test_load_glossary_default_non_dict_warns(tmp_path, monkeypatch, capsys):
    # 默认术语表不是 JSON 对象时与格式错误同样警告,而非静默忽略
    p = tmp_path / "g.json"
    p.write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setattr(api, "DEFAULT_GLOSSARY", str(p))
    assert api.load_glossary(None) == []
    assert "警告" in capsys.readouterr().err


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


import json

import requests


class _FakeResponse:
    """模拟 requests 流式响应。"""

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for ln in self._lines:
            yield ln.encode("utf-8")


def _sse(delta: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": delta}}]})


def test_translate_text_stream(monkeypatch):
    calls = {}

    def fake_post(url, json, timeout, stream, headers=None):
        calls["payload"] = json
        calls["headers"] = headers
        return _FakeResponse([_sse("你"), _sse("好"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    result = api.translate_text("http://x/v1", "m", "提示词", 1024)
    assert result == "你好"
    assert calls["payload"]["stream"] is True
    assert calls["payload"]["chat_template_kwargs"] == {"enable_thinking": False}
    # 网关对默认 UA 返回 412,必须显式携带 User-Agent
    assert calls["headers"]["User-Agent"] == "Index-Translate-Client/1.0"


def test_translate_text_retries_then_raises(monkeypatch):
    count = {"n": 0}

    def fake_post(url, json, timeout, stream, headers=None):
        count["n"] += 1
        raise requests.ConnectionError("网络错误")

    monkeypatch.setattr(api.requests, "post", fake_post)
    with pytest.raises(api.TranslateError):
        api.translate_text("http://x/v1", "m", "p", 1024)
    assert count["n"] == api.RETRY_TIMES + 1

def test_translate_text_error_preserves_cause(monkeypatch):
    # 重试耗尽抛出的 TranslateError 应保留原始异常链,便于排查根因
    def fake_post(url, json, timeout, stream, headers=None):
        raise requests.ConnectionError("网络错误")

    monkeypatch.setattr(api.requests, "post", fake_post)
    with pytest.raises(api.TranslateError) as e:
        api.translate_text("http://x/v1", "m", "p", 1024)
    assert e.value.__cause__ is not None


def test_translate_text_recovers_on_second_try(monkeypatch):
    count = {"n": 0}

    def fake_post(url, json, timeout, stream, headers=None):
        count["n"] += 1
        if count["n"] == 1:
            raise requests.ConnectionError("网络错误")
        return _FakeResponse([_sse("好"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    assert api.translate_text("http://x/v1", "m", "p", 1024) == "好"


def test_translate_text_strips_think(monkeypatch):
    def fake_post(url, json, timeout, stream, headers=None):
        return _FakeResponse([_sse("<think>思考</think>译文"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    assert api.translate_text("http://x/v1", "m", "p", 1024) == "译文"


def test_translate_text_empty_result_raises(monkeypatch):
    def fake_post(url, json, timeout, stream, headers=None):
        return _FakeResponse(["data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    with pytest.raises(api.TranslateError):
        api.translate_text("http://x/v1", "m", "p", 1024)


def test_translate_text_skips_non_dict_chunk(monkeypatch):
    # 网关可能发送非对象分片(如 data: []),应跳过而不是崩溃
    def fake_post(url, json, timeout, stream, headers=None):
        return _FakeResponse(["data: []", _sse("好"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    assert api.translate_text("http://x/v1", "m", "p", 1024) == "好"
