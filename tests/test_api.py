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


def test_build_prompt_context_adds_isolation_constraint():
    # 携带上下文时追加硬约束:输出不得包含上下文参考的任何内容
    prompt = api.build_prompt("x", [], context="前文参考")
    assert "【硬性要求】输出仅包含【源文】的译文,不得翻译或输出【上下文参考】中的任何内容。" in prompt


def test_build_prompt_without_context_has_no_isolation_constraint():
    # 无上下文时约束行数与现状一致,不出现隔离约束
    prompt = api.build_prompt("x", [], "")
    assert "不得翻译或输出【上下文参考】" not in prompt


def test_build_prompt_sparse_constraints():
    # 稀疏化实验:约束并条,不再逐项点名加黑与链接标记
    prompt = api.build_prompt("x", [], "")
    assert "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。" in prompt
    assert "不得翻译或修改 @@@...@@@ 占位符。" in prompt
    assert "表格保持行数与列数,分隔行保持。" in prompt
    assert "加黑标记必须成对出现" not in prompt
    assert "只翻译显示文本" not in prompt


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


class _FakeStatusResponse(_FakeResponse):
    """raise_for_status 抛指定状态码的 HTTPError(模拟网关 4xx/5xx)。"""

    def __init__(self, status_code):
        super().__init__([])
        self._status = status_code

    def raise_for_status(self):
        resp = requests.Response()
        resp.status_code = self._status
        raise requests.HTTPError(f"{self._status} Error", response=resp)


@pytest.fixture(autouse=True)
def sleep_calls(monkeypatch):
    """重试退避不真等:记录 sleep 秒数供断言,避免拖慢测试套件。

    刻意不加 raising=False:api.sleep 一旦被重命名,这里必须立刻报错。
    否则打桩静默失效、测试开始真的等待,套件从 3 秒变成几十秒且无任何提示。
    """
    calls = []
    monkeypatch.setattr(api, "sleep", calls.append)
    return calls


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


def test_retry_backs_off_between_attempts(monkeypatch, sleep_calls):
    # 瞬时 412(网关抖动/限流)需退避后再试:此前循环内无 sleep,3 次尝试在
    # 数十毫秒内打光,故障窗口未消退即全部失败(用户实测稍后手动重试即成功)
    count = {"n": 0}

    def fake_post(url, json, timeout, stream, headers=None):
        count["n"] += 1
        if count["n"] < 3:
            return _FakeStatusResponse(412)
        return _FakeResponse([_sse("译文"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    assert api.translate_text("http://x/v1", "m", "p", 1024) == "译文"
    assert count["n"] == 3
    assert sleep_calls == [api.RETRY_BACKOFF, api.RETRY_BACKOFF * 2]  # 指数退避


@pytest.mark.parametrize("status", [408, 412, 429, 500, 502, 503])
def test_retryable_status_exhausts_retries(monkeypatch, sleep_calls, status):
    # 可重试状态码:退避重试至上限后才抛错。
    # 状态码列表刻意写成字面量、不从 api.RETRYABLE_STATUS 派生——若从常量派生,
    # 常量被改坏时参数列表会跟着缩小,测试永远发现不了(实测:删掉 429 后本用例
    # 从 5 个降到 4 个、全绿)。改常量必须同时改这里,这正是想要的摩擦。
    count = {"n": 0}

    def fake_post(url, json, timeout, stream, headers=None):
        count["n"] += 1
        return _FakeStatusResponse(status)

    monkeypatch.setattr(api.requests, "post", fake_post)
    with pytest.raises(api.TranslateError):
        api.translate_text("http://x/v1", "m", "p", 1024)
    assert count["n"] == api.RETRY_TIMES + 1
    assert len(sleep_calls) == api.RETRY_TIMES  # 最后一次失败后不再等待


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_permanent_4xx_fails_fast(monkeypatch, sleep_calls, status):
    # 非可重试 4xx 源于请求本身(参数非法/鉴权/不存在),重试不会变好:
    # 立即失败,否则退避会把必然失败的请求拖得更慢
    count = {"n": 0}

    def fake_post(url, json, timeout, stream, headers=None):
        count["n"] += 1
        return _FakeStatusResponse(status)

    monkeypatch.setattr(api.requests, "post", fake_post)
    with pytest.raises(api.TranslateError):
        api.translate_text("http://x/v1", "m", "p", 1024)
    assert count["n"] == 1
    assert sleep_calls == []


def test_translate_text_surfaces_gateway_error(monkeypatch):
    # 网关对参数错误(如 max_tokens 超限)返回 HTTP 200 + error 分片:
    # 曾因无 choices 被静默跳过 → 误报「API 返回空结果」,掩盖 invalid_request 真因
    err_line = "data: " + json.dumps(
        {"error": {"message": "请求参数格式错误", "type": "invalid_request"}})

    def fake_post(url, json, timeout, stream, headers=None):
        return _FakeResponse([err_line])

    monkeypatch.setattr(api.requests, "post", fake_post)
    with pytest.raises(api.TranslateError) as exc:
        api.translate_text("http://x/v1", "m", "p", 38106)
    assert "请求参数格式错误" in str(exc.value)

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


def test_translate_text_ollama_omits_bilibili_specifics(monkeypatch):
    # ollama 分支:payload 不带 chat_template_kwargs,不发送特殊 User-Agent
    calls = {}

    def fake_post(url, json, timeout, stream, headers=None):
        calls["payload"] = json
        calls["headers"] = headers
        return _FakeResponse([_sse("你"), _sse("好"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    result = api.translate_text("http://localhost:11434/v1",
                                "index-translate-9b:latest", "提示词", 1024,
                                ollama=True)
    assert result == "你好"
    assert "chat_template_kwargs" not in calls["payload"]
    assert calls["payload"]["stream"] is True
    assert calls["headers"] == {}


def test_translate_text_ollama_retries_and_strips_think(monkeypatch):
    # ollama 分支沿用重试与 </think> 剥离:首次连接失败,第二次成功并剥离
    count = {"n": 0}

    def fake_post(url, json, timeout, stream, headers=None):
        count["n"] += 1
        if count["n"] == 1:
            raise requests.ConnectionError("连接被拒绝")
        return _FakeResponse([_sse("<think>思考</think>译文"), "data: [DONE]"])

    monkeypatch.setattr(api.requests, "post", fake_post)
    assert api.translate_text("http://localhost:11434/v1", "m", "p", 1024,
                              ollama=True) == "译文"
    assert count["n"] == 2


def test_build_prompt_custom_constraints():
    # 显式 constraints 替换默认 md 约束(html/txt 分派路径)
    prompt = api.build_prompt("x", [], "", constraints=["只输出纯文本译文。", "不得翻译占位符。"])
    assert "只输出纯文本译文。" in prompt
    assert "严格保留 markdown 语法结构" not in prompt


def test_build_prompt_default_is_md_constraints():
    # 缺省回落 markdown.CONSTRAINTS(等价断言,防 api 副本漂移——Task 1 审查 Important 流转)
    from md2zh import markdown
    prompt = api.build_prompt("x", [], "")
    assert all(c in prompt for c in markdown.CONSTRAINTS)
    assert "只输出纯文本译文" not in prompt  # html/txt 约束不得混入默认路径
    assert "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。" in prompt
    assert "表格保持行数与列数,分隔行保持。" in prompt
