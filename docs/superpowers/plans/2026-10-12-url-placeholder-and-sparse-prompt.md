# 链接 URL 占位符化与提示词稀疏化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** URL 以 `@@@URL_n@@@` 占位符物理隔离(模型不可见,根治「链接 url 不一致」),提示词约束由 5 条并为 3 条(稀疏化实验,降低加黑漂移失败率)。

**Architecture:** `protect_code_blocks` 增第三步 `_protect_links`(顺序 fenced → inline → links,行内代码内的假链接已被隔离);checks.py/translator.py 源码零改动(URL 占位符被既有占位符与链接检查自动覆盖,文档级还原遍历全映射);`FORMAT_CONSTRAINTS` 并条去枚举。发布前置真实 API 验证(控制方执行,见末尾)。

**Tech Stack:** Python ≥ 3.10、pytest(API 全 mock)、现模块 markdown.protect_code_blocks / checks / api.build_prompt。

## Global Constraints

- 版本号按语义化版本提升至 **0.2.3**(patch)。
- 占位符格式:`@@@URL_n@@@`(n 从 0 递增);映射值 = 原 url(不含括号);显示文本保留照常翻译。
- 保护顺序:**fenced → inline → links**;映射合并 `{**fenced, **inline, **links}`。
- **checks.py 与 translator.py 源码零改动**;`build_frontmatter_prompt` 约束列表不动。
- 新约束列表精确文本(逐字):
  ```python
  FORMAT_CONSTRAINTS = [
      "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。",
      "不得翻译或修改 @@@...@@@ 占位符。",
      "表格保持行数与列数,分隔行保持。",
  ]
  ```
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → GREEN → 提交;每任务独立提交;提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾。
- 现有 123 项测试保持通过(本改动对既有测试纯增量,无需修改既有断言);全部任务完成后共 **128** 项。
- 源码 `src/`、测试 `tests/`;代码注释与用户可见输出一律中文;不修改 `references/call_api.py`。
- **发布前置(控制方执行,非任务步骤)**:真实 API 跑 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md"`,验收:链接类失败 = 0 且加黑失败块数 ≤ 3(基线 4 失败块:加黑 ×3 + 链接 ×1);加黑失败块数 > 3 则回退方向 2 的约束改动后再发布。
- anaconda 的 PytestDeprecationWarning 是既有环境噪音,忽略。

---

### Task 1: 链接 URL 占位符化

**Files:**
- Modify: `src/md2zh/markdown.py`(增 `_LINK_URL_RE` 与 `_protect_links`,`protect_code_blocks` 接第三步)
- Test: `tests/test_markdown.py`(+2)、`tests/test_checks.py`(+1)、`tests/test_translator.py`(+1)

**Interfaces:**
- Consumes: `markdown.protect_code_blocks(text) -> tuple[str, dict[str, str]]`(既有签名不变);`markdown.restore_code_blocks`(既有)。
- Produces: 保护后文本中链接形态为 `[显示文本](@@@URL_n@@@)`;mapping 含 `@@@URL_n@@@ → url`。Task 2/3 不依赖本任务签名,但终态测试数 127 依赖本任务新增 4 项。

- [ ] **Step 1: 写失败测试(3 项 RED + 1 项钉桩)**

`tests/test_markdown.py` 末尾追加:

```python
def test_links_url_protected():
    src = "见 [文档](https://a.dev/x) 与 [下载](https://b.dev/y)"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "https://a.dev/x" not in protected
    assert "https://b.dev/y" not in protected
    assert "[文档]" in protected          # 显示文本保留
    assert "[下载]" in protected
    assert "@@@URL_0@@@" in protected
    assert "@@@URL_1@@@" in protected
    assert mapping["@@@URL_0@@@"] == "https://a.dev/x"
    assert mapping["@@@URL_1@@@"] == "https://b.dev/y"
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_links_inside_inline_code_not_protected():
    # 行内代码整体隔离在先,反引号内的假链接不得被 URL 保护触及
    src = "见 `[x](https://in.code)` 与 [真](https://real.dev)"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "https://real.dev" not in protected
    assert mapping.get("@@@INLINE_0@@@") == "`[x](https://in.code)`"
    assert "@@@URL_0@@@" in protected
    assert markdown.restore_code_blocks(protected, mapping) == src
```

`tests/test_translator.py` 末尾追加(此测试的 fake 内嵌「模型不可见 URL」断言,旧实现下必然失败):

```python
def test_translate_file_link_url_restored(monkeypatch, tmp_path):
    # 链接 URL 占位符化:模型只能看到占位符,译文还原后 url 原样、无占位符残留
    src = tmp_path / "A.md"
    src.write_text("# 标题\n\n见 [官方文档](https://docs.example.com/a) 了解。", encoding="utf-8")

    def fake(*a, **k):
        prompt = a[2]
        # 模型视角:真实 url 不得出现在任何 API 请求中
        assert "https://docs.example.com/a" not in prompt
        # 回传【源文】原文:占位符与本块一致,校验通过
        return prompt.split("【源文】\n", 1)[1].split("\n\n【约束要求】", 1)[0]

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "https://docs.example.com/a" in content
    assert "[官方文档]" in content
    assert "@@@URL" not in content
```

`tests/test_checks.py` 末尾追加(行为钉桩:既有检查对保护形态有效,写后立即通过):

```python
def test_check_links_protected_form_detects_swap():
    # URL 占位符化后,链接检查在保护形态下工作:占位符序列不一致即捕获
    problems = checks.check_links("[a](@@@URL_0@@@)", "[a](@@@URL_1@@@)")
    assert problems
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_markdown.py::test_links_url_protected tests/test_markdown.py::test_links_inside_inline_code_not_protected tests/test_translator.py::test_translate_file_link_url_restored -v`
Expected: 3 项 FAIL——markdown 两项因 url 未被保护(断言 `not in protected` 失败);translator 一项因 fake 内断言失败(`https://docs.example.com/a` 仍在提示词中)。checks 钉桩项 PASS。

- [ ] **Step 3: 最小实现**

`src/md2zh/markdown.py`:

1. `protect_code_blocks` 整体替换为:

```python
def protect_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    """围栏代码块、行内代码与链接 URL 替换为占位符,返回 (保护后文本, 占位符→原文 映射)。

    先处理围栏(其内部的行内代码不重复保护),再处理行内代码,
    最后处理链接 URL(此时反引号内的假链接已被行内占位符隔离);
    未闭合的围栏视为普通文本。
    """
    text, fenced = _protect_fenced(text)
    text, inline = _protect_inline(text)
    text, links = _protect_links(text)
    return text, {**fenced, **inline, **links}
```

2. 在 `_protect_inline` 之后追加:

```python
_LINK_URL_RE = re.compile(r"(\[[^\]\n]*\]\()([^)\n]*)(\))")


def _protect_links(text: str) -> tuple[str, dict[str, str]]:
    """链接 URL 替换为占位符,显示文本保留照常翻译。"""
    mapping: dict[str, str] = {}
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        ph = f"@@@URL_{n}@@@"
        mapping[ph] = m.group(2)
        n += 1
        return f"{m.group(1)}{ph}{m.group(3)}"

    return _LINK_URL_RE.sub(repl, text), mapping
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_markdown.py tests/test_translator.py::test_translate_file_link_url_restored tests/test_checks.py::test_check_links_protected_form_detects_swap -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `127 passed`(123 既有 + 4 新增)

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/markdown.py tests/test_markdown.py tests/test_checks.py tests/test_translator.py
git commit -m "feat: 链接 URL 占位符物理隔离

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 提示词约束稀疏化

**Files:**
- Modify: `src/md2zh/api.py`(`FORMAT_CONSTRAINTS` 常量)
- Test: `tests/test_api.py`(+1)

**Interfaces:**
- Consumes: 无(常量替换,`build_prompt`/`build_frontmatter_prompt` 调用方式不变)。
- Produces: 提示词约束编号列表变 3 条;Task 3 的 CHANGELOG「变更」条目依赖此行为。

- [ ] **Step 1: 写失败测试**

`tests/test_api.py` 的 `test_build_prompt_without_context_has_no_isolation_constraint` 之后追加:

```python
def test_build_prompt_sparse_constraints():
    # 稀疏化实验:约束并条,不再逐项点名加黑与链接标记
    prompt = api.build_prompt("x", [], "")
    assert "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。" in prompt
    assert "不得翻译或修改 @@@...@@@ 占位符。" in prompt
    assert "表格保持行数与列数,分隔行保持。" in prompt
    assert "加黑标记必须成对出现" not in prompt
    assert "只翻译显示文本" not in prompt
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_api.py::test_build_prompt_sparse_constraints -v`
Expected: FAIL,AssertionError(合并后的新约束行不存在)

- [ ] **Step 3: 最小实现**

`src/md2zh/api.py` 的 `FORMAT_CONSTRAINTS` 整体替换为:

```python
# 每次请求携带的 markdown 格式约束(稀疏化:不逐项点名标记,避免模型过度加粗/改写)
FORMAT_CONSTRAINTS = [
    "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。",
    "不得翻译或修改 @@@...@@@ 占位符。",
    "表格保持行数与列数,分隔行保持。",
]
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest tests/test_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest -v`
Expected: `128 passed`

- [ ] **Step 6: 提交**

```bash
git add src/md2zh/api.py tests/test_api.py
git commit -m "feat: 提示词格式约束稀疏化

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 版本 0.2.3 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`、`tests/test_version.py`、`pyproject.toml`、`README.md`、`CHANGELOG.md`、`CLAUDE.md`

**Interfaces:**
- Consumes: 任务 1/2 完成后的测试终态 128 项;版本号 0.2.3。
- Produces: 全仓库版本/文档与 0.2.3 一致,测试 128/128 全绿。

- [ ] **Step 1: 更新版本断言并确认 RED**

`tests/test_version.py` 改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.2.3"
```

Run: `python -m pytest tests/test_version.py -v`
Expected: FAIL,`AssertionError: assert '0.2.2' == '0.2.3'`

- [ ] **Step 2: 版本号三处同步并确认 GREEN**

- `src/md2zh/__init__.py`:`__version__ = "0.2.2"` → `__version__ = "0.2.3"`
- `pyproject.toml`:`version = "0.2.2"` → `version = "0.2.3"`

Run: `python -m pytest tests/test_version.py -v`
Expected: PASS

- [ ] **Step 3: README 徽章与测试数**

`README.md` 四处替换:

- 第 6 行:`![Version](https://img.shields.io/badge/version-0.2.2-brightgreen)` → `![Version](https://img.shields.io/badge/version-0.2.3-brightgreen)`
- 第 7 行:`![Tests](https://img.shields.io/badge/tests-123%20passed-brightgreen)` → `![Tests](https://img.shields.io/badge/tests-128%20passed-brightgreen)`
- 第 136 行:`python -m pytest -v            # 运行全部测试(123 项,API 已 mock,不依赖网络)` → 把 `123 项` 改为 `128 项`
- 第 158 行:`├── tests/              # 123 项测试,API 全 mock` → 把 `123 项测试` 改为 `128 项测试`

(若行号因先前改动偏移,按文本匹配替换,不得改动其他内容。)

- [ ] **Step 4: CHANGELOG 新增 0.2.3 小节**

在 `## [0.2.2] - 2026-10-12` 之前插入(最新在前):

```markdown
## [0.2.3] - 2026-10-12

### 修复

- 链接 URL 以 `@@@URL_n@@@` 占位符物理隔离:URL 不再进入 API 请求,模型无从改写,消除「链接 url 与原文不一致」失败;还原时拼回原 url

### 变更

- 提示词格式约束由 5 条并为 3 条,不再逐项点名加黑与链接标记(稀疏化,降低模型对标记的过度改写)
```

链接区两处更新:

- `[Unreleased]: https://github.com/wzlu/bilibli-translator/compare/v0.2.2...HEAD` → `.../compare/v0.2.3...HEAD`
- 在其后新增一行:`[0.2.3]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.3`

- [ ] **Step 5: CLAUDE.md 同步**

四处替换(既有行内的精确子串):

- Overview:`当前版本 0.2.2。` → `当前版本 0.2.3。`
- 测试行:`python -m pytest -v`(123 项,API 全部 mock,不依赖真实网络) → 把 `123 项` 改为 `128 项`
- 「代码块物理隔离」条目之后新增一条核心设计决策(独立一行,格式与既有条目一致):`- **链接 URL 物理隔离**:[显示文本](url) 的 url 以 @@@URL_n@@@ 占位符替换后才发送 API,模型不可见,还原时拼回`

Recent Updates 顶部新增条目:先运行

```bash
git log --format=%h -1
git rev-list --count 9896253..HEAD
```

把得到的 `<尾哈希>` 与 `<提交数>` 填入条目(格式与 v0.2.2 条目一致):

```markdown
v0.2.3 链接 URL 占位符化与提示词稀疏化:9896253..<尾哈希> 共 <提交数> 个提交(规格/计划 + 任务 1-2 实施),本提交为文档同步;128/128 测试通过。链接 URL 以 @@@URL_n@@@ 物理隔离(模型不可见),提示词格式约束并条去枚举;真实 API 验证结果:见发布说明。
```

- [ ] **Step 6: 全量回归并提交**

Run: `python -m pytest -v`
Expected: `128 passed`

```bash
git add src/md2zh/__init__.py tests/test_version.py pyproject.toml README.md CHANGELOG.md CLAUDE.md
git commit -m "docs: 版本 0.2.3 与变更日志(链接占位符化与提示词稀疏化)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 发布前真实 API 验证(控制方执行,非子代理任务)

任务 1-3 全部完成并审查通过后,控制方执行:

1. 运行 `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md"`(若 `opensre_system_prompt_zh.md` 已存在,追加 `--force` 以真正重译);
2. 收集 stderr 警告,统计:链接类失败块数(预期 0)与加黑失败块数(基线 ≤3);
3. 判定:链接失败 = 0 且加黑 ≤ 3 → 通过,进入发布;加黑 > 3 → 方向 2 判定劣化,回退 `FORMAT_CONSTRAINTS` 改动(恢复 5 条约束)后再发布,并在 CHANGELOG 中删除「变更」小节;
4. 验证结果记入 `.superpowers/sdd/progress.md` 台账与发布说明。

---

## 自审结论

- **规格覆盖**:§2 需求 1 → 任务 1;需求 2 → 任务 2;需求 3(checks 零改动)→ 任务 1 的钉桩测试 + 全量回归;需求 4 → 各任务回归步骤;需求 5(手工实验)→ 「发布前真实 API 验证」小节(验收阈值与回退路径逐字一致);§6 文档与发布 → 任务 3。
- **占位符扫描**:无 TBD/「类似任务 N」;所有代码步骤给出完整代码;CLAUDE.md 提交范围哈希由确切命令运行时取值。
- **类型一致性**:`_protect_links` 返回类型与既有 `_protect_fenced`/`_protect_inline` 一致;`@@@URL_n@@@` 命名与规格 §4.1 一致;测试数演进 123 → 127 → 128 与各任务回归预期吻合;「发布前验证」的基线数字(4 失败块/阈值 3)与规格 §5 逐字一致。
