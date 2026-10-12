# frontmatter 校验移除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除 frontmatter 校验:frontmatter 按现有提示词规则翻译后不校验、不重译、不回退,译文直接采用。

**Architecture:** `_translate_frontmatter` 不再走 `_repair`(单次调用直接返回译文,`source` 参数删除);`checks.check_frontmatter` 与 `_keys` 删除(不留死代码);`build_frontmatter_prompt` 与 `markdown.split_frontmatter` 不动。正文三重校验(链接/表格/占位符)、修复循环、回退语义、退出码、流约定零改动。

**Tech Stack:** Python ≥ 3.10、pytest(API 全 mock)。

## Global Constraints

- 版本号按语义化版本提升至 **0.2.5**(patch)。
- `_translate_frontmatter` 新签名 `(fm, glossary, api_base, model) -> str`(删除 `source`);`_translate_document` 调用点同步。
- `checks.py` 删除 `check_frontmatter` 与 `_keys` 后仅剩链接/表格/占位符三个检查函数;**不留死代码**。
- `build_frontmatter_prompt` 与 `markdown.split_frontmatter` **一行不动**(「现有规则」)。
- 链接/表格/占位符校验、REPAIR_RETRIES=2、正文回退语义、退出码、流约定、换行保真均不变;不修改 `references/call_api.py`。
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → GREEN → 提交;每任务独立提交;提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾。
- 测试数演进:**127 → 124**(删 3 项 check 测试,改写 2 项 translator 测试净 0);全部任务完成后 124 项全绿。
- 源码 `src/`、测试 `tests/`;代码注释与用户可见输出一律中文。
- **发布前置(控制方执行)**:真实 API 跑 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\skills\analyzing-local-repositories\SKILL.md" --force`(验收:frontmatter 警告 0、`SKILL_zh.md` 的 frontmatter 为中文不再回退)与 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md" --force`(回归:加黑 0、链接 ≤1);不达则裁决。
- anaconda 的 PytestDeprecationWarning 是既有环境噪音,忽略。

---

### Task 1: frontmatter 校验移除

**Files:**
- Modify: `src/md2zh/translator.py`(`_translate_frontmatter` 整体替换、`_translate_document` 调用点)、`src/md2zh/checks.py`(删 `check_frontmatter` 与 `_keys`)
- Test: `tests/test_checks.py`(删 3 项)、`tests/test_translator.py`(改写 2 项)

**Interfaces:**
- Consumes: 无(既有 `_repair` 仍由 `_translate_chunk` 使用,不动)。
- Produces: `_translate_frontmatter(fm, glossary, api_base, model) -> str` 单次调用直接返回译文;`checks` 模块不再导出 `check_frontmatter`/`_keys`。终态测试数 124。

- [ ] **Step 1: 删除 check_frontmatter 的 3 项测试并改写 2 项 translator 测试**

`tests/test_checks.py` 删除以下 3 个函数(整段删除):

```python
def test_check_frontmatter_ok():
    src = "---\ntitle: Hello\n---"
    assert checks.check_frontmatter(src, "---\ntitle: 你好\n---") == []


def test_check_frontmatter_key_changed():
    problems = checks.check_frontmatter("---\ntitle: Hello\n---", "---\n标题: 你好\n---")
    assert problems


def test_check_frontmatter_missing_markers():
    problems = checks.check_frontmatter("---\ntitle: Hello\n---", "title: 你好")
    assert problems
```

`tests/test_translator.py` 把 `test_frontmatter_fallback_to_original` 整体替换为:

```python
def test_frontmatter_key_changed_accepted(monkeypatch, tmp_path):
    # frontmatter 不再校验:模型改了 key 也直接采用,不回退原文、不重译
    src = tmp_path / "A.md"
    src.write_text("---\ntitle: Hello\n---\n\n正文", encoding="utf-8")
    calls = {"n": 0}
    # 3 份同款改 key 译文 + 正文:旧实现 3 次校验失败后回退原文(共 4 次调用)
    outputs = iter(["---\n标题: 错\n---"] * 3 + ["译文"])

    def fake(*a, **k):
        calls["n"] += 1
        return next(outputs)

    monkeypatch.setattr(api, "translate_text", fake)
    translator.translate_file(str(src), force=False, glossary=[],
                              api_base="http://x", model="m")
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "标题: 错" in content        # 译文 frontmatter 直接采用
    assert "title: Hello" not in content  # 不回退原文
    assert calls["n"] == 2               # frontmatter + 正文各一次,无重译
```

`tests/test_translator.py` 把 `test_document_frontmatter_warning_names_source` 整体替换为:

```python
def test_document_frontmatter_no_repair_warning(monkeypatch, capsys):
    # frontmatter 不再校验:经 _translate_document 无重译、无警告,译文直接采用
    outputs = iter(["---\n标题: 你好\n---"] * 3 + ["正文译文"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    text = "---\ntitle: Hello\n---\n\nBody"
    result = translator._translate_document(text, [], "http://x", "m", source="docs/a.md")
    assert "标题: 你好" in result
    assert "title: Hello" not in result
    err = capsys.readouterr().err
    assert "frontmatter" not in err
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py::test_frontmatter_key_changed_accepted tests/test_translator.py::test_document_frontmatter_no_repair_warning -v`
Expected: 2 项 FAIL,AssertionError(旧实现 3 次校验失败后回退原文:译文文件含 `title: Hello` 而非 `标题: 错`、调用 4 次而非 2 次、stderr 含 frontmatter 警告)

- [ ] **Step 3: 最小实现**

1. `src/md2zh/checks.py` 删除 `check_frontmatter` 函数与 `_keys` 函数(整段,含 docstring):

```python
def check_frontmatter(src: str, dst: str) -> list[str]:
    """frontmatter 的 --- 标记与 key 集合必须一致。"""
    problems = []
    if not (src.startswith("---") and src.rstrip().endswith("---")):
        return problems  # 原文异常时由调用方保证,不校验
    if not (dst.startswith("---") and dst.rstrip().endswith("---")):
        problems.append("译文 frontmatter 缺少 --- 标记")
        return problems
    if _keys(src) != _keys(dst):
        problems.append(f"frontmatter key 集合不一致(原文 {_keys(src)},译文 {_keys(dst)})")
    return problems
```

```python
def _keys(frontmatter: str) -> list[str]:
    keys = []
    for line in frontmatter.splitlines():
        line = line.strip()
        if line in ("---", ""):
            continue
        if ":" in line:
            keys.append(line.split(":", 1)[0].strip())
    return keys
```

2. `src/md2zh/translator.py` 的 `_translate_frontmatter` 整体替换为:

```python
def _translate_frontmatter(fm: str, glossary: list[str], api_base: str, model: str) -> str:
    """frontmatter 独立翻译:仅译 value,不校验、不重译、不回退。

    key 与 --- 标记由提示词约束保持;模型偏差直接采用(信任模型取舍,同 v0.2.4 加黑)。
    """
    return api.translate_text(api_base, model,
                              api.build_frontmatter_prompt(fm, glossary), MAX_TOKENS_SINGLE)
```

3. `src/md2zh/translator.py` 的 `_translate_document` 调用点改为:

```python
        head = _translate_frontmatter(fm, glossary, api_base, model)
```

(删除 `source=source`:frontmatter 路径不再产生警告。)

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_checks.py tests/test_translator.py::test_frontmatter_key_changed_accepted tests/test_translator.py::test_document_frontmatter_no_repair_warning tests/test_translator.py::test_frontmatter_translated -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `124 passed`(127 − 3 删除;改写项净 0)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/translator.py src/md2zh/checks.py tests/test_checks.py tests/test_translator.py
git commit -m "feat: 移除 frontmatter 校验,译文直接采用

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 版本 0.2.5 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`、`tests/test_version.py`、`pyproject.toml`、`README.md`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: 任务 1 完成后的测试终态 124 项;版本号 0.2.5。
- Produces: 全仓库版本/文档与 0.2.5 一致,测试 124/124 全绿。

- [ ] **Step 1: 更新版本断言并确认 RED**

`tests/test_version.py` 改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.2.5"
```

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL,`AssertionError: assert '0.2.4' == '0.2.5'`

- [ ] **Step 2: 版本号三处同步并确认 GREEN**

- `src/md2zh/__init__.py`:`__version__ = "0.2.4"` → `__version__ = "0.2.5"`
- `pyproject.toml`:`version = "0.2.4"` → `version = "0.2.5"`

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 3: README 徽章、测试数与 frontmatter 表述**

`README.md` 七处替换(按文本匹配,不得改动其他内容):

- 第 6 行:`![Version](https://img.shields.io/badge/version-0.2.4-brightgreen)` → `version-0.2.5`
- 第 7 行:`![Tests](https://img.shields.io/badge/tests-127%20passed-brightgreen)` → `tests-124%20passed`
- 第 30 行:`frontmatter(仅译 value,key 与 \`---\` 标记不变)` → `frontmatter(仅译 value,key 与 \`---\` 标记由提示词约束保持)`
- 第 77 行:`frontmatter 的 key 与 \`---\` 标记不变` → `frontmatter 的 key 与 \`---\` 标记由提示词约束保持`
- 第 136 行:`# 运行全部测试(127 项,API 已 mock,不依赖网络)` → `124 项`
- 第 158 行:`├── tests/              # 127 项测试,API 全 mock` → `124 项测试`
- 第 167 行:`- frontmatter 识别与表格分块采用启发式:复杂嵌套 YAML frontmatter、紧凑表格等边界场景由校验+回退原文兜底,格式正确性优先;` → `- frontmatter 识别与表格分块采用启发式:frontmatter 不校验、译文直接采用;表格等边界场景由校验+回退原文兜底,格式正确性优先;`

(若行号因先前改动偏移,按文本匹配替换。)

- [ ] **Step 4: CHANGELOG 新增 0.2.5 小节**

在 `## [0.2.4] - 2026-10-12` 之前插入(最新在前):

```markdown
## [0.2.5] - 2026-10-12

### 变更

- 不再校验 frontmatter:按现有提示词规则翻译后译文直接采用,不重译、不回退(消除 YAML 折叠标量续行被冒号启发式误判导致的整块回退;取舍:模型若改 key 或丢 --- 标记将直接写出,由提示词约束保持)
```

链接区两处更新:

- `[Unreleased]: https://github.com/wzlu/bilibli-translator/compare/v0.2.4...HEAD` → `.../compare/v0.2.5...HEAD`
- 在其后新增一行:`[0.2.5]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.5`

- [ ] **Step 5: CLAUDE.md 同步**

五处替换(既有行内的精确子串):

- Overview:`当前版本 0.2.4。` → `当前版本 0.2.5。`
- 测试行:`python -m pytest -v`(127 项,API 全部 mock,不依赖真实网络) → 把 `127 项` 改为 `124 项`
- Architecture 的 checks.py 行:`纯函数块级校验:链接、表格、frontmatter、占位符` → `纯函数块级校验:链接、表格、占位符`
- 「frontmatter 独立翻译」条目:`仅译 value,key 与 \`---\` 标记严格保留,校验失败回退原文` → `仅译 value,key 与 \`---\` 标记由提示词约束保持,不校验、不重译、不回退`
- Important Notes 已知限制行:`表格行跨表按全局下标配对、frontmatter 冒号启发式、紧凑表格 \`|--|--|\` 不识别等启发式边界` → 删除 `、frontmatter 冒号启发式`(校验已移除,该启发式仅识别用、不再引发失败)

Recent Updates 顶部新增条目:先运行

```bash
git log --format=%h -1
git rev-list --count d83ee6f..HEAD
```

把得到的 `<尾哈希>` 与 `<提交数>` 填入条目(格式与 v0.2.4 条目一致):

```markdown
v0.2.5 frontmatter 校验移除:d83ee6f..<尾哈希> 共 <提交数> 个提交(计划 + 任务 1 实施),本提交为文档同步;124/124 测试通过。frontmatter 翻译后不再校验,译文直接采用。真实 API 复验结果:见发布说明。
```

- [ ] **Step 6: 全量回归并提交**

Run: `python -m pytest -v`
Expected: `124 passed`

```bash
git add src/md2zh/__init__.py tests/test_version.py pyproject.toml README.md CHANGELOG.md CLAUDE.md
git commit -m "docs: 版本 0.2.5 与变更日志(frontmatter 校验移除)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 发布前真实 API 复验(控制方执行,非子代理任务)

任务 1-2 全部完成并审查通过后,控制方执行:

1. 运行 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\skills\analyzing-local-repositories\SKILL.md" --force`;统计 stderr:frontmatter 类警告(预期 0);检查 `SKILL_zh.md` 头部 frontmatter 已译为中文(不再回退英文);
2. 运行 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md" --force`;统计:加黑类失败(预期 0)与链接类失败(预期 ≤1,v0.2.3 已知错位残余)——回归确认正文路径不受影响;
3. 判定:frontmatter 警告 0 且加黑 0 且链接 ≤1 → 通过,进入发布;不达 → 裁决(回退对应改动或接受并如实记录);
4. 复验结果回填 CLAUDE.md 条目「真实 API 复验结果」并记入 `.superpowers/sdd/progress.md`。

---

## 自审结论

- **规格覆盖**:§2 需求 1(frontmatter 单次调用/source 删除)→ 任务 1 Step 3;需求 2(check_frontmatter/_keys 删除、提示词与 split_frontmatter 不动)→ 任务 1 Step 3 与全局约束;需求 3(正文三重校验等不变)→ 全局约束与任务 1 范围;需求 4(删 3/改写 2/终态 124)→ 任务 1;§5 真实 API 复验 → 「发布前真实 API 复验」小节(两次运行与验收阈值逐字一致);§6 文档 → 任务 2。
- **占位符扫描**:无 TBD/「类似任务 N」;所有代码步骤给出完整代码;CLAUDE.md 提交范围哈希由确切命令运行时取值。
- **类型一致性**:测试数演进 127 → 124 与回归预期吻合;`_translate_frontmatter` 新签名与调用点逐字一致;RED 预期(AssertionError:旧实现回退/4 次调用/警告存在)与新旧行为推演一致;复验验收阈值与规格 §5 逐字一致。
