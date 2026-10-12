# 分段上下文占位符泄漏修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除长文分段上下文中的占位符泄漏源——上下文发送前还原为真实代码内容,并以提示词硬约束阻止模型输出上下文内容。

**Architecture:** 分两处改动:`_translate_document` 把 `protect_code_blocks` 的 mapping 下传 `_translate_long`,`_translate_long` 构建上下文时先整块还原、后切尾部;`build_prompt` 在 context 非空时向编号约束列表追加一条隔离硬约束。校验层、回退语义、占位符编号方案全部不动。

**Tech Stack:** Python ≥ 3.10、pytest(API 全 mock)、现模块 `markdown.restore_code_blocks`。

## Global Constraints

- 版本号按语义化版本提升至 **0.2.2**(patch)。
- `_translate_long` 新签名(仅关键字、mapping **必填**):`_translate_long(text: str, glossary: list[str], api_base: str, model: str, *, mapping: dict[str, str], source: str = "") -> str`。
- 还原顺序:**先整块还原、后切尾部**(`markdown.restore_code_blocks(chunk, mapping)[-half:]`),杜绝切出半截占位符令牌。
- 新增硬约束的精确文本(逐字):`【硬性要求】输出仅包含【源文】的译文,不得翻译或输出【上下文参考】中的任何内容。`
- 校验层、回退语义、退出码、流约定、占位符编号方案均不变;不修改 `references/call_api.py`。
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → GREEN → 提交;每任务独立提交。
- 现有 120 项测试保持通过(受影响断言在 TDD 内同步更新);全部任务完成后共 **123** 项。
- 源码 `src/`、测试 `tests/`;代码注释与用户可见输出一律中文。
- 提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾。

---

### Task 1: 分段上下文发送前还原占位符

**Files:**
- Modify: `src/md2zh/translator.py`(两处:`_translate_long` 定义与 `_translate_document` 调用点)
- Test: `tests/test_translator.py`(新增 1 项 + 更新既有 1 处调用点)

**Interfaces:**
- Consumes: `markdown.restore_code_blocks(text: str, mapping: dict[str, str]) -> str`(既有,不变);`markdown.chunk_text`(既有)。
- Produces: `_translate_long(..., mapping=mapping, source=source)`——Task 2/3 不依赖本任务的新签名,但既有测试 `tests/test_translator.py:159` 直接调用点必须随签名更新。

- [ ] **Step 1: 写失败测试**

在 `tests/test_translator.py` 末尾追加(无需新增 import,该文件已导入 `api` 与 `translator`):

```python
def test_long_context_restores_placeholders(monkeypatch):
    # 分段上下文不得携带占位符令牌:上一块尾部的行内代码在上下文中必须是还原后的真实代码,
    # 否则模型会把上一块的占位符带入输出,被判「未知占位符」而整块回退
    prompts = []

    def fake(*a, **k):
        prompt = a[2]  # translate_text(api_base, model, prompt, max_tokens)
        prompts.append(prompt)
        # 伪译文:回传【源文】原文(占位符与本块一致),校验必然通过
        return prompt.split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]

    monkeypatch.setattr(api, "translate_text", fake)
    chunk1 = "正文段落。" * 570 + " 结尾代码 `code_tail`。"
    chunk2 = "后续正文。" * 200 + " 代码 `code_2`。"
    text = chunk1 + "\n\n" + chunk2
    _, mapping = translator.markdown.protect_code_blocks(text)

    result = translator._translate_long(text, [], "http://x", "m", mapping=mapping)

    assert result == text
    assert len(prompts) == 2
    # 第二块请求携带上下文:截取【上下文参考】与【源文】之间的段落
    ctx = prompts[1].split("【上下文参考】(仅供术语一致参考,不要翻译本段)\n", 1)[1].split("\n【源文】", 1)[0]
    assert "`code_tail`" in ctx          # 上一块尾部代码已还原
    assert "@@@INLINE" not in ctx        # 上下文中无占位符令牌
    assert "@@@CODEBLOCK" not in ctx
    # 本块【源文】仍保持占位符保护(代码不出现在源文、占位符在)
    src = prompts[1].split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]
    assert "@@@INLINE_" in src
    assert "`code_2`" not in src
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py::test_long_context_restores_placeholders -v`
Expected: FAIL,`TypeError: _translate_long() got an unexpected keyword argument 'mapping'`

- [ ] **Step 3: 最小实现**

`src/md2zh/translator.py`,把 `_translate_long` 整体替换为:

```python
def _translate_long(text: str, glossary: list[str], api_base: str, model: str,
                    *, mapping: dict[str, str], source: str = "") -> str:
    """超长文本:分段翻译,每段附前段上下文参考保证术语延续。

    上下文发送前还原占位符:占位符令牌不进入 API 请求,防止模型把
    上一块的占位符带入输出而触发「未知占位符」校验失败。
    """
    parts: list[str] = []
    prev_context = ""
    half = CONTEXT_TAIL // 2
    for chunk in markdown.chunk_text(text, CHUNK_SIZE):
        # 不可分割的超限块(如大表格)按块长放大输出预算,避免确定性截断
        budget = max(MAX_TOKENS_CHUNK, len(chunk) * 2 + 200)
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context, source=source)
        parts.append(translated)
        # 前段上下文:上一段(原文+译文)尾部,先还原占位符再切尾部——
        # 上下文与文件原文同形,且不可能切出半截占位符令牌
        src_tail = markdown.restore_code_blocks(chunk, mapping)[-half:]
        dst_tail = markdown.restore_code_blocks(translated, mapping)[-half:]
        prev_context = f"原文: {src_tail}\n译文: {dst_tail}"
    return "".join(parts)
```

`_translate_document` 中调用点改为(原行 `body = _translate_long(protected, glossary, api_base, model, source=source)`):

```python
        body = _translate_long(protected, glossary, api_base, model, mapping=mapping, source=source)
```

- [ ] **Step 4: 运行新测试确认 GREEN**

Run: `python -m pytest tests/test_translator.py::test_long_context_restores_placeholders -v`
Expected: PASS

- [ ] **Step 5: 更新既有调用点并回归**

`tests/test_translator.py:159` 改为:

```python
    result = translator._translate_long(text, [], "http://x", "m", mapping={}, source="docs/a.md")
```

Run: `python -m pytest -v`
Expected: `121 passed`(120 既有 + 1 新增;anaconda pytest-asyncio 的 PytestDeprecationWarning 属环境噪音,可忽略)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: 分段上下文发送前还原占位符

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 提示词追加上下文隔离硬约束

**Files:**
- Modify: `src/md2zh/api.py`(`build_prompt` 约束装配处)
- Test: `tests/test_api.py`(新增 2 项)

**Interfaces:**
- Consumes: 无(既有 `build_prompt(text, glossary, fix_notes="", context="")` 签名不变)。
- Produces: 带 context 的提示词约束列表最后一条为「输出仅包含【源文】的译文…」;不带 context 时约束行数与现状一致。

- [ ] **Step 1: 写失败测试**

在 `tests/test_api.py` 的 `test_build_prompt_with_context` 之后追加:

```python
def test_build_prompt_context_adds_isolation_constraint():
    # 携带上下文时追加硬约束:输出不得包含上下文参考的任何内容
    prompt = api.build_prompt("x", [], context="前文参考")
    assert "【硬性要求】输出仅包含【源文】的译文,不得翻译或输出【上下文参考】中的任何内容。" in prompt


def test_build_prompt_without_context_has_no_isolation_constraint():
    # 无上下文时约束行数与现状一致,不出现隔离约束
    prompt = api.build_prompt("x", [], "")
    assert "不得翻译或输出【上下文参考】" not in prompt
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_api.py::test_build_prompt_context_adds_isolation_constraint -v`
Expected: FAIL,`AssertionError`(断言文本不在 prompt 中)

- [ ] **Step 3: 最小实现**

`src/md2zh/api.py` 的 `build_prompt` 中,把

```python
    constraints = list(FORMAT_CONSTRAINTS)
    _append_requirements(constraints, glossary, fix_notes)
```

改为:

```python
    constraints = list(FORMAT_CONSTRAINTS)
    _append_requirements(constraints, glossary, fix_notes)
    if context:
        # 上下文仅供术语参考:硬性禁止输出上下文内容,防止模型把参考段带入译文
        constraints.append("【硬性要求】输出仅包含【源文】的译文,不得翻译或输出【上下文参考】中的任何内容。")
```

(其后 `req_lines = ...` 编号生成逻辑不动,新约束自然成为最后一条编号项。)

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_api.py -v`
Expected: 全部 PASS(含新增 2 项;既有 `test_build_prompt_with_context` 断言不受影响)

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `123 passed`

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/api.py tests/test_api.py
git commit -m "feat: 提示词追加上下文隔离硬约束

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 版本 0.2.2 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`、`tests/test_version.py`、`pyproject.toml`、`README.md`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: 任务 1/2 完成后的测试终态 123 项;版本号 0.2.2。
- Produces: 全仓库版本/文档与 0.2.2 一致,测试 123/123 全绿。

- [ ] **Step 1: 更新版本断言并确认 RED**

`tests/test_version.py` 改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.2.2"
```

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL,`AssertionError: assert '0.2.1' == '0.2.2'`

- [ ] **Step 2: 版本号三处同步并确认 GREEN**

- `src/md2zh/__init__.py`:`__version__ = "0.2.1"` → `__version__ = "0.2.2"`
- `pyproject.toml` 第 7 行:`version = "0.2.1"` → `version = "0.2.2"`

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 3: README 徽章与测试数**

`README.md` 四处替换:

- 第 6 行:`![Version](https://img.shields.io/badge/version-0.2.1-brightgreen)` → `![Version](https://img.shields.io/badge/version-0.2.2-brightgreen)`
- 第 7 行:`![Tests](https://img.shields.io/badge/tests-120%20passed-brightgreen)` → `![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen)`
- 第 136 行:`python -m pytest -v            # 运行全部测试(120 项,API 已 mock,不依赖网络)` → 把 `120 项` 改为 `123 项`
- 第 158 行:`├── tests/              # 120 项测试,API 全 mock` → 把 `120 项测试` 改为 `123 项测试`

- [ ] **Step 4: CHANGELOG 新增 0.2.2 小节**

在 `## [0.2.0] - 2026-10-12` 之前插入:

```markdown
## [0.2.2] - 2026-10-12

### 修复

- 长文分段上下文发送前还原占位符:占位符令牌不再进入 API 请求,消除「出现未知占位符」警告与整块回退英文原文的根因;携带上下文的提示词追加硬约束,输出不得包含上下文参考内容
```

链接区两处更新:

- `[Unreleased]: https://github.com/wzlu/bilibli-translator/compare/v0.2.1...HEAD` → `.../compare/v0.2.2...HEAD`
- 在其后新增一行:`[0.2.2]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.2`

- [ ] **Step 5: CLAUDE.md 同步**

三处替换(均为既有行内的精确子串):

- Overview:`当前版本 0.2.1。` → `当前版本 0.2.2。`
- 测试行:`python -m pytest -v`(120 项,API 全部 mock,不依赖真实网络) → 把 `120 项` 改为 `123 项`
- 核心设计决策「单次调用为主」条目:`附前段上下文参考保证术语延续)` → `附前段上下文参考保证术语延续;上下文发送前还原占位符,占位符令牌不进 API 请求)`

Recent Updates 顶部新增条目:先运行

```bash
git log --format=%h -1
git rev-list --count 2dff2fa..HEAD
```

把得到的 `<尾哈希>` 与 `<提交数>` 填入条目(格式与既有条目一致):

```markdown
v0.2.2 上下文占位符泄漏修复:2dff2fa..<尾哈希> 共 <提交数> 个提交(规格/计划 + SDD 3 任务 × 实施/审查),123/123 测试通过。长文分段上下文发送前还原占位符(占位符令牌不进 API 请求),提示词追加上下文隔离硬约束,消除「出现未知占位符」整块回退根因。
```

- [ ] **Step 6: 全量回归并提交**

Run: `python -m pytest -v`
Expected: `123 passed`

```bash
git add src/md2zh/__init__.py tests/test_version.py pyproject.toml README.md CHANGELOG.md CLAUDE.md
git commit -m "docs: 版本 0.2.2 与变更日志(上下文占位符泄漏修复)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 自审结论

- **规格覆盖**:§2 需求 1 → 任务 1;需求 2 → 任务 2;需求 3 → 任务 1/2 回归步骤 + 任务 3 终态;需求 4 → 全局约束;§6 文档与发布 → 任务 3。无缺口。
- **占位符扫描**:无 TBD/「类似任务 N」;所有代码步骤给出完整代码;CLAUDE.md 的提交范围哈希由确切命令在运行时取值并给出精确填入格式。
- **类型一致性**:`mapping` 签名在任务 1 定义、既有调用点(测试:159)同步更新;任务 2 不触及 translator;任务 3 的测试数 123 与任务 1/2 的预期回归值一致(121 → 123)。
