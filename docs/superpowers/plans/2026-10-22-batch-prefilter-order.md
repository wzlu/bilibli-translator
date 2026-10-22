# 批量模式前置判断顺序优化(译文已存在优先)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 批量模式前置判断顺序改为「译文已存在(非 `--force`)→ 忽略名单 → 提交线程池」,已存在译文的文件在主线程以最短路径跳过。

**Architecture:** 改动仅限 `src/md2zh/translator.py` 的 `run_batch`(前置循环与 docstring);`translate_file` 与 `ignore.py` 不动。严格 TDD:先写失败测试(旧顺序下必红),再改实现,全量回归后提交。

**Tech Stack:** Python ≥3.10、pytest(monkeypatch/capsys)、零新依赖、API 全部 mock。

## Global Constraints

- 改动仅 `src/md2zh/translator.py` 的 `run_batch`;`translate_file`、`ignore.py`、其他模块不动
- 跳过警告文本固定为:`md2zh: 跳过 {p}: 译文已存在(使用 --force 覆盖)`(与 worker 内 detail 文本一致)
- 交叉情形(译文已存在且命中忽略,非 force)计「跳过」不计「忽略」;`--force` 下忽略优先不变
- 退出码契约不变(0/1/64/65/66/74/75/130/141);stdout 只输出数据,进度/警告走 stderr 且经 `_warn`
- 代码注释与用户可见输出一律中文;提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- 每任务:先写失败测试 → 跑红 → 最小实现 → 跑绿 → 提交;测试命令 `python -m pytest -v`

## File Structure

- Modify: `src/md2zh/translator.py` — `run_batch` 前置循环与 docstring(唯一实现改动)
- Modify: `tests/test_translator.py` — 新增 5 个测试(插在 `test_run_batch_ignore_wins_over_force` 之后)
- Modify: `CLAUDE.md` — 「忽略列表」与「批量多线程」两条语义口径
- Modify: `CHANGELOG.md` — 新增 `[0.7.0] - 未发布` 条目

---

### Task 1: run_batch 前置短路核心实现

**Files:**
- Modify: `src/md2zh/translator.py:262-278`(`run_batch` 前置循环与 docstring)
- Test: `tests/test_translator.py`(插在 `test_run_batch_ignore_wins_over_force` 函数之后)

**Interfaces:**
- Consumes: `_zh_path(p) -> str`(同模块,返回 `ABC.md → ABC_zh.md`);`ignore_matcher.is_ignored(p) -> bool`;`_warn(msg)`(模块级 stderr 串行化函数)
- Produces: `run_batch` 行为变更——非 `force` 且 `os.path.exists(_zh_path(p))` 时主线程计「跳过」,不调用 `translate_file`、不调用 `is_ignored`、不提交线程池

- [ ] **Step 1: 写 3 个失败测试**

在 `tests/test_translator.py` 的 `test_run_batch_ignore_wins_over_force` 函数之后插入:

```python
def test_run_batch_existing_translation_skipped_upfront(monkeypatch, tmp_path, capsys):
    # 译文已存在 + 非 force:主线程前置跳过,translate_file 不被调用
    src = tmp_path / "a.md"
    src.write_text("# Hi", encoding="utf-8")
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")

    def fake(src_path, **k):
        raise AssertionError(f"已有译文不应提交翻译: {src_path}")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch([str(src)], force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_OK
    captured = capsys.readouterr()
    assert "md2zh: 跳过 " in captured.err
    assert "汇总: 成功 0,跳过 1,忽略 0,失败 0" in captured.err


def test_run_batch_existing_translation_wins_over_ignore(monkeypatch, tmp_path, capsys):
    # 交叉情形:译文已存在且命中忽略 → 计「跳过」不计「忽略」(非 force)
    src = tmp_path / "a.md"
    src.write_text("# Hi", encoding="utf-8")
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(src) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))

    def fake(src_path, **k):
        raise AssertionError(f"已有译文不应提交翻译: {src_path}")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch([str(src)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    captured = capsys.readouterr()
    assert "md2zh: 跳过 " in captured.err
    assert "md2zh: 忽略 " not in captured.err
    assert "汇总: 成功 0,跳过 1,忽略 0,失败 0" in captured.err


def test_run_batch_existing_translation_not_submitted(monkeypatch, tmp_path):
    # 混合列表:仅无译文文件进入线程池
    src = tmp_path / "a.md"
    src.write_text("# Hi", encoding="utf-8")
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")
    fresh = tmp_path / "b.md"
    fresh.write_text("# Hi", encoding="utf-8")
    submitted: list[str] = []

    def fake(src_path, *, force, glossary, api_base, model, repair, ollama=False, fmt=None):
        submitted.append(src_path)
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch([str(src), str(fresh)], force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=2)
    assert rc == translator.EX_OK
    assert submitted == [str(fresh)]
```

- [ ] **Step 2: 跑测试验证失败**

Run: `python -m pytest tests/test_translator.py -k existing_translation -v`
Expected: 3 failed——测试 1/2:旧实现提交线程池并调用 `translate_file`,fake 抛 `AssertionError`(worker 内异常计入失败),「跳过 1」断言失败;测试 3:`submitted` 含两个文件,`assert submitted == [str(fresh)]` 失败。

- [ ] **Step 3: 最小实现**

编辑 `src/md2zh/translator.py`,第一处替换 docstring(262-266 行):

old:

```python
    忽略列表命中优先于扩展名与存在性检查,且不受 --force 影响;
    命中文件在主线程前置处理,不提交线程池。fmt 显式时全局覆盖,缺省逐文件推断。
```

new:

```python
    前置判断顺序(主线程):非 --force 且译文已存在 → 跳过;命中忽略列表 → 忽略;
    其余提交线程池。忽略优先于扩展名/存在性检查且不受 --force 影响;
    译文已存在优先于忽略,仅非 --force 生效。fmt 显式时全局覆盖,缺省逐文件推断。
```

第二处替换前置循环:

old:

```python
    ok = skipped = ignored = failed = 0
    todo: list[str] = []
    for p in paths:
        if ignore_matcher is not None and ignore_matcher.is_ignored(p):
            _warn(f"md2zh: 忽略 {p}: 命中忽略列表")
            ignored += 1
        else:
            todo.append(p)
```

new:

```python
    ok = skipped = ignored = failed = 0
    todo: list[str] = []
    for p in paths:
        # 前置判断顺序:译文已存在(非 force)→ 忽略名单 → 提交线程池
        if not force and os.path.exists(_zh_path(p)):
            _warn(f"md2zh: 跳过 {p}: 译文已存在(使用 --force 覆盖)")
            skipped += 1
        elif ignore_matcher is not None and ignore_matcher.is_ignored(p):
            _warn(f"md2zh: 忽略 {p}: 命中忽略列表")
            ignored += 1
        else:
            todo.append(p)
```

- [ ] **Step 4: 跑测试验证通过**

Run: `python -m pytest tests/test_translator.py -k existing_translation -v`
Expected: 3 passed。再跑既有忽略相关回归:`python -m pytest tests/test_translator.py -k "ignored or ignore_wins" -v`
Expected: passed(`test_run_batch_ignore_wins_over_force` 为 force=True,exists 不短路,忽略仍优先;`test_run_batch_ignored_not_submitted` 文件无译文,顺序无影响)。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: 批量模式前置跳过已存在译文(非 force 优先于忽略)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 边缘情形与输出顺序锁定

**Files:**
- Test: `tests/test_translator.py`(插在 Task 1 新增测试之后)

**Interfaces:**
- Consumes: Task 1 已实现的 `run_batch` 前置短路;`translator._warn(msg)`(monkeypatch 记录调用顺序)
- Produces: 两项行为锁定——「源文件已删但译文存在」计「跳过」;跳过警告先于任何线程池工作发生

说明:这两项行为是 Task 1 实现的直接结果,本任务为锁定性测试——预期**直接 PASS**;若 FAIL 说明 Task 1 实现有回归,回查 Step 3 的代码。

- [ ] **Step 1: 写 2 个锁定性测试**

在 Task 1 新增测试之后插入:

```python
def test_run_batch_source_gone_translation_exists_skipped(tmp_path, capsys):
    # 源文件已删但译文存在:前置 exists 短路 → 计「跳过」(不再计失败)
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")
    rc = translator.run_batch([str(tmp_path / "a.md")], force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_OK
    assert "汇总: 成功 0,跳过 1,忽略 0,失败 0" in capsys.readouterr().err


def test_run_batch_skip_warn_precedes_workers(monkeypatch, tmp_path):
    # 跳过警告在主线程前置输出,先于任何线程池工作发生
    src = tmp_path / "a.md"
    src.write_text("# Hi", encoding="utf-8")
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")
    fresh = tmp_path / "b.md"
    fresh.write_text("# Hi", encoding="utf-8")
    order: list[tuple[str, str]] = []
    real_warn = translator._warn

    def fake_warn(msg):
        order.append(("warn", msg))
        real_warn(msg)

    def fake(src_path, *, force, glossary, api_base, model, repair, ollama=False, fmt=None):
        order.append(("translate", src_path))
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "_warn", fake_warn)
    monkeypatch.setattr(translator, "translate_file", fake)
    translator.run_batch([str(src), str(fresh)], force=False, glossary=[],
                         api_base="http://x", model="m", max_threads=2)
    skip_idx = order.index(("warn", f"md2zh: 跳过 {src}: 译文已存在(使用 --force 覆盖)"))
    translate_idx = order.index(("translate", str(fresh)))
    assert skip_idx < translate_idx
```

- [ ] **Step 2: 跑测试验证通过**

Run: `python -m pytest tests/test_translator.py -k "source_gone or skip_warn_precedes" -v`
Expected: 2 passed(Task 1 已实现;直接 PASS 属于预期)。

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -v`
Expected: 252 passed(原 247 + 新增 5),0 failed。若有因语义反转失效的旧断言,按规格裁决修正后重跑。

- [ ] **Step 4: 提交**

```bash
git add tests/test_translator.py
git commit -m "test: 锁定批量前置跳过的边缘与输出顺序语义

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 文档同步

**Files:**
- Modify: `CLAUDE.md`(「核心设计决策」中「忽略列表」「批量多线程」两条)
- Modify: `CHANGELOG.md`(顶部新增条目)

**Interfaces:**
- Consumes: 无(纯文档);Produces: 语义口径与变更记录

- [ ] **Step 1: 更新 CLAUDE.md 两条口径**

编辑一,「忽略列表」条目(约第 30 行):

old:

```
- **忽略列表**:`--filelist` 批量模式自动读取当前目录 `.translateignore`(不存在视为无规则);命中文件略过不翻译(忽略优先于扩展名/存在性检查与 `--force`),计入汇总「忽略」数
```

new:

```
- **忽略列表**:`--filelist` 批量模式自动读取当前目录 `.translateignore`(不存在视为无规则);命中文件略过不翻译,计入汇总「忽略」数(交叉情形:非 `--force` 且译文已存在时计「跳过」;忽略优先于扩展名/存在性检查与 `--force` 不变)
```

编辑二,「批量多线程」条目(约第 31 行):

old:

```
并行翻译,忽略命中前置不提交,完成即输出(乱序),计数与汇总在主线程聚合;
```

new:

```
并行翻译,译文已存在(非 `--force`)与忽略命中均前置不提交,完成即输出(乱序),计数与汇总在主线程聚合;
```

- [ ] **Step 2: 更新 CHANGELOG.md**

在 `# 变更日志` 说明段之后、`## [0.6.0] - 2026-10-15` 之前插入:

```markdown
## [0.7.0] - 未发布

### 变更

- 批量模式前置判断顺序:非 `--force` 下「译文已存在」优先于「忽略名单」,命中即在主线程直接跳过(不再做忽略匹配与线程池提交)
- 跳过警告由「随完成乱序输出」改为「前置按文件列表顺序输出」;交叉情形(译文已存在且命中忽略)由计「忽略」改为计「跳过」;源文件已删但译文存在由「失败」改为「跳过」
```

(发布日期、`__init__.py`/`pyproject.toml` 版本号双处同步与 CLAUDE.md Recent Updates 回填由发布流程负责,不在本计划内。)

- [ ] **Step 3: 提交**

```bash
git add CLAUDE.md CHANGELOG.md
git commit -m "docs: 批量前置判断顺序语义口径与 CHANGELOG 0.7.0 条目

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review(计划撰写时已完成)

1. **Spec coverage:** §4.1 改动→Task 1;§4.3 三项语义变更→测试 2/5/4(交叉/顺序/源删)与 Task 3 文档;§6 五项测试→Task 1(1/2/3)+ Task 2(4/5);§7 文档→Task 3;§8「不做的事」→无任务(正确,未做 scandir 缓存/正则合并/参数化跳过)。
2. **Placeholder scan:** 无 TBD/TODO;每步含完整代码与确切命令、预期输出。
3. **Type consistency:** `fake` 签名与既有 `test_run_batch_completed_first_printed_first` 一致;`_warn` 消息文本与 Task 1 实现逐字一致;`TranslateResult("ok", ...)` 字段与 `run_batch` 消费端一致。
