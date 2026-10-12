# 重译计数器修复与加黑校验移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复重译计数器越界(不再打印 `重译(3/2)`),并从校验管线移除加黑检查(四重校验收敛为链接/表格/占位符三重)。

**Architecture:** `_repair` 打印重译行前加守卫(仅在有后续重译时打印);`_check_block` 检查序列删 `check_bold`,`checks.check_bold` 与其测试删除,`build_frontmatter_prompt` 删除从未被执行过的加黑约束行。链接/表格/占位符校验、修复循环、回退语义不动。

**Tech Stack:** Python ≥ 3.10、pytest(API 全 mock)。

## Global Constraints

- 版本号按语义化版本提升至 **0.2.4**(patch)。
- 计数器语义:`重译(x/2)` = 第 x 次重译即将进行;耗尽路径警告序列恰为 `重译(1/2)`、`重译(2/2)`、`重译耗尽`,**不出现** `重译(3/2)`。
- 加黑校验移除范围:`_check_block` 序列、`checks.check_bold` 函数与 `_BOLD` 常量、`build_frontmatter_prompt` 的「`**` 加黑标记必须成对出现…」行、`check_bold` 的 4 项测试。**不留死代码**。
- 链接/表格/占位符校验、REPAIR_RETRIES=2、回退语义、退出码、流约定、frontmatter 校验(check_frontmatter)均不变;不修改 `references/call_api.py`。
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → GREEN → 提交;每任务独立提交;提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾。
- 测试数演进:**129 → 130 → 127**;全部任务完成后 127 项全绿。
- 源码 `src/`、测试 `tests/`;代码注释与用户可见输出一律中文。
- **发布前置(控制方执行)**:真实 API 跑 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md"`,验收:加黑类失败 = 0 且链接类 ≤ 1(v0.2.3 已知错位残余);不达则裁决。
- anaconda 的 PytestDeprecationWarning 是既有环境噪音,忽略。

---

### Task 1: 重译计数器越界修复

**Files:**
- Modify: `src/md2zh/translator.py`(`_repair` 循环内警告行)
- Test: `tests/test_translator.py`(+1)

**Interfaces:**
- Consumes: 无(既有 `_repair` 签名不变)。
- Produces: 耗尽路径警告序列无 `重译(3/2)`;Task 2/3 不依赖,但既有警告测试断言 `重译(1/2)` 仍须通过。

- [ ] **Step 1: 写失败测试**

`tests/test_translator.py` 末尾追加:

```python
def test_chunk_repair_warning_retry_counter_bounded(monkeypatch, capsys):
    # 重译计数器不得越界:耗尽路径恰为 重译(1/2)、重译(2/2),无 重译(3/2)
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096)
    err = capsys.readouterr().err
    assert "重译(1/2)" in err
    assert "重译(2/2)" in err
    assert "重译(3/2)" not in err
    assert "块重译耗尽,保留原文" in err
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py::test_chunk_repair_warning_retry_counter_bounded -v`
Expected: FAIL,AssertionError(`重译(3/2)` 出现在 err 中)

- [ ] **Step 3: 最小实现**

`src/md2zh/translator.py` 的 `_repair` 中,把

```python
        sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{REPAIR_RETRIES}): {';'.join(problems)}\n")
```

改为:

```python
        if attempt < REPAIR_RETRIES:
            sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{REPAIR_RETRIES}): {';'.join(problems)}\n")
```

(末次失败不再打印重译行,直接落入循环后的「重译耗尽」行。)

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_translator.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `130 passed`

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "fix: 重译计数器不再越界打印

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 加黑校验移除

**Files:**
- Modify: `src/md2zh/checks.py`(删 `_BOLD` 与 `check_bold`)、`src/md2zh/translator.py`(`_check_block`)、`src/md2zh/api.py`(`build_frontmatter_prompt` 约束列表)
- Test: `tests/test_checks.py`(删 4 项)、`tests/test_translator.py`(改写 1 项、增 1 项)

**Interfaces:**
- Consumes: 任务 1 的 `_repair` 守卫(不影响本任务);`_check_block` 为 `_translate_chunk`/`_repair` 内部消费,仅内部调用。
- Produces: `_check_block` 检查序列为 `(checks.check_links, checks.check_tables, checks.check_placeholders)`;`checks` 模块不再导出 `check_bold`。终态测试数 127。

- [ ] **Step 1: 删除 check_bold 的 4 项测试并写失败测试**

`tests/test_checks.py` 删除以下 4 个函数(整段删除,含注释):

```python
def test_check_bold_ok():
    assert checks.check_bold("**重要** 内容", "**重要** 内容") == []


def test_check_bold_count_mismatch():
    problems = checks.check_bold("**a** **b**", "**a** b")
    assert problems


def test_check_bold_unpaired():
    problems = checks.check_bold("", "**a")
    assert problems
```

以及文件末尾的:

```python
def test_check_bold_odd_source_not_flagged():
    # 源文本身 ** 不成对时,不因译文奇偶性误报(否则该块永远无法通过校验)
    assert checks.check_bold("a ** b", "甲 ** 乙") == []
```

`tests/test_translator.py` 把 `test_chunk_repair_then_success` 整体替换为(触发机制由加黑改为链接):

```python
def test_chunk_repair_then_success(monkeypatch):
    # 第一次译文丢失链接,第二次修复
    outputs = iter(["没有链接的译文", "[译文](https://x)"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[text](https://x)", [], "http://x", "m", 4096)
    assert result == "[译文](https://x)"
```

`tests/test_translator.py` 末尾追加:

```python
def test_chunk_bold_drift_accepted(monkeypatch):
    # 加黑不再校验:译文丢失 ** 标记仍被接受,不回退原文
    outputs = iter(["粗体内容", "粗体内容", "粗体内容"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("**bold** 内容", [], "http://x", "m", 4096)
    assert result == "粗体内容"
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py::test_chunk_bold_drift_accepted -v`
Expected: FAIL,AssertionError(旧实现 3 次加黑校验失败后回退原文,result 为 `**bold** 内容` ≠ `粗体内容`)

- [ ] **Step 3: 最小实现**

1. `src/md2zh/checks.py` 删除 `_BOLD` 常量与 `check_bold` 函数(整段):

```python
_BOLD = "**"


def check_bold(src: str, dst: str) -> list[str]:
    """加黑标记:** 数量与原文一致;源文成对时译文也必须成对。"""
    problems = []
    if src.count(_BOLD) != dst.count(_BOLD):
        problems.append(f"加黑标记 ** 数量不一致(原文 {src.count(_BOLD)} 个,译文 {dst.count(_BOLD)} 个)")
    if src.count(_BOLD) % 2 == 0 and dst.count(_BOLD) % 2 != 0:
        problems.append("译文 ** 标记不成对")
    return problems
```

2. `src/md2zh/translator.py` 的 `_check_block` 整体替换为:

```python
def _check_block(src: str, dst: str) -> list[str]:
    """块级校验汇总:链接/表格/占位符。"""
    problems: list[str] = []
    for fn in (checks.check_links, checks.check_tables, checks.check_placeholders):
        problems.extend(fn(src, dst))
    return problems
```

3. `src/md2zh/api.py` 的 `build_frontmatter_prompt` 约束列表删除这一行:

```python
        "** 加黑标记必须成对出现、包裹对应的译文词语。",
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_checks.py tests/test_translator.py::test_chunk_bold_drift_accepted tests/test_translator.py::test_chunk_repair_then_success -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `127 passed`(130 − 4 删除 + 1 新增;改写项净 0)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/checks.py src/md2zh/translator.py src/md2zh/api.py tests/test_checks.py tests/test_translator.py
git commit -m "feat: 移除加黑校验,块级校验收敛为三重

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 版本 0.2.4 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`、`tests/test_version.py`、`pyproject.toml`、`README.md`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: 任务 1/2 完成后的测试终态 127 项;版本号 0.2.4。
- Produces: 全仓库版本/文档与 0.2.4 一致,测试 127/127 全绿。

- [ ] **Step 1: 更新版本断言并确认 RED**

`tests/test_version.py` 改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.2.4"
```

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL,`AssertionError: assert '0.2.3' == '0.2.4'`

- [ ] **Step 2: 版本号三处同步并确认 GREEN**

- `src/md2zh/__init__.py`:`__version__ = "0.2.3"` → `__version__ = "0.2.4"`
- `pyproject.toml`:`version = "0.2.3"` → `version = "0.2.4"`

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 3: README 徽章与测试数**

`README.md` 四处替换(按文本匹配,不得改动其他内容):

- 第 6 行:`![Version](https://img.shields.io/badge/version-0.2.3-brightgreen)` → `version-0.2.4`
- 第 7 行:`![Tests](https://img.shields.io/badge/tests-128%20passed-brightgreen)` → `tests-127%20passed`
- 第 136 行:`# 运行全部测试(128 项,API 已 mock,不依赖网络)` → `127 项`
- 第 158 行:`├── tests/              # 128 项测试,API 全 mock` → `127 项测试`

- [ ] **Step 4: CHANGELOG 新增 0.2.4 小节**

在 `## [0.2.3] - 2026-10-12` 之前插入(最新在前):

```markdown
## [0.2.4] - 2026-10-12

### 修复

- 重译计数器越界:耗尽路径不再打印「重译(3/2)」,仅在后续确有重译时打印「重译(x/2)」

### 变更

- 不再校验加黑 ** 标记:块级校验收敛为链接/表格/占位符三重,模型自行增删加黑不再触发重译/回退(取舍:译文可能含不成对 **,由提示词约束与模型自行保持)
```

链接区两处更新:

- `[Unreleased]: https://github.com/wzlu/bilibli-translator/compare/v0.2.3...HEAD` → `.../compare/v0.2.4...HEAD`
- 在其后新增一行:`[0.2.4]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.4`

- [ ] **Step 5: CLAUDE.md 同步**

三处替换(既有行内的精确子串):

- Overview:`当前版本 0.2.3。` → `当前版本 0.2.4。`
- 测试行:`python -m pytest -v`(128 项,API 全部 mock,不依赖真实网络) → 把 `128 项` 改为 `127 项`
- Architecture 的 checks.py 行:`纯函数块级校验:加黑配对、链接、表格、frontmatter、占位符` → `纯函数块级校验:链接、表格、frontmatter、占位符`

Recent Updates 顶部新增条目:先运行

```bash
git log --format=%h -1
git rev-list --count 7777b6b..HEAD
```

把得到的 `<尾哈希>` 与 `<提交数>` 填入条目(格式与 v0.2.3 条目一致):

```markdown
v0.2.4 重译计数器修复与加黑校验移除:7777b6b..<尾哈希> 共 <提交数> 个提交(规格/计划 + 任务 1-2 实施),本提交为文档同步;127/127 测试通过。真实 API 复验结果:见发布说明。
```

- [ ] **Step 6: 全量回归并提交**

Run: `python -m pytest -v`
Expected: `127 passed`

```bash
git add src/md2zh/__init__.py tests/test_version.py pyproject.toml README.md CHANGELOG.md CLAUDE.md
git commit -m "docs: 版本 0.2.4 与变更日志(计数器修复与加黑校验移除)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 发布前真实 API 复验(控制方执行,非子代理任务)

任务 1-3 全部完成并审查通过后,控制方执行:

1. 运行 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md"`(若 `opensre_system_prompt_zh.md` 已存在,追加 `--force`);
2. 统计 stderr 警告:加黑类失败块数(预期 0)与链接类失败块数(预期 ≤1,v0.2.3 已知错位残余);
3. 判定:加黑 = 0 且链接 ≤1 → 通过,进入发布;不达 → 裁决(回退对应改动或接受并如实记录);
4. 复验结果回填 CLAUDE.md 条目「真实 API 复验结果」并记入 `.superpowers/sdd/progress.md`。

---

## 自审结论

- **规格覆盖**:§2 需求 1(计数器)→ 任务 1;需求 2(加黑移除三处 + 测试删除)→ 任务 2;需求 3(三重校验不动)→ 任务 2 Step 3 的范围;需求 4(改写测试/终态 127)→ 任务 2;§5 真实 API 复验 → 「发布前真实 API 复验」小节;§6 文档 → 任务 3。
- **占位符扫描**:无 TBD/「类似任务 N」;所有代码步骤给出完整代码;CLAUDE.md 提交范围哈希由确切命令运行时取值。
- **类型一致性**:测试数演进 129 → 130 → 127 与各任务回归预期吻合;`_check_block` 新序列与规格 §4.2 逐字一致;CHANGELOG 小节措辞与规格 §6 一致;复验验收阈值(加黑 0/链接 ≤1)与规格 §5 逐字一致。
