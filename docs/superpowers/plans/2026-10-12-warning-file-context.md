# 翻译期警告补文件上下文 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 块级修复警告补文件路径前缀,批量模式下用户可定位问题文件;stdin 模式显示 `<stdin>`。

**Architecture:** 文件路径(或 `<stdin>`)作为 `source` 仅关键字参数(默认 `""`)贯穿 `_translate_document` → `_translate_frontmatter`/`_translate_chunk`/`_translate_long` → `_repair`,`_repair` 组装警告时 `source` 非空才加 `"{source}: "` 前缀。与现有 `context` 参数的贯穿风格一致,无全局状态。

**Tech Stack:** Python ≥ 3.10、pytest、requests(运行期依赖不变)

## Global Constraints

- 规格:`docs/superpowers/specs/2026-10-12-warning-file-context-design.md`(已确认)
- 警告格式:`md2zh: 警告: {source}: {label}校验失败,重译(1/2): ...` / `md2zh: 警告: {source}: {label}重译耗尽,保留原文: ...`;路径为用户传入原样;stdin 模式 `source="<stdin>"`;`source` 为空时不加前缀(兼容内部直接调用)
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → 确认 GREEN → 提交
- 源码 `src/`、测试 `tests/`;注释与用户可见输出一律中文
- 现有 114 项测试全部保持通过;最终全量 120 项
- 退出码契约不变;不新增依赖;不修改 `references/call_api.py`
- 提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- 测试命令:`python -m pytest -v`(Windows,环境含 pytest-asyncio 插件的 PytestDeprecationWarning 可忽略)

## File Structure

- 修改 `src/md2zh/translator.py`:警告输出(`_repair`)与 source 参数贯穿(`_translate_document`/`_translate_frontmatter`/`_translate_chunk`/`_translate_long`/`translate_file`/`run_stdin`)
- 修改 `tests/test_translator.py`:新增 6 项测试
- 修改 `tests/test_version.py`、`src/md2zh/__init__.py`:版本 0.2.1
- 修改 `CHANGELOG.md`、`CLAUDE.md`:发布文档

---

### Task 1: 块级修复警告携带 source

**Files:**
- Modify: `src/md2zh/translator.py`(`_repair` 122-136 行、`_translate_chunk` 139-150 行、`_translate_long` 153-166 行)
- Test: `tests/test_translator.py`(在 `test_chunk_repair_exhausted_falls_back` 函数后追加 3 项测试)

**Interfaces:**
- Produces:`_repair(make_prompt, check, *, api_base, model, max_tokens, label, source: str = "")`;`_translate_chunk(src, glossary, api_base, model, max_tokens, context: str = "", *, source: str = "")`;`_translate_long(text, glossary, api_base, model, *, source: str = "")`。后续任务依赖这些签名。

- [ ] **Step 1: 写失败测试**

在 `tests/test_translator.py` 的 `test_chunk_repair_exhausted_falls_back` 函数之后追加(该文件已导入 `io`/`sys`/`api`/`translator`):

```python
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
    result = translator._translate_long(text, [], "http://x", "m", source="docs/a.md")
    assert result == text
    assert "md2zh: 警告: docs/a.md: 块重译耗尽,保留原文" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m pytest tests/test_translator.py::test_chunk_repair_warning_names_source tests/test_translator.py::test_chunk_repair_warning_without_source_keeps_format tests/test_translator.py::test_long_warning_names_source -v
```

预期:`test_chunk_repair_warning_names_source` 与 `test_long_warning_names_source` FAIL(`TypeError: unexpected keyword argument 'source'`);`test_chunk_repair_warning_without_source_keeps_format` PASS(兼容守卫)。

- [ ] **Step 3: 最小实现**

`src/md2zh/translator.py` 三处修改(用 Edit 精确替换,注意 `_translate_chunk` 与 `_translate_long` 的函数签名行与调用行):

修改 1 — `_repair` 签名与警告行:

```python
def _repair(make_prompt, check, *, api_base: str, model: str,
            max_tokens: int, label: str, source: str = "") -> tuple[bool, str]:
    """通用修复循环:校验失败带错误说明重译,重译耗尽返回 (False, "")。

    make_prompt(fix_notes) 构建带修复说明的提示词;check(dst) 返回问题列表,空列表表示通过。
    source 为来源文件路径(stdin 模式为 "<stdin>"),非空时警告带 "{source}: " 前缀。
    """
    prefix = f"{source}: " if source else ""
    problems: list[str] = []
    for attempt in range(REPAIR_RETRIES + 1):
        dst = api.translate_text(api_base, model, make_prompt(";".join(problems)), max_tokens)
        problems = check(dst)
        if not problems:
            return True, dst
        sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{REPAIR_RETRIES}): {';'.join(problems)}\n")
    sys.stderr.write(f"md2zh: 警告: {prefix}{label}重译耗尽,保留原文: {';'.join(problems)}\n")
    return False, ""
```

修改 2 — `_translate_chunk` 签名加 `*, source: str = ""`,`_repair` 调用加 `source=source,`:

```python
def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "", *, source: str = "") -> str:
    """翻译一段文本:校验失败带错误说明重译,仍失败回退原文。"""
    ok, dst = _repair(
        make_prompt=lambda fix: api.build_prompt(src, glossary, fix_notes=fix, context=context),
        check=lambda d: _check_block(src, d),
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
        source=source,
    )
    if not ok:
        return src
    # 译文经 API strip,回挂源块尾随空白,保持分段边界与文件末尾布局
    return dst + _trailing_whitespace(src)
```

修改 3 — `_translate_long` 签名加 `*, source: str = ""`,`_translate_chunk` 调用加 `source=source`:

```python
def _translate_long(text: str, glossary: list[str], api_base: str, model: str,
                    *, source: str = "") -> str:
    """超长文本:分段翻译,每段附前段上下文参考保证术语延续。"""
    parts: list[str] = []
    prev_context = ""
    half = CONTEXT_TAIL // 2
    for chunk in markdown.chunk_text(text, CHUNK_SIZE):
        # 不可分割的超限块(如大表格)按块长放大输出预算,避免确定性截断
        budget = max(MAX_TOKENS_CHUNK, len(chunk) * 2 + 200)
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context, source=source)
        parts.append(translated)
        # 前段上下文:上一段(原文+译文)尾部,供下一段术语保持一致
        prev_context = f"原文: {chunk[-half:]}\n译文: {translated[-half:]}"
    return "".join(parts)
```

- [ ] **Step 4: 运行测试确认 GREEN**

```bash
python -m pytest tests/test_translator.py -v
```

预期:全部 PASS(现有测试 + 3 项新测试,共 117 项)。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: 块级修复警告携带文件路径(source 参数贯穿修复循环)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 文档层与文件/stdin 入口接线

**Files:**
- Modify: `src/md2zh/translator.py`(`_translate_document` 88-106 行、`_translate_frontmatter` 169-177 行、`translate_file` 76 行、`run_stdin` 244 行)
- Test: `tests/test_translator.py`(追加 3 项测试)

**Interfaces:**
- Consumes: Task 1 的 `_repair`/`_translate_chunk`/`_translate_long` 的 `source` 参数
- Produces:`_translate_document(text, glossary, api_base, model, *, source: str = "")`;`_translate_frontmatter(fm, glossary, api_base, model, *, source: str = "")`

- [ ] **Step 1: 写失败测试**

在 `tests/test_translator.py` 文件末尾追加(`_FakeStdin` 类已在文件中定义,直接复用):

```python
def test_document_frontmatter_warning_names_source(monkeypatch, capsys):
    # 经 _translate_document 的 frontmatter 修复警告携带 source
    outputs = iter(["坏译文", "还是坏", "依然坏", "正文译文"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "---\ntitle: Hello\n---\n\nBody"
    result = translator._translate_document(text, [], "http://x", "m", source="docs/a.md")
    assert "title: Hello" in result  # frontmatter 回退原文,结构保留
    err = capsys.readouterr().err
    assert "md2zh: 警告: docs/a.md: frontmatter 重译耗尽,保留原文" in err


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
```

- [ ] **Step 2: 运行测试确认 RED**

```bash
python -m pytest tests/test_translator.py::test_document_frontmatter_warning_names_source tests/test_translator.py::test_translate_file_warning_names_path tests/test_translator.py::test_run_stdin_warning_names_stdin -v
```

预期:全部 FAIL(`test_document_frontmatter_warning_names_source` 为 TypeError,其余两项为断言失败——警告尚无路径前缀)。

- [ ] **Step 3: 最小实现**

`src/md2zh/translator.py` 四处修改:

修改 1 — `_translate_document` 签名加 `*, source: str = ""`,并下传:

```python
def _translate_document(text: str, glossary: list[str], api_base: str, model: str,
                        *, source: str = "") -> str:
    """文档级翻译:frontmatter 独立翻译,正文按单次/分段策略处理。"""
    fm, rest = markdown.split_frontmatter(text)
    protected, mapping = markdown.protect_code_blocks(rest)

    if fm is None:
        head = ""
    else:
        head = _translate_frontmatter(fm, glossary, api_base, model, source=source)

    if len(protected) <= SINGLE_CALL_LIMIT:
        body = _translate_chunk(protected, glossary, api_base, model, MAX_TOKENS_SINGLE, source=source)
    else:
        body = _translate_long(protected, glossary, api_base, model, source=source)

    body = markdown.restore_code_blocks(body, mapping)
    if head:
        return f"{head.rstrip()}\n\n{body.lstrip()}"
    return body
```

修改 2 — `_translate_frontmatter` 签名加 `*, source: str = ""`,`_repair` 调用加 `source=source,`:

```python
def _translate_frontmatter(fm: str, glossary: list[str], api_base: str, model: str,
                           *, source: str = "") -> str:
    """frontmatter 独立翻译:仅译 value;校验失败重译,仍失败保留原文。"""
    ok, dst = _repair(
        make_prompt=lambda fix: api.build_frontmatter_prompt(fm, glossary, fix_notes=fix),
        check=lambda d: checks.check_frontmatter(fm, d),
        api_base=api_base, model=model, max_tokens=MAX_TOKENS_SINGLE, label="frontmatter",
        source=source,
    )
    return dst if ok else fm
```

修改 3 — `translate_file` 的 `_translate_document` 调用传 `source=src_path`(该行与 `run_stdin` 中同文本,Edit 时用下方唯一上下文):

```python
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        translated = _translate_document(text, glossary, api_base, model, source=src_path)
        _atomic_write(dst_path, translated.replace("\r\n", "\n"), newline=newline)
```

修改 4 — `run_stdin` 的 `_translate_document` 调用传 `source="<stdin>"`(用下方唯一上下文区分):

```python
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    try:
        translated = _translate_document(text, glossary, api_base, model, source="<stdin>")
```

- [ ] **Step 4: 运行测试确认 GREEN**

```bash
python -m pytest -v
```

预期:全部 PASS,共 120 项(114 现有 + 6 新增)。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: 文档层与文件/stdin 入口接线,警告补文件上下文

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 版本 0.2.1 与发布文档

**Files:**
- Modify: `tests/test_version.py`、`src/md2zh/__init__.py`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: Task 2 完成的全部功能

- [ ] **Step 1: 更新版本测试(确认 RED)**

`tests/test_version.py` 断言改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.2.1"
```

运行 `python -m pytest tests/test_version.py -v`,预期 FAIL(当前 `__version__ == "0.2.0"`)。

- [ ] **Step 2: 提升版本号(确认 GREEN)**

`src/md2zh/__init__.py`:`__version__ = "0.2.1"`。

运行 `python -m pytest tests/test_version.py -v`,预期 PASS。

- [ ] **Step 3: 更新 CHANGELOG**

`CHANGELOG.md` 顶部 `## [0.2.0] - 2026-10-12` 之前插入:

```markdown
## [0.2.1] - 2026-10-12

### 修复

- 块级修复警告补文件路径前缀(如 `md2zh: 警告: docs/a.md: 块重译耗尽,保留原文: ...`),批量模式下可定位问题文件;stdin 模式显示 `<stdin>`
```

- [ ] **Step 4: 更新 CLAUDE.md**

1. 「流约定」一节末尾追加一句:`块级修复警告带文件路径前缀(stdin 模式为 `<stdin>`)。`
2. 运行 `git log --oneline -3` 取得本次 3 个提交哈希,在「Recent Updates」顶部新增一条(v0.2.1 警告补文件上下文),格式参照既有条目(功能一句话 + 提交哈希区间 + 测试通过数 120/120)。

- [ ] **Step 5: 全量验证并提交**

```bash
python -m pytest -v
```

预期:120 passed。

```bash
git add tests/test_version.py src/md2zh/__init__.py CHANGELOG.md CLAUDE.md
git commit -m "docs: 版本 0.2.1 与变更日志(警告补文件上下文)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage:** 规格 §4.2 全部签名改动落在 Task 1/2;§5 测试表 5 项全部覆盖(另加 1 项 `_translate_long` 转发测试);§6 文档落 Task 3;§7 非目标未引入。
- **Placeholder scan:** 无 TBD/TODO;所有代码步骤含完整代码与命令。
- **Type consistency:** `source: str = ""` 仅关键字参数在全部 5 个函数签名一致;测试断言字符串与实现输出逐字一致(已对照现有代码核实 `label="块"`/`"frontmatter"`、`REPAIR_RETRIES=2`、`check_frontmatter` 无 `---` 必报错、`chunk_text` 超限单段不切割)。
