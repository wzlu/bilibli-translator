# --ollama 本地翻译后端 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 md2zh 新增 `--ollama` 选项:使用本地 ollama OpenAI 兼容端点(`http://localhost:11434/v1`)与模型 `index-translate-9b:latest` 离线翻译,强制单线程,版本升至 0.5.0。

**Architecture:** 布尔标志贯穿——`api.translate_text` 增 `ollama: bool = False`(为真时省略 B 站特有 `chat_template_kwargs`、不发送特殊 UA),标志沿 translator 调用链逐层透传(默认 False,存量调用零迁移);CLI 层用 `None` 哨兵默认值检测显式传参并做冲突报错(退出 64),`--ollama` 时线程数锁定 1。

**Tech Stack:** Python ≥ 3.10(仅标准库 + requests)、pytest、argparse。

## Global Constraints

- 规格:`docs/superpowers/specs/2026-10-13-ollama-local-backend-design.md`(已获批)
- 运行期依赖仅 `requests`;`references/call_api.py` 不得修改
- 目录规则:源码 `src/`、测试 `tests/`、临时文件 `temp/`、报告 `reports/`
- 代码注释与用户可见输出一律中文
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → 确认 GREEN → 提交
- 测试命令:`python -m pytest -v`;报告:`python -m pytest -v --junitxml=reports/junit.xml`
- 真实 API 不进自动化测试(全部 mock)
- 提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- 退出码契约:64 用法错误;其余(65/66/74/75/130/141)不变
- **规格偏差说明(已核实的机械性改动):** 规格 §2.7「存量 148 项零改动」按「不改变既有测试的行为语义」执行——以下 9 处**严格签名的测试替身**必须追加新关键字形参(否则 TypeError),属签名机械扩展,断言全部不变:
  - `tests/test_translator.py:58`、`:248`(`def fake(api_base, model, prompt, max_tokens)` → 加 `ollama=False`)
  - `tests/test_translator.py:609`、`:639`、`:669`、`:685`、`:733`、`:870`(`def fake(src_path, *, force, glossary, api_base, model, repair)` → 加 `ollama=False`)
  - `tests/test_cli.py:209`(`fake_run_batch` → 加 `ollama=False`)

## 文件结构

- **Modify `src/md2zh/api.py`**:新增 `OLLAMA_API_BASE`/`OLLAMA_MODEL` 常量;`translate_text` 增 `ollama` 形参与 payload/headers 分支
- **Modify `src/md2zh/translator.py`**:9 个函数签名追加 `ollama: bool = False` 并逐层透传(线程池逻辑不改)
- **Modify `src/md2zh/cli.py`**:`--ollama` 选项、哨兵默认值、冲突检测、缺省解析、main 三分支透传
- **Modify `src/md2zh/__init__.py`**:版本 0.5.0
- **Test `tests/test_api.py`、`tests/test_translator.py`、`tests/test_cli.py`、`tests/test_version.py`**
- **Docs `README.md`、`CHANGELOG.md`、`CLAUDE.md`**:v0.5.0 同步

---

### Task 1: api.py——ollama 请求分支与常量

**Files:**
- Modify: `src/md2zh/api.py:9-10`(常量区)、`src/md2zh/api.py:108-163`(`translate_text`)
- Test: `tests/test_api.py`(文件末尾追加)

**Interfaces:**
- Consumes: 无(首个任务)
- Produces:`api.OLLAMA_API_BASE = "http://localhost:11434/v1"`、`api.OLLAMA_MODEL = "index-translate-9b:latest"`、`translate_text(api_base, model, prompt, max_tokens, ollama: bool = False) -> str`(Task 2/3 依赖)

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 末尾追加:

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api.py::test_translate_text_ollama_omits_bilibili_specifics tests/test_api.py::test_translate_text_ollama_retries_and_strips_think -v`
Expected: FAIL,`TypeError: translate_text() got an unexpected keyword argument 'ollama'`

- [ ] **Step 3: 最小实现**

在 `src/md2zh/api.py` 常量区(`DEFAULT_MODEL` 之后)加:

```python
OLLAMA_API_BASE = "http://localhost:11434/v1"
OLLAMA_MODEL = "index-translate-9b:latest"
```

`translate_text` 整体替换为:

```python
def translate_text(api_base: str, model: str, prompt: str, max_tokens: int,
                   ollama: bool = False) -> str:
    """流式调用 chat/completions,失败自动重试,重试耗尽抛 TranslateError。

    采用流式请求规避非流式长文本的网关 504 超时(见 references/call_api.py)。
    ollama=True 走本地 OpenAI 兼容端点:省略 B 站特有的 chat_template_kwargs,
    网关 412 的 User-Agent 要求不适用。
    """
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if not ollama:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    # B 站网关要求非默认 User-Agent,否则返回 412(见 references/call_api.py);
    # 本地 ollama 无此要求,空 dict 让 requests 使用默认 UA
    headers = {"User-Agent": "Index-Translate-Client/1.0"} if not ollama else {}
    last_error: Exception | None = None
    for _ in range(RETRY_TIMES + 1):
        try:
            with requests.post(url, json=payload, headers=headers,
                               timeout=REQUEST_TIMEOUT, stream=True) as resp:
                resp.raise_for_status()
                parts = []
                for raw in resp.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    body = line[6:]
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                    except json.JSONDecodeError:
                        continue
                    # 网关可能发送非对象分片,跳过而不是崩溃(见 references/call_api.py)
                    if not isinstance(chunk, dict):
                        continue
                    choices = chunk.get("choices") or []
                    if not choices or not isinstance(choices[0], dict):
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        parts.append(content)
                text = "".join(parts)
                if "</think>" in text:
                    text = text.split("</think>", 1)[1]
                if not text.strip():
                    raise TranslateError("API 返回空结果")
                return text.strip()
        except (requests.RequestException, TranslateError) as e:
            last_error = e
    # from 保留原始异常链,便于排查根因
    raise TranslateError(str(last_error)) from last_error
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS(全部 test_api,含存量 20 项——存量用例不传 ollama 走默认 False,payload 不变)

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/api.py tests/test_api.py
git commit -m "feat: api 层 ollama 请求分支(B 站特有参数按标志省略)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: translator.py——ollama 标志贯穿调用链

**Files:**
- Modify: `src/md2zh/translator.py`(9 个函数)
- Test: `tests/test_translator.py`(末尾追加 3 个新测试;8 处严格签名替身机械扩展)

**Interfaces:**
- Consumes: Task 1 的 `api.OLLAMA_API_BASE`/`OLLAMA_MODEL`(本任务不直接用)、`api.translate_text(..., ollama=...)`
- Produces:`translate_file(..., repair=0, ollama=False)`、`run_single(..., repair=0, ollama=False)`、`run_batch(..., max_threads=10, ollama=False)`、`run_stdin(*, ..., repair=0, ollama=False)`(Task 3 依赖)

- [ ] **Step 1: 写失败测试**

在 `tests/test_translator.py` 末尾追加:

```python
def test_ollama_threads_to_translate_text(monkeypatch, tmp_path):
    # ollama=True 沿 translate_file 全链路透传到 api.translate_text;缺省为 False
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    calls = []

    def fake(api_base, model, prompt, max_tokens, ollama=False):
        calls.append((api_base, model, ollama))
        return "# 你好"

    monkeypatch.setattr(api, "translate_text", fake)
    r1 = translator.translate_file(str(src), force=False, glossary=[],
                                   api_base="http://x", model="m", ollama=True)
    assert r1.status == "ok"
    assert calls[-1][2] is True
    r2 = translator.translate_file(str(src), force=True, glossary=[],
                                   api_base="http://x", model="m")
    assert r2.status == "ok"
    assert calls[-1][2] is False


def test_run_stdin_ollama_threads(monkeypatch, capsys):
    # stdin 模式透传 ollama 到 api.translate_text
    calls = []
    monkeypatch.setattr(sys, "stdin", _FakeStdin("# Hi".encode("utf-8")))

    def fake(api_base, model, prompt, max_tokens, ollama=False):
        calls.append(ollama)
        return "# 你好"

    monkeypatch.setattr(api, "translate_text", fake)
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m",
                                ollama=True) == translator.EX_OK
    assert calls == [True]
    assert capsys.readouterr().out == "# 你好\n"


def test_run_batch_threads_ollama_to_translate_file(monkeypatch, capsys):
    # run_batch 把 ollama 透传给 translate_file;线程池行为不受标志影响
    calls = []

    def fake(src_path, *, force, glossary, api_base, model, repair, ollama=False):
        calls.append(ollama)
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    assert translator.run_batch(["a.md"], force=False, glossary=[],
                                api_base="http://x", model="m",
                                max_threads=3, ollama=True) == translator.EX_OK
    assert calls == [True]
    assert capsys.readouterr().out == "a.md_zh\n"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_translator.py::test_ollama_threads_to_translate_text tests/test_translator.py::test_run_stdin_ollama_threads tests/test_translator.py::test_run_batch_threads_ollama_to_translate_file -v`
Expected: FAIL,`TypeError: translate_file() got an unexpected keyword argument 'ollama'`

- [ ] **Step 3: 实现透传 + 机械扩展 8 处严格替身**

`src/md2zh/translator.py` 按以下逐个修改(只列变化行,其余不动):

1. `translate_file` 签名与 `_translate_document` 调用:

```python
def translate_file(src_path: str, *, force: bool, glossary: list[str],
                   api_base: str, model: str, repair: int = 0,
                   ollama: bool = False) -> TranslateResult:
```

```python
        translated = _translate_document(text, glossary, api_base, model,
                                         source=src_path, repair=repair,
                                         ollama=ollama)
```

2. `_translate_document`:

```python
def _translate_document(text: str, glossary: list[str], api_base: str, model: str,
                        *, source: str = "", repair: int = 0,
                        ollama: bool = False) -> str:
```

```python
        head = _translate_frontmatter(fm, glossary, api_base, model, ollama=ollama)
```

```python
        body = _translate_chunk(protected, glossary, api_base, model, MAX_TOKENS_SINGLE,
                                source=source, repair=repair, ollama=ollama)
```

```python
        body = _translate_long(protected, glossary, api_base, model,
                               mapping=mapping, source=source, repair=repair,
                               ollama=ollama)
```

3. `_repair` 签名与调用:

```python
def _repair(make_prompt, check, *, api_base: str, model: str,
            max_tokens: int, label: str, source: str = "", retries: int = 0,
            ollama: bool = False) -> str:
```

```python
        dst = api.translate_text(api_base, model, make_prompt(";".join(problems)),
                                 max_tokens, ollama=ollama)
```

4. `_translate_chunk` 签名与 `_repair` 调用:

```python
def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "", *, source: str = "",
                     repair: int = 0, ollama: bool = False) -> str:
```

```python
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
        source=source, retries=repair, ollama=ollama,
```

5. `_translate_long` 签名与 `_translate_chunk` 调用:

```python
def _translate_long(text: str, glossary: list[str], api_base: str, model: str,
                    *, mapping: dict[str, str], source: str = "",
                    repair: int = 0, ollama: bool = False) -> str:
```

```python
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context, source=source,
                                      repair=repair, ollama=ollama)
```

6. `_translate_frontmatter`:

```python
def _translate_frontmatter(fm: str, glossary: list[str], api_base: str, model: str,
                           ollama: bool = False) -> str:
```

```python
    return api.translate_text(api_base, model,
                              api.build_frontmatter_prompt(fm, glossary),
                              MAX_TOKENS_SINGLE, ollama=ollama)
```

7. `run_single`:

```python
def run_single(path: str, *, force: bool, glossary: list[str],
               api_base: str, model: str, repair: int = 0,
               ollama: bool = False) -> int:
```

```python
    result = translate_file(path, force=force, glossary=glossary,
                            api_base=api_base, model=model, repair=repair,
                            ollama=ollama)
```

8. `run_batch` 签名与 submit:

```python
def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str, repair: int = 0,
              ignore_matcher: ignore.IgnoreMatcher | None = None,
              max_threads: int = 10, ollama: bool = False) -> int:
```

```python
        futures = {executor.submit(translate_file, p, force=force, glossary=glossary,
                                   api_base=api_base, model=model, repair=repair,
                                   ollama=ollama): p
                   for p in todo}
```

9. `run_stdin`:

```python
def run_stdin(*, glossary: list[str], api_base: str, model: str, repair: int = 0,
              ollama: bool = False) -> int:
```

```python
        translated = _translate_document(text, glossary, api_base, model,
                                         source="<stdin>", repair=repair,
                                         ollama=ollama)
```

机械扩展 8 处严格替身(仅签名加 `ollama=False`,断言不动):

- `tests/test_translator.py:58` 与 `:248`:`def fake(api_base, model, prompt, max_tokens):` → `def fake(api_base, model, prompt, max_tokens, ollama=False):`
- `tests/test_translator.py:609`、`:639`、`:669`、`:685`、`:733`、`:870`:`def fake(src_path, *, force, glossary, api_base, model, repair):` → 末尾加 `, ollama=False`(替换 6 处,可用 `replace_all`)

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_translator.py tests/test_api.py -v`
Expected: PASS(新增 3 项 + 存量全部;替身扩展仅签名变化)

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: translator 层 ollama 标志贯穿(线程池逻辑不变)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: cli.py——--ollama 解析、冲突检测与缺省解析

**Files:**
- Modify: `src/md2zh/cli.py:21-60`(`parse_args`)、`src/md2zh/cli.py:63-108`(`main` 三处调用)
- Test: `tests/test_cli.py`(末尾追加 6 个新测试;`test_max_threads_passthrough` 替身机械扩展)

**Interfaces:**
- Consumes: Task 1 的 `api.OLLAMA_API_BASE`/`OLLAMA_MODEL`/`DEFAULT_API_BASE`/`DEFAULT_MODEL`;Task 2 的 `run_single/run_batch/run_stdin` 的 `ollama` 形参
- Produces: 解析后的 `args.api_base`/`args.model`/`args.max_threads`(恒定非 None)与 `args.ollama`(Task 4 依赖)

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 末尾追加:

```python
@pytest.mark.parametrize("extra, msg", [
    (["--api-base", "http://x/v1"], "--ollama 与 --api-base 不能同时使用"),
    (["--model", "m"], "--ollama 与 --model 不能同时使用"),
    (["-c", "2"], "--ollama 强制单线程"),
    (["-c", "0"], "--ollama 强制单线程"),
    (["-c", "-1"], "--ollama 强制单线程"),
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli.py::test_ollama_conflicts_exit_64 tests/test_cli.py::test_ollama_resolves_defaults_and_single_thread tests/test_cli.py::test_ollama_single_file_end_to_end tests/test_cli.py::test_help_contains_ollama -v`
Expected: FAIL——`--ollama` 未被识别(`unrecognized arguments` 或断言失败)

- [ ] **Step 3: 实现 parse_args 与 main 透传**

`parse_args` 整体替换为:

```python
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _Parser(
        prog="md2zh",
        description="将英文 Markdown 文件翻译为中文,保存为 *_zh.md(同目录)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,  # 保留 epilog 示例的换行
    )
    parser.add_argument("file", nargs="?", metavar="FILE", help="要翻译的 Markdown 文件")
    parser.add_argument("--filelist", metavar="LIST",
                        help="文件列表(每行一个 md 文件,# 开头的行被忽略)")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的 *_zh.md(默认跳过)")
    parser.add_argument("--glossary", metavar="FILE",
                        help=f"术语表文件(JSON);缺省加载 {api.DEFAULT_GLOSSARY}")
    parser.add_argument("--api-base", default=None,
                        help=f"翻译 API 地址(默认 {api.DEFAULT_API_BASE})")
    parser.add_argument("--model", default=None,
                        help=f"模型(默认 {api.DEFAULT_MODEL})")
    parser.add_argument("--ollama", action="store_true",
                        help="使用本地 ollama 翻译(端点 http://localhost:11434/v1,"
                             "模型 index-translate-9b:latest,强制单线程)")
    parser.add_argument("--repair", type=int, choices=range(3), default=0,
                        help="校验失败后的重译次数 0-2(默认 0;失败一律采用译文,不回退原文)")
    parser.add_argument("-c", "--max-threads", type=int, default=None, metavar="N",
                        help="--filelist 模式最大并发线程数(默认 10;仅批量模式生效)")
    parser.add_argument("--version", action="version", version=f"md2zh {__version__}")
    parser.epilog = (
        "示例:\n"
        "  md2zh ABC.md                      翻译单个文件,生成 ABC_zh.md\n"
        "  md2zh --filelist list.txt         批量翻译(每行一个 md 文件)\n"
        "  md2zh --filelist list.txt -c 5     批量翻译,最多 5 个线程并行(默认 10)\n"
        "  md2zh ABC.md --force              覆盖已存在的译文\n"
        "  md2zh ABC.md --glossary g.json    指定术语表\n"
        "  md2zh ABC.md --ollama             使用本地 ollama 离线翻译(强制单线程)\n"
        "  cat ABC.md | md2zh -              管道过滤器(stdin → stdout)\n"
        "  md2zh ABC.md --repair 2            校验失败后重译至多 2 次(默认不重译)"
    )
    args = parser.parse_args(argv)
    if args.file and args.filelist:
        parser.error("FILE 与 --filelist 不能同时使用")
    if not args.file and not args.filelist:
        parser.error("需要 FILE 或 --filelist 其中之一")
    if args.ollama:
        # --ollama 锁定本地端点与模型:显式后端参数冲突即用法错误
        if args.api_base is not None:
            parser.error("--ollama 与 --api-base 不能同时使用")
        if args.model is not None:
            parser.error("--ollama 与 --model 不能同时使用")
        if args.max_threads is not None and args.max_threads != 1:
            parser.error("--ollama 强制单线程,-c/--max-threads 仅接受 1")
        args.api_base = api.OLLAMA_API_BASE
        args.model = api.OLLAMA_MODEL
        args.max_threads = 1
    else:
        # 哨兵回填:未显式传参时取默认值,显式传参(含 -c 0/-1)走既有校验
        if args.api_base is None:
            args.api_base = api.DEFAULT_API_BASE
        if args.model is None:
            args.model = api.DEFAULT_MODEL
        if args.max_threads is None:
            args.max_threads = 10
        if args.max_threads < 1:
            parser.error("-c/--max-threads 必须是正整数")
    return args
```

`main` 三处调用追加 `ollama=args.ollama`:

```python
            return translator.run_stdin(glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        repair=args.repair, ollama=args.ollama)
```

```python
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        ignore_matcher=matcher, repair=args.repair,
                                        max_threads=args.max_threads,
                                        ollama=args.ollama)
```

```python
        return translator.run_single(args.file, force=args.force, glossary=glossary,
                                     api_base=args.api_base, model=args.model,
                                     repair=args.repair, ollama=args.ollama)
```

机械扩展 `tests/test_cli.py:209`:`def fake_run_batch(paths, *, force, glossary, api_base, model, repair,` 下一行 `ignore_matcher, max_threads):` → `ignore_matcher, max_threads, ollama=False):`

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS(新增 6 项 + 存量全部;`test_max_threads_passthrough`/`test_max_threads_invalid_exits_64` 行为不变)

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/cli.py tests/test_cli.py
git commit -m "feat: cli 层 --ollama 选项与冲突检测(退出 64)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 版本 0.5.0 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py:3`、`tests/test_version.py:4-5`
- Modify: `README.md`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: Task 1-3 全部落地
- Produces: 发布版本 0.5.0(后续任务依赖版本号)

- [ ] **Step 1: 先改版本测试(RED)**

`tests/test_version.py`:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.5.0"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL,`AssertionError: assert '0.4.0' == '0.5.0'`

- [ ] **Step 3: 提升版本(GREEN)**

`src/md2zh/__init__.py`:

```python
"""md2zh:英文 Markdown 翻译 CLI。"""

__version__ = "0.5.0"
```

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 4: 文档同步**

`CHANGELOG.md` 在 `## [0.4.0]` 上方插入:

```markdown
## [0.5.0] - 2026-10-13

### 新增

- `--ollama` 本地翻译后端:使用本地 ollama OpenAI 兼容端点(固定 http://localhost:11434/v1,模型 index-translate-9b:latest)离线翻译;请求省略 B 站特有的 `chat_template_kwargs` 与 User-Agent 要求;强制单线程
- `--ollama` 与显式 `--api-base`/`--model`/`-c N(N>1)` 冲突报错,按用法错误退出 64(`-c 1` 合法)
```

`README.md` 三处同步:

1. 「快速开始」bash 块,在 `--repair 2` 示例(现第 71 行)之后追加:

```bash
# 使用本地 ollama 离线翻译(强制单线程)
md2zh ABC.md --ollama
```

2. 「行为约定」列表末尾(现第 89 行之后)追加:

```markdown
- `--ollama` 使用本地 ollama 翻译(固定 `http://localhost:11434/v1`,模型 `index-translate-9b:latest`,强制单线程;与显式 `--api-base`/`--model`/`-c N(N>1)` 冲突按用法错误退出 64);
```

3. 「翻译 API 说明」节,在开头段(现第 130 行)之后追加:

```markdown
`--ollama` 模式下改用本地 ollama 的 OpenAI 兼容端点(需本机已运行 ollama 且已拉取 `index-translate-9b:latest`):

```
POST http://localhost:11434/v1/chat/completions
```

- 请求省略 B 站特有的 `chat_template_kwargs` 与 User-Agent 要求;
- 强制单线程:本地 9B 模型多线程并发无收益(仅 `--filelist` 模式受影响,单文件/stdin 天然串行)。
```

4. 「开发」节测试数 `148 项` → `159 项`(现第 144 行)。

`CLAUDE.md`:
- CLI 接口清单加一行:`--ollama       使用本地 ollama 翻译(端点 http://localhost:11434/v1,模型 index-translate-9b:latest,强制单线程;与显式 --api-base/--model/-c N>1 冲突报错退出 64)`
- 「核心设计决策」追加:`**本地 ollama 后端**:--ollama 经布尔标志贯穿(cli→translator→api),ollama 分支省略 chat_template_kwargs 与特殊 UA(仅 B 站网关 412 要求);强制单线程在 CLI 层完成(max_threads=1),translator 线程池逻辑不变`
- 标题版本号 0.4.0 → 0.5.0,Recent Updates 增补 v0.5.0 条目(实施与真实 API 复验结果在实施完成后回填)

- [ ] **Step 5: 全量测试与报告**

Run: `python -m pytest -v --junitxml=reports/junit.xml`
Expected: 全部 PASS(148 + 新增 11 = **159** 项;新增明细:api 2、translator 3、cli 6)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/__init__.py tests/test_version.py README.md CHANGELOG.md CLAUDE.md
git commit -m "chore: 版本 0.5.0 与文档同步(--ollama 本地后端)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 实施后:真实 ollama 手工验证(环境已就绪,不阻塞合并)

自动化测试全 mock;以下清单在实施完成后用本机 ollama 执行,结果回填 CHANGELOG/CLAUDE.md:

1. `md2zh data/sample_en.md --ollama` → 生成 `data/sample_en_zh.md`(不入库),译文中文、无 `@@@` 残留、链接/表格完好
2. `cat data/sample_en.md | md2zh - --ollama` → stdout 输出中文译文
3. `md2zh --filelist temp/list.txt --ollama` → 单线程批量,汇总正确(准备含 2-3 个 md 文件的列表放 `temp/`)
4. 冲突实测:`md2zh a.md --ollama --api-base http://x`、`--ollama --model m`、`--ollama -c 5` → 均退出 64 且 stderr 报错清晰
5. 停掉 ollama 服务后运行 `md2zh data/sample_en.md --ollama` → 重试后退出 75,stderr 报连接错误
6. 观察 9B 本地模型生成速度与 120s 超时余量;确认 `</think>` 剥离对本地模型输出无副作用
