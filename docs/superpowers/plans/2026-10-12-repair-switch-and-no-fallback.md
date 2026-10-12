# 修复重译开关与不回退语义 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复重译改为参数开关 `--repair N`(默认 0,可开 1-2),校验失败永不回退原文、一律采用译文(警告提示)。

**Architecture:** `_repair` 返回值由 `tuple[bool, str]` 改为 `str`(始终返回最后一次译文),新增 `retries` 参数;`repair` 穿透 `translate_file`/`run_single`/`run_batch`/`run_stdin`/`_translate_document`/`_translate_chunk`/`_translate_long`;cli.py 新增 `--repair`(type=int, choices=range(3), default=0,非法值经既有 argparse 错误路径退出 64)。三重校验、占位符管线、退出码契约、frontmatter 路径零改动。

**Tech Stack:** Python ≥ 3.10、pytest(API 全 mock)。

## Global Constraints

- 版本号按语义化版本提升至 **0.3.0**(minor);五处同步(`src/md2zh/__init__.py`、`pyproject.toml`、`tests/test_version.py`、README 徽章、CLAUDE.md Overview)。
- 警告契约(逐字,前缀契约 v0.2.1 保留):
  - repair=0 失败:`md2zh: 警告: {前缀}块校验失败,采用译文: {问题}`
  - repair>0 中间失败:`md2zh: 警告: {前缀}块校验失败,重译(x/N): {问题}`
  - repair>0 耗尽:`md2zh: 警告: {前缀}块重译耗尽,采用译文: {问题}`
  - 「块重译耗尽,保留原文」永久移除。
- `_repair` 新签名:`(make_prompt, check, *, api_base, model, max_tokens, label, source="", retries=0) -> str`;循环 `range(retries + 1)`,守卫 `attempt < retries`,无越界。
- 穿透签名(全部 keyword-only 追加,默认 0):`translate_file(src_path, *, force, glossary, api_base, model, repair: int = 0)`、`run_single(path, *, force, glossary, api_base, model, repair: int = 0)`、`run_batch(paths, *, force, glossary, api_base, model, repair: int = 0, ignore_matcher=None)`、`run_stdin(*, glossary, api_base, model, repair: int = 0)`、`_translate_document(text, glossary, api_base, model, *, source="", repair=0)`、`_translate_long(text, glossary, api_base, model, *, mapping, source="", repair=0)`、`_translate_chunk(src, glossary, api_base, model, max_tokens, context="", *, source="", repair=0)`。
- 三重校验(链接/表格/占位符)函数、占位符管线、退出码契约(64 复用)、流约定、换行保真、frontmatter 路径(v0.2.5)均不变;不修改 `references/call_api.py`。
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → GREEN → 提交;每任务独立提交;提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾。
- 测试数演进:**124 → 126 → 129**;全部任务完成后 129 项全绿。
- 源码 `src/`、测试 `tests/`;代码注释与用户可见输出一律中文。
- **发布前置(控制方执行)**:真实 API 跑 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md" --force`(默认 repair=0):无「保留原文」类警告、加黑类警告 0;若出现「采用译文」警告,抽查 `*_zh.md` 对应块确为中译文。`SKILL.md` --force 回归 0 警告。观察项(不设硬验收):同文件 `--repair 2` 对照跑,记录重译是否收敛。不达则裁决。
- anaconda 的 PytestDeprecationWarning 是既有环境噪音,忽略。

---

### Task 1: 核心循环不回退与 repair 穿透

**Files:**
- Modify: `src/md2zh/translator.py`(`_repair`、`_translate_chunk` 整体替换;`translate_file`/`run_single`/`run_batch`/`run_stdin`/`_translate_document`/`_translate_long` 加 `repair` 参数与透传)
- Test: `tests/test_translator.py`(新增 2 项、改写 8 项)

**Interfaces:**
- Consumes: 无(全局约束的签名列表)。
- Produces: `_repair(..., retries=0) -> str`;`_translate_chunk(..., repair=0)` 不再回退;公共入口全部带 `repair`。终态测试数 126。

- [ ] **Step 1: 写失败测试**

`tests/test_translator.py` 末尾追加 2 项:

```python
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
```

`tests/test_translator.py` 改写以下 8 项(逐项整体替换):

`test_chunk_repair_exhausted_falls_back` →:

```python
def test_chunk_repair_exhausted_accepts_translation(monkeypatch, capsys):
    # 始终丢失链接:3 次尝试(1 次初译 + 2 次重译)后采用最后一次译文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, repair=2)
    assert result == "依然坏"
```

`test_chunk_repair_warning_names_source` →:

```python
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
```

`test_chunk_repair_warning_without_source_keeps_format` →:

```python
def test_chunk_repair_warning_without_source_keeps_format(monkeypatch, capsys):
    # 内部直接调用不带 source 时警告格式与现状一致,不出现空前缀
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096, repair=2)
    err = capsys.readouterr().err
    assert "md2zh: 警告: 块重译耗尽,采用译文" in err
    assert "警告: :" not in err
```

`test_long_warning_names_source` →:

```python
def test_long_warning_names_source(monkeypatch, capsys):
    # 超长文本分段路径的块级警告同样携带 source,耗尽后采用译文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "[a](https://x) " + "正文" * 2000  # 单段超 3000 字符,按不可分割块整段处理
    result = translator._translate_long(text, [], "http://x", "m", mapping={},
                                        source="docs/a.md", repair=2)
    assert result == "依然坏"
    assert "md2zh: 警告: docs/a.md: 块重译耗尽,采用译文" in capsys.readouterr().err
```

`test_translate_file_warning_names_path` →:

```python
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
```

`test_run_stdin_warning_names_stdin` →:

```python
def test_run_stdin_warning_names_stdin(monkeypatch, capsys):
    # stdin 模式:块级警告用 <stdin> 标识,stdout 为最后一次译文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(sys, "stdin", _FakeStdin("[a](https://x)".encode("utf-8")))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m", repair=2) == translator.EX_OK
    cap = capsys.readouterr()
    assert cap.out == "依然坏\n"
    assert "md2zh: 警告: <stdin>: 块重译耗尽,采用译文" in cap.err
```

`test_chunk_repair_warning_retry_counter_bounded` →(仅改调用与末行断言):

```python
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
```

`test_chunk_repair_then_success` →:

```python
def test_chunk_repair_then_success(monkeypatch):
    # 第一次译文丢失链接,第二次修复(repair=1)
    outputs = iter(["没有链接的译文", "[译文](https://x)"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[text](https://x)", [], "http://x", "m", 4096, repair=1)
    assert result == "[译文](https://x)"
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py::test_chunk_default_no_repair_accepts_translation tests/test_translator.py::test_chunk_repair_one_attempts_twice -v`
Expected: 2 项 FAIL(旧实现:默认仍重译 2 次——`calls == 1` 与 `"重译" not in err` 断言失败、结果回退原文;repair 为未知关键字参数 → TypeError)

- [ ] **Step 3: 最小实现**

`src/md2zh/translator.py` 六处修改:

1. `_repair` 整体替换为:

```python
def _repair(make_prompt, check, *, api_base: str, model: str,
            max_tokens: int, label: str, source: str = "", retries: int = 0) -> str:
    """校验驱动的可选重译:失败打印警告,始终返回最后一次译文。

    retries 为校验失败后的重译次数(0 表示不重译);校验只决定是否重试,
    不回退原文——损坏块以译文形态写出,由警告提示(信任模型取舍)。
    """
    prefix = f"{source}: " if source else ""
    problems: list[str] = []
    dst = ""
    for attempt in range(retries + 1):
        dst = api.translate_text(api_base, model, make_prompt(";".join(problems)), max_tokens)
        problems = check(dst)
        if not problems:
            return dst
        if attempt < retries:
            sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{retries}): {';'.join(problems)}\n")
    if retries:
        sys.stderr.write(f"md2zh: 警告: {prefix}{label}重译耗尽,采用译文: {';'.join(problems)}\n")
    else:
        sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,采用译文: {';'.join(problems)}\n")
    return dst
```

2. `_translate_chunk` 整体替换为:

```python
def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "", *, source: str = "",
                     repair: int = 0) -> str:
    """翻译一段文本:校验失败按 repair 可选重译,始终采用译文。"""
    dst = _repair(
        make_prompt=lambda fix: api.build_prompt(src, glossary, fix_notes=fix, context=context),
        check=lambda d: _check_block(src, d),
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
        source=source, retries=repair,
    )
    # 译文经 API strip,回挂源块尾随空白,保持分段边界与文件末尾布局
    return dst + _trailing_whitespace(src)
```

3. `translate_file` 签名与 `_translate_document` 调用:

```python
def translate_file(src_path: str, *, force: bool, glossary: list[str],
                   api_base: str, model: str, repair: int = 0) -> TranslateResult:
```

```python
        translated = _translate_document(text, glossary, api_base, model,
                                         source=src_path, repair=repair)
```

4. `_translate_document` 签名与两处转发:

```python
def _translate_document(text: str, glossary: list[str], api_base: str, model: str,
                        *, source: str = "", repair: int = 0) -> str:
```

```python
        body = _translate_chunk(protected, glossary, api_base, model, MAX_TOKENS_SINGLE,
                                source=source, repair=repair)
```

```python
        body = _translate_long(protected, glossary, api_base, model,
                               mapping=mapping, source=source, repair=repair)
```

5. `_translate_long` 签名与段内转发:

```python
def _translate_long(text: str, glossary: list[str], api_base: str, model: str,
                    *, mapping: dict[str, str], source: str = "",
                    repair: int = 0) -> str:
```

```python
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context, source=source,
                                      repair=repair)
```

6. `run_single` / `run_batch` / `run_stdin` 签名与透传:

```python
def run_single(path: str, *, force: bool, glossary: list[str],
               api_base: str, model: str, repair: int = 0) -> int:
```

```python
    result = translate_file(path, force=force, glossary=glossary,
                            api_base=api_base, model=model, repair=repair)
```

```python
def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str, repair: int = 0,
              ignore_matcher: ignore.IgnoreMatcher | None = None) -> int:
```

```python
        result = translate_file(p, force=force, glossary=glossary,
                                api_base=api_base, model=model, repair=repair)
```

```python
def run_stdin(*, glossary: list[str], api_base: str, model: str, repair: int = 0) -> int:
```

```python
        translated = _translate_document(text, glossary, api_base, model,
                                         source="<stdin>", repair=repair)
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_translator.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `126 passed`(124 + 2 新增;改写净 0;公共入口默认 0,test_cli 既有用例不受影响)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: 修复重译参数化,校验失败一律采用译文

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: CLI --repair 开关

**Files:**
- Modify: `src/md2zh/cli.py`(`parse_args` 加 `--repair`、`epilog` 加示例行、`main` 三处透传)、`src/md2zh/translator.py`(删死常量 `REPAIR_RETRIES`,任务 1 遗留,控制方批准扩展)
- Test: `tests/test_cli.py`(+2)、`tests/test_translator.py`(+1)

**Interfaces:**
- Consumes: 任务 1 的 `run_single/run_batch/run_stdin(..., repair)` 签名与 `_repair` 语义。
- Produces: `--repair N`(0-2,默认 0,非法 64);`REPAIR_RETRIES` 常量删除(现无任何引用);终态测试数 129。

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py` 末尾追加:

```python
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
```

`tests/test_translator.py` 末尾追加:

```python
def test_run_stdin_default_no_repair_accepts(monkeypatch, capsys):
    # stdin 模式默认不重译:校验失败采用译文,stdout 为译文
    monkeypatch.setattr(sys, "stdin", _FakeStdin("[a](https://x)".encode("utf-8")))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "坏译文")
    assert translator.run_stdin(glossary=[], api_base="http://x", model="m",
                                repair=0) == translator.EX_OK
    cap = capsys.readouterr()
    assert cap.out == "坏译文\n"
    assert "md2zh: 警告: <stdin>: 块校验失败,采用译文" in cap.err
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_cli.py::test_repair_invalid_exits_usage tests/test_cli.py::test_repair_threads_to_translator tests/test_translator.py::test_run_stdin_default_no_repair_accepts -v`
Expected: 1 项 FAIL(`test_repair_threads_to_translator`:旧 CLI 不识别 `--repair` → SystemExit 64 而非 EX_OK)。另 2 项先行通过:`test_repair_invalid_exits_usage` 为钉桩项(旧实现因「无法识别 --repair」同样退出 64);`test_run_stdin_default_no_repair_accepts` 因修订 1(任务 1 已给 run_stdin 默认 0)在 RED 阶段即通过。

- [ ] **Step 3: 最小实现**

`src/md2zh/cli.py`:

1. `parse_args` 在 `--model` 行之后追加:

```python
    parser.add_argument("--repair", type=int, choices=range(3), default=0,
                        help="校验失败后的重译次数 0-2(默认 0;失败一律采用译文,不回退原文)")
```

2. `epilog` 示例块末行追加一行(在 `cat ABC.md | md2zh -` 行之后):

```python
        "  md2zh ABC.md --repair 2            校验失败后重译至多 2 次(默认不重译)"
```

3. `main` 三处透传:

```python
            return translator.run_stdin(glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        repair=args.repair)
```

```python
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        ignore_matcher=matcher, repair=args.repair)
```

```python
        return translator.run_single(args.file, force=args.force, glossary=glossary,
                                     api_base=args.api_base, model=args.model,
                                     repair=args.repair)
```

4. `src/md2zh/translator.py` 删除死常量(先 `grep -rn "REPAIR_RETRIES" src/ tests/` 确认零引用后删整行):

```python
REPAIR_RETRIES = 2
```

(任务 1 起该常量已无引用,控制方批准并入本任务清理,不留死代码。)

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_cli.py tests/test_translator.py::test_run_stdin_default_no_repair_accepts -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `129 passed`

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/cli.py src/md2zh/translator.py tests/test_cli.py tests/test_translator.py
git commit -m "feat: 新增 --repair 重译开关(默认关闭)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 版本 0.3.0 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`、`tests/test_version.py`、`pyproject.toml`、`README.md`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: 任务 1/2 完成后的测试终态 129 项;版本号 0.3.0。
- Produces: 全仓库版本/文档与 0.3.0 一致,测试 129/129 全绿。

- [ ] **Step 1: 更新版本断言并确认 RED**

`tests/test_version.py` 改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.3.0"
```

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL,`AssertionError: assert '0.2.5' == '0.3.0'`

- [ ] **Step 2: 版本号三处同步并确认 GREEN**

- `src/md2zh/__init__.py`:`__version__ = "0.2.5"` → `__version__ = "0.3.0"`
- `pyproject.toml`:`version = "0.2.5"` → `version = "0.3.0"`

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 3: README 徽章、测试数、特性行与 CLI 块**

`README.md` 七处替换(按文本匹配,不得改动其他内容):

- 第 6 行:`![Version](https://img.shields.io/badge/version-0.2.5-brightgreen)` → `version-0.3.0`
- 第 7 行:`![Tests](https://img.shields.io/badge/tests-124%20passed-brightgreen)` → `tests-129%20passed`
- 第 31 行:`- 🔁 **自动修复循环**:块级校验失败时携带具体错误说明自动重译(≤2 次),仍失败则该块回退保留原文(格式天然正确),全程无需人工干预` → `- 🔁 **校验与可选修复**:块级校验失败时打印警告并采用译文(不回退原文);可选 \`--repair N\`(0-2,默认 0)自动重译,全程无需人工干预`
- CLI 代码块:`--force           覆盖已存在的 *_zh.md(默认跳过)` 行之后追加一行(与相邻行对齐):`--repair N        校验失败后的重译次数 0-2(默认 0;失败一律采用译文)`
- 第 136 行:`# 运行全部测试(124 项,API 已 mock,不依赖网络)` → `129 项`
- 第 158 行:`├── tests/              # 124 项测试,API 全 mock` → `129 项测试`
- 第 167 行:`- frontmatter 识别与表格分块采用启发式:frontmatter 不校验、译文直接采用;表格等边界场景由校验+回退原文兜底,格式正确性优先;` → `- frontmatter 识别与表格分块采用启发式:frontmatter 不校验、译文直接采用;校验失败一律采用译文并警告(不回退原文),格式正确性优先;`

(若行号偏移,按文本匹配替换。)

**修订 4 扩展(控制方批准,实现者披露)**:以下四行为简报外、但新语义下将成事实错误的旧描述,按最小子串替换同步(其余标点/上下文不动):

- README:78 `校验失败自动重译修复,重试耗尽后该块保留原文并输出警告(文件仍算成功生成);` → `校验失败输出警告并采用译文,可用 --repair N 开启重译(文件仍算成功生成);`
- README:87 `0 | 成功(含全部跳过/忽略、含"回退保留原文"的文件)` → `0 | 成功(含全部跳过/忽略、含"校验失败采用译文"的文件)`
- README:168 `校验失败兜底意味着极端情况下个别块可能保留英文原文,stderr 会给出明确警告;` → `校验失败采用译文意味着极端情况下个别损坏块以译文写出,stderr 会给出明确警告;`
- CLAUDE.md:73 `0 成功(含全部跳过/忽略/回退原文)` → `0 成功(含全部跳过/忽略/校验失败采用译文)`

- [ ] **Step 4: CHANGELOG 新增 0.3.0 小节**

在 `## [0.2.5] - 2026-10-12` 之前插入(最新在前):

```markdown
## [0.3.0] - 2026-10-12

### 新增

- `--repair N` 修复重译开关:校验失败后的重译次数 0-2,默认 0(关闭)

### 变更

- 校验失败不再回退原文:一律采用最后一次译文并打印警告(取舍:损坏块如丢链接/占位符将以译文形态写出,警告为唯一提示;实证修复重译对链接类失败无收敛)
```

链接区两处更新:

- `[Unreleased]: https://github.com/wzlu/bilibli-translator/compare/v0.2.5...HEAD` → `.../compare/v0.3.0...HEAD`
- 在其后新增一行:`[0.3.0]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.3.0`

- [ ] **Step 5: CLAUDE.md 同步**

六处替换(既有行内的精确子串):

- Overview:`当前版本 0.2.5。` → `当前版本 0.3.0。`
- 测试行:`python -m pytest -v`(124 项,API 全部 mock,不依赖真实网络) → 把 `124 项` 改为 `129 项`
- 「四重格式保障」条目:`- **四重格式保障**:占位符隔离 + 提示词格式约束 + 块级校验 + 自动修复循环(校验失败带错误说明重译 ≤2 次,仍失败该块回退保留原文)` → `- **四重格式保障**:占位符隔离 + 提示词格式约束 + 块级校验 + 可选自动修复循环(--repair 默认关闭;校验失败一律采用译文并警告,不回退原文)`
- CLI 接口代码块:`  --force           覆盖已存在的 *_zh.md(默认跳过)` 行之后追加一行(与相邻行对齐):`  --repair N        校验失败后的重译次数 0-2(默认 0;失败一律采用译文)`
- Important Notes 已知限制行:`最坏后果为无谓重译或该块回退原文,损害有界` → `最坏后果为无谓重译或该块以损坏译文写出(警告提示),损害有界`
- Recent Updates 顶部新增条目:先运行

```bash
git log --format=%h -1
git rev-list --count 0e8aa87..HEAD
```

把得到的 `<尾哈希>` 与 `<提交数>` 填入条目(格式与 v0.2.5 条目一致):

```markdown
v0.3.0 修复重译开关与不回退语义:0e8aa87..<尾哈希> 共 <提交数> 个提交(计划 + 任务 1-2 实施),本提交为文档同步;129/129 测试通过。--repair N 开关(默认 0);校验失败一律采用译文,不再回退原文。真实 API 复验结果:见发布说明。
```

- [ ] **Step 6: 全量回归并提交**

Run: `python -m pytest -v`
Expected: `129 passed`

```bash
git add src/md2zh/__init__.py tests/test_version.py pyproject.toml README.md CHANGELOG.md CLAUDE.md
git commit -m "docs: 版本 0.3.0 与变更日志(重译开关与不回退语义)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 发布前真实 API 复验(控制方执行,非子代理任务)

任务 1-3 全部完成并审查通过后,控制方执行:

1. 运行 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md" --force`(默认 repair=0):统计 stderr——不得出现「保留原文」类警告;加黑类警告 0;若出现「采用译文」警告,抽查 `opensre_system_prompt_zh.md` 对应块确为中译文(不再夹英文块);
2. 运行 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\skills\analyzing-local-repositories\SKILL.md" --force`:0 警告(回归);
3. 观察项(不设硬验收):`md2zh.exe "...\opensre_system_prompt.md" --force --repair 2` 对照,记录重译是否收敛,结论记入发布说明;
4. 判定:无「保留原文」、加黑 0、SKILL.md 0 警告 → 通过,进入发布;不达 → 裁决(回退对应改动或接受并如实记录);
5. 复验结果回填 CLAUDE.md 条目「真实 API 复验结果」并记入 `.superpowers/sdd/progress.md`。

---

## 自审结论

- **规格覆盖**:§2 需求 1(--repair CLI)→ 任务 2;需求 2(永不回退/警告)→ 任务 1;需求 3(三重校验等不变)→ 全局约束与任务 1 范围;需求 4(穿透)→ 任务 1;需求 5(计数器)→ 任务 1 Step 3 守卫;§5 测试表 → 任务 1/2(新增 2+3 项、改写 8 项);§5 真实 API 复验 → 「发布前真实 API 复验」小节(验收阈值逐字一致);§6 文档 → 任务 3。
- **占位符扫描**:无 TBD/「类似任务 N」;所有代码步骤给出完整代码;CLAUDE.md 提交范围哈希由确切命令运行时取值。
- **类型一致性**:测试数演进 124 → 126 → 129 与各任务回归预期吻合;穿透签名与全局约束逐字一致(公共入口默认 0,既有测试零改动);警告契约三行文本与规格 §4.4 逐字一致;`_repair` 返回值/循环/守卫与规格 §4.1 逐字一致。

## 计划修订记录

- **修订 1(任务 1 执行中发现,实现者披露 + 控制方裁决)**:初版计划把四个公共入口的 `repair` 写成必填参数,与规格 §4.2「默认 0」及「既有其余测试零改动」矛盾(28 处既有直接调用会 TypeError)。裁决:四个公共入口一律 keyword-only `repair: int = 0`;随之删除任务 1 Step 5 的「排除 test_cli 中间态」注记(不再出现)。规格为权威依据,无需修订规格。
- **修订 2(任务 1 完成后,实现者披露 + 控制方批准)**:`REPAIR_RETRIES = 2` 常量自任务 1 起无引用(死常量)。并入任务 2 一并删除(不留死代码,项目纪律)。
- **修订 3(任务 2 执行中发现,实现者披露 + 控制方确认)**:任务 2 Step 2 的 RED 预期原为「2 FAIL」,实际 1 FAIL——`test_run_stdin_default_no_repair_accepts` 因修订 1 已在 RED 阶段通过(测试按简报逐字保留,终态覆盖仍有效)。Step 2 预期文本已同步。
- **修订 4(任务 3 执行中发现,实现者披露 + 控制方批准)**:README:78/87/168 与 CLAUDE.md:73 四行仍描述旧「回退原文」语义,新语义下为事实错误;批准按最小子串替换同步(目标文本已并入任务 3 Step 3/5)。
