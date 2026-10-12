# md2zh 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 md2zh——将英文 Markdown 文件翻译为中文(保存为同目录 `*_zh.md`)的 unix-cli 规范命令行工具,基于 Bilibili 免费翻译 API。

**Architecture:** 五模块分层:`markdown.py`(纯文本块解析与占位符保护)、`checks.py`(纯函数格式校验)、`api.py`(术语表/提示词/流式请求与重试)、`translator.py`(编排:单文件全流程、自动修复循环、批量处理)、`cli.py`(参数解析与退出码映射)。代码块经占位符物理隔离不发给 API;格式一致性由提示词约束 + 块级校验 + 自动重译修复 + 原文回退四重保障。

**Tech Stack:** Python ≥ 3.10,运行期依赖仅 `requests`;开发依赖 `pytest`;setuptools + pyproject.toml,console script 入口 `md2zh`。

**规格文档:** `docs/superpowers/specs/2026-10-12-md2zh-translator-design.md`(已确认)

## Global Constraints

- 运行期依赖仅 `requests`;Python ≥ 3.10
- 源码在 `src/`、测试在 `tests/`、样例数据在 `data/`、报告在 `reports/`
- 所有代码注释与用户可见输出均为中文
- 不得修改 `references/call_api.py`
- 退出码契约(规格 §8):0 成功 / 1 部分失败 / 64 用法错误 / 65 数据格式错误 / 66 输入不可用 / 74 输出错误 / 75 API 临时不可用 / 130 SIGINT
- stdout 只输出数据(成功生成的译文路径,每行一个);进度/警告/汇总走 stderr;错误消息格式 `md2zh: 上下文: 信息`
- 输入 UTF-8(含 BOM),输出 UTF-8;原子写(同目录临时文件 + os.replace)
- 每个任务严格 TDD:先写失败测试 → 运行确认失败 → 最小实现 → 运行确认通过 → 提交

## File Structure

| 文件 | 职责 |
|---|---|
| `src/md2zh/__init__.py` | 版本号 |
| `src/md2zh/markdown.py` | frontmatter 拆分、代码块/行内代码占位符保护与还原、文本分段(纯文本,无 I/O) |
| `src/md2zh/checks.py` | 块级校验:加黑配对、链接、表格、frontmatter、占位符(纯函数) |
| `src/md2zh/api.py` | 术语表加载、提示词构建、流式 HTTP 请求与重试(无文件 I/O) |
| `src/md2zh/translator.py` | 编排层:退出码常量、单文件全流程(含修复循环)、文件列表与批量处理、原子写 |
| `src/md2zh/cli.py` | 参数解析(用法错误退出 64)、退出码映射、main 入口 |
| `tests/` | 各模块测试(API 全部 mock,不依赖真实网络) |
| `pyproject.toml` | 打包与依赖、console script `md2zh` |

---

### Task 1: 项目脚手架(预计 15 分钟)

**Files:**
- Create: `.gitignore`、`pyproject.toml`、`src/md2zh/__init__.py`、`tests/test_version.py`

**Interfaces:**
- Produces: 包 `md2zh`(可导入,`__version__ == "0.1.0"`);console script `md2zh`(Task 11 后可用);git 仓库(目前项目非 git 仓库,本任务初始化以便逐任务提交)

- [ ] **Step 1: 初始化 git 仓库并创建 .gitignore**

```bash
cd /d/ops/bilibli-translator && git init
```

创建 `.gitignore`:

```gitignore
__pycache__/
*.egg-info/
.pytest_cache/
temp/
reports/
dist/
build/
```

- [ ] **Step 2: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "md2zh"
version = "0.1.0"
description = "将英文 Markdown 文件翻译为中文的命令行工具"
requires-python = ">=3.10"
dependencies = ["requests>=2.31"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
md2zh = "md2zh.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: 创建 src/md2zh/__init__.py**

```python
"""md2zh:英文 Markdown 翻译 CLI。"""

__version__ = "0.1.0"
```

- [ ] **Step 4: 写失败测试 tests/test_version.py**

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.1.0"
```

- [ ] **Step 5: 安装并运行测试**

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_version.py -v
```

Expected: `1 passed`

- [ ] **Step 6: 提交**

```bash
git add .gitignore pyproject.toml src/md2zh/__init__.py tests/test_version.py
git commit -m "feat: 搭建 md2zh 项目脚手架

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: markdown.py — frontmatter 拆分(预计 15 分钟)

**Files:**
- Create: `src/md2zh/markdown.py`、`tests/test_markdown.py`

**Interfaces:**
- Produces: `split_frontmatter(text: str) -> tuple[str | None, str]`——开头为 `---` 且存在含 `:` 键值行与闭合 `---` 行时返回 `(含首尾 --- 的 frontmatter, 剩余文本)`,否则 `(None, 原文)`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_markdown.py`)

```python
from md2zh import markdown


def test_no_frontmatter():
    fm, rest = markdown.split_frontmatter("# 标题\n\n正文\n")
    assert fm is None
    assert rest == "# 标题\n\n正文\n"


def test_frontmatter_split():
    text = "---\ntitle: Hello\n---\n\n# 正文\n"
    fm, rest = markdown.split_frontmatter(text)
    assert fm == "---\ntitle: Hello\n---\n"
    assert rest == "\n# 正文\n"


def test_closing_marker_detection():
    text = "---\ntitle: 测试\n---\n正文"
    fm, rest = markdown.split_frontmatter(text)
    assert fm == "---\ntitle: 测试\n---\n"
    assert rest == "正文"


def test_hr_not_frontmatter():
    # 仅一个 --- 行(水平分隔线),不应识别为 frontmatter
    text = "---\n\n# 正文\n"
    fm, rest = markdown.split_frontmatter(text)
    assert fm is None
    assert rest == text


def test_no_kv_not_frontmatter():
    # 首尾 --- 之间没有键值行,视为水平分隔线
    text = "---\n无冒号内容\n---\n\n# 正文\n"
    fm, rest = markdown.split_frontmatter(text)
    assert fm is None
    assert rest == text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_markdown.py -v`
Expected: FAIL(`ModuleNotFoundError: No module named 'md2zh.markdown'`)

- [ ] **Step 3: 实现 src/md2zh/markdown.py(本任务只含 split_frontmatter)**

```python
"""Markdown 块解析与保护:frontmatter 拆分、代码块占位符、文本分段。"""

import re


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """拆分开头的 frontmatter 块(含首尾 --- 行);无则返回 (None, 原文)。

    识别规则:首行是 ---,且在其与某个闭合 --- 行之间存在含 ":" 的键值行;
    否则视为水平分隔线,不拆分。
    """
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            # 闭合行之前至少一行含 ":",才认定为 frontmatter
            if any(":" in ln for ln in lines[1:i]):
                cut = sum(len(ln) for ln in lines[: i + 1])
                return text[:cut], text[cut:]
            return None, text
    return None, text
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_markdown.py -v`
Expected: `5 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/markdown.py tests/test_markdown.py
git commit -m "feat: markdown 模块支持 frontmatter 拆分

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: markdown.py — 代码块占位符保护与还原(预计 20 分钟)

**Files:**
- Modify: `src/md2zh/markdown.py`
- Test: `tests/test_markdown.py`(追加)

**Interfaces:**
- Produces: `protect_code_blocks(text: str) -> tuple[str, dict[str, str]]`——围栏代码块替换为 `@@@CODEBLOCK_n@@@`、行内代码替换为 `@@@INLINE_n@@@`,返回 `(保护后文本, 占位符→原文 映射)`;`restore_code_blocks(text: str, mapping: dict[str, str]) -> str`——占位符还原,`restore(protect(x)) == x`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_markdown.py`)

```python
def test_fenced_block_protected():
    src = "前文\n```python\nprint(1)\n```\n后文"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "```" not in protected
    assert "print(1)" not in protected
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_inline_code_protected():
    src = "使用 `os.replace` 完成替换"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "`" not in protected
    assert "os.replace" not in protected
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_unclosed_fence_left_as_text():
    src = "```\n未闭合"
    protected, mapping = markdown.protect_code_blocks(src)
    assert protected == src
    assert mapping == {}


def test_multiple_blocks_roundtrip():
    src = "# 标题\n\n```bash\nls\n```\n\n正文 `code` 结束\n"
    protected, mapping = markdown.protect_code_blocks(src)
    assert len(mapping) == 2
    assert markdown.restore_code_blocks(protected, mapping) == src


def test_nested_fence_not_split():
    # 4 反引号围栏内含 3 反引号围栏:不得在内层处截断
    src = "````markdown\n```py\nprint(1)\n```\n````\n"
    protected, mapping = markdown.protect_code_blocks(src)
    assert "print(1)" not in protected
    assert len(mapping) == 1
    assert markdown.restore_code_blocks(protected, mapping) == src
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_markdown.py -v -k "protected or roundtrip or unclosed"`
Expected: FAIL(`AttributeError: module 'md2zh.markdown' has no attribute 'protect_code_blocks'`)

- [ ] **Step 3: 追加实现到 src/md2zh/markdown.py**

```python
_INLINE_RE = re.compile(r"`[^`\n]+`")


def _fence_len(line: str) -> int:
    """统计行首连续反引号个数(围栏开启/闭合判定依据)。"""
    stripped = line.lstrip()
    n = 0
    while n < len(stripped) and stripped[n] == "`":
        n += 1
    return n


def protect_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    """围栏代码块与行内代码替换为占位符,返回 (保护后文本, 占位符→原文 映射)。

    先处理围栏(其内部的行内代码不重复保护),再处理行内代码;
    未闭合的围栏视为普通文本。
    """
    text, fenced = _protect_fenced(text)
    text, inline = _protect_inline(text)
    return text, {**fenced, **inline}


def _protect_fenced(text: str) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    mapping: dict[str, str] = {}
    lines = text.splitlines(keepends=True)
    i, n = 0, 0
    while i < len(lines):
        open_len = _fence_len(lines[i])
        if open_len >= 3:
            start = i
            i += 1
            # 闭合围栏必须不少于开启围栏的反引号个数
            while i < len(lines) and _fence_len(lines[i]) < open_len:
                i += 1
            if i >= len(lines):  # 未闭合:整段视为普通文本
                parts.append("".join(lines[start:]))
                break
            i += 1  # 包含闭合行
            block = "".join(lines[start:i])
            ph = f"@@@CODEBLOCK_{n}@@@"
            mapping[ph] = block
            parts.append(ph)
            n += 1
        else:
            parts.append(lines[i])
            i += 1
    return "".join(parts), mapping


def _protect_inline(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        ph = f"@@@INLINE_{n}@@@"
        mapping[ph] = m.group(0)
        n += 1
        return ph

    return _INLINE_RE.sub(repl, text), mapping


def restore_code_blocks(text: str, mapping: dict[str, str]) -> str:
    """将占位符还原为原始代码内容。"""
    for ph, original in mapping.items():
        text = text.replace(ph, original)
    return text
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_markdown.py -v`
Expected: `10 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/markdown.py tests/test_markdown.py
git commit -m "feat: markdown 模块支持代码块占位符保护与还原

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: markdown.py — 文本分段(预计 20 分钟)

**Files:**
- Modify: `src/md2zh/markdown.py`
- Test: `tests/test_markdown.py`(追加)

**Interfaces:**
- Produces: `chunk_text(text: str, max_chars: int = 3000) -> list[str]`——按空行切分并保留分隔符,表格行/列表项合并为整块;关键性质:`"".join(chunk_text(x)) == x`,单段超过 max_chars 的整块(如大表格)保持完整不切割

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_markdown.py`)

```python
def test_chunk_join_reproduces_text():
    text = "# A\n\n段落一。\n\n| a | b |\n| 1 | 2 |\n\n段落二。\n"
    assert "".join(markdown.chunk_text(text)) == text


def test_chunk_table_kept_whole():
    table = "| a | b |\n" * 10  # 90 字符,超过 max_chars=80 的整块保持完整
    text = "前言\n\n" + table + "\n后语"
    chunks = markdown.chunk_text(text, 80)
    assert any(table in c for c in chunks)


def test_chunk_splits_at_limit():
    text = "段落。\n\n" * 25  # 每块 5 字符,总长 125
    chunks = markdown.chunk_text(text, 100)
    assert len(chunks) >= 2
    assert max(len(c) for c in chunks) <= 100
    assert "".join(chunks) == text


def test_chunk_merged_list_join_consistent():
    # 空行分隔的连续列表项进入合并分支:拼接必须与原文一致
    text = "- a\n\n- b\n\n- c\n"
    chunks = markdown.chunk_text(text)
    assert "".join(chunks) == text
    assert len(chunks) == 1


def test_chunk_merged_tables_join_consistent():
    # 空行分隔的两个表格进入合并分支:拼接必须与原文一致
    # 表格后须有后续内容(尾段),否则合并步 sep 为空,顺序颠倒不可见
    table1 = "| a | b |\n| 1 | 2 |"
    table2 = "| c | d |\n| 3 | 4 |\n"
    text = table1 + "\n\n" + table2 + "\n\n后语"
    assert "".join(markdown.chunk_text(text)) == text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_markdown.py -v -k chunk`
Expected: FAIL(`AttributeError: ... has no attribute 'chunk_text'`)

- [ ] **Step 3: 追加实现到 src/md2zh/markdown.py**

```python
_TABLE_LIST_RE = re.compile(r"^\s*(\||[-*+]|\d+\.)\s+")


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """按逻辑边界切分文本;所有段按序拼接与原文完全一致。

    超出 max_chars 的不可分割块(如大表格)保持完整,不做切割。
    """
    blocks = _logical_blocks(text)
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        if current and size + len(block) > max_chars:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        chunks.append("".join(current))
    return chunks


def _logical_blocks(text: str) -> list[str]:
    """按空行切分并保留分隔符;连续的表格行/列表项合并为一块。"""
    parts = re.split(r"(\n[ \t]*\n)", text)
    blocks: list[str] = []
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if para and _is_table_or_list(para) and blocks and _is_table_or_list(blocks[-1]):
            blocks[-1] += para + sep
            continue
        blocks.append(para + sep)
    return blocks


def _is_table_or_list(para: str) -> bool:
    """段落首行是否为表格行或列表项。"""
    return bool(_TABLE_LIST_RE.match(para))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_markdown.py -v`
Expected: `15 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/markdown.py tests/test_markdown.py
git commit -m "feat: markdown 模块支持按逻辑边界分段

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: checks.py — 块级格式校验(预计 20 分钟)

**Files:**
- Create: `src/md2zh/checks.py`、`tests/test_checks.py`

**Interfaces:**
- Produces(全部返回问题描述列表,空列表 = 通过):
  - `check_bold(src: str, dst: str) -> list[str]`——`**` 数量与原文一致;源文成对时译文也必须成对
  - `check_links(src: str, dst: str) -> list[str]`——链接数量与 url 序列一致
  - `check_tables(src: str, dst: str) -> list[str]`——表格行数与每行列数一致
  - `check_frontmatter(src: str, dst: str) -> list[str]`——`---` 标记与 key 集合一致
  - `check_placeholders(src: str, dst: str) -> list[str]`——占位符集合一致

- [ ] **Step 1: 写失败测试** `tests/test_checks.py`

```python
from md2zh import checks


def test_check_bold_ok():
    assert checks.check_bold("**重要** 内容", "**重要** 内容") == []


def test_check_bold_count_mismatch():
    problems = checks.check_bold("**a** **b**", "**a** b")
    assert problems


def test_check_bold_unpaired():
    problems = checks.check_bold("", "**a")
    assert problems


def test_check_links_ok():
    assert checks.check_links("[文本](https://a.b)", "[译文](https://a.b)") == []


def test_check_links_url_changed():
    problems = checks.check_links("[a](https://a.b)", "[a](https://c.d)")
    assert problems


def test_check_tables_ok():
    src = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    dst = "| 甲 | 乙 |\n|---|---|\n| 一 | 二 |\n"
    assert checks.check_tables(src, dst) == []


def test_check_tables_row_mismatch():
    problems = checks.check_tables("| a |\n| b |\n", "| 甲 |\n")
    assert problems


def test_check_tables_col_mismatch():
    problems = checks.check_tables("| a | b |\n", "| 甲 |\n")
    assert problems


def test_check_frontmatter_ok():
    src = "---\ntitle: Hello\n---"
    dst = "---\ntitle: 你好\n---"
    assert checks.check_frontmatter(src, dst) == []


def test_check_frontmatter_key_changed():
    problems = checks.check_frontmatter("---\ntitle: Hello\n---", "---\n标题: 你好\n---")
    assert problems


def test_check_frontmatter_missing_markers():
    problems = checks.check_frontmatter("---\ntitle: Hello\n---", "title: 你好")
    assert problems


def test_check_placeholders_ok():
    src = "看 @@@CODEBLOCK_0@@@ 这里"
    assert checks.check_placeholders(src, src) == []


def test_check_placeholders_missing():
    problems = checks.check_placeholders("@@@CODEBLOCK_0@@@", "无")
    assert problems


def test_check_bold_odd_source_not_flagged():
    # 源文本身 ** 不成对时,不因译文奇偶性误报(否则该块永远无法通过校验)
    assert checks.check_bold("a ** b", "甲 ** 乙") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_checks.py -v`
Expected: FAIL(`ImportError: cannot import name 'checks' from 'md2zh'`(Python 3.11+ 对缺失子模块的实际措辞))

- [ ] **Step 3: 实现 src/md2zh/checks.py**

```python
"""块级格式校验:全部返回问题描述列表,空列表表示通过。"""

import re

_LINK_RE = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")
_PLACEHOLDER_RE = re.compile(r"@@@[A-Z]+_\d+@@@")
_BOLD = "**"


def check_bold(src: str, dst: str) -> list[str]:
    """加黑标记:** 数量与原文一致;源文成对时译文也必须成对。"""
    problems = []
    if src.count(_BOLD) != dst.count(_BOLD):
        problems.append(f"加黑标记 ** 数量不一致(原文 {src.count(_BOLD)} 个,译文 {dst.count(_BOLD)} 个)")
    if src.count(_BOLD) % 2 == 0 and dst.count(_BOLD) % 2 != 0:
        problems.append("译文 ** 标记不成对")
    return problems


def check_links(src: str, dst: str) -> list[str]:
    """链接数量与 url 序列必须与原文一致。"""
    problems = []
    src_links = _LINK_RE.findall(src)
    dst_links = _LINK_RE.findall(dst)
    if len(src_links) != len(dst_links):
        problems.append(f"链接数量不一致(原文 {len(src_links)} 个,译文 {len(dst_links)} 个)")
    src_urls = [m.split("](", 1)[1][:-1] for m in src_links]
    dst_urls = [m.split("](", 1)[1][:-1] for m in dst_links]
    if src_urls != dst_urls:
        problems.append("链接 url 与原文不一致")
    return problems


def check_tables(src: str, dst: str) -> list[str]:
    """表格行的行数与每行列数必须一致。"""
    problems = []
    src_rows = [ln for ln in src.splitlines() if ln.lstrip().startswith("|")]
    dst_rows = [ln for ln in dst.splitlines() if ln.lstrip().startswith("|")]
    if len(src_rows) != len(dst_rows):
        problems.append(f"表格行数不一致(原文 {len(src_rows)} 行,译文 {len(dst_rows)} 行)")
        return problems
    for i, (s, d) in enumerate(zip(src_rows, dst_rows)):
        if s.count("|") != d.count("|"):
            problems.append(f"第 {i + 1} 个表格行列数不一致")
    return problems


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


def check_placeholders(src: str, dst: str) -> list[str]:
    """所有占位符必须原样出现在译文中。"""
    src_ph = sorted(_PLACEHOLDER_RE.findall(src))
    dst_ph = sorted(_PLACEHOLDER_RE.findall(dst))
    problems = []
    missing = sorted(set(src_ph) - set(dst_ph))
    extra = sorted(set(dst_ph) - set(src_ph))
    if missing:
        problems.append(f"占位符丢失: {missing}")
    if extra:
        problems.append(f"出现未知占位符: {extra}")
    return problems


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

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_checks.py -v`
Expected: `14 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/checks.py tests/test_checks.py
git commit -m "feat: checks 模块实现块级格式校验

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: api.py — 术语表加载与提示词构建(预计 20 分钟)

**Files:**
- Create: `src/md2zh/api.py`、`tests/test_api.py`

**Interfaces:**
- Produces:
  - `DEFAULT_API_BASE = "https://index-translate.bilibili.com/v1"`、`DEFAULT_MODEL = "Index-Translate-35B-A3B"`、`DEFAULT_GLOSSARY = ~/.config/md2zh/glossary.json`、`RETRY_TIMES = 2`、`REQUEST_TIMEOUT = 120`
  - `load_glossary(path: str | None) -> list[str]`——返回 `"A→B"` 列表;默认文件缺失返回 `[]`;显式文件缺失抛 `FileNotFoundError`,格式错误抛 `ValueError`
  - `build_prompt(text, glossary, fix_notes="", context="") -> str`
  - `build_frontmatter_prompt(text, glossary, fix_notes="") -> str`

- [ ] **Step 1: 写失败测试** `tests/test_api.py`

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL(`ImportError: cannot import name 'api' from 'md2zh'`(Python 3.11+ 对缺失子模块的实际措辞))

- [ ] **Step 3: 实现 src/md2zh/api.py(本任务只含常量、load_glossary 与提示词构建)**

```python
"""翻译 API 调用:术语表加载、提示词构建、流式请求与重试。"""

import json
import os
import sys

import requests

DEFAULT_API_BASE = "https://index-translate.bilibili.com/v1"
DEFAULT_MODEL = "Index-Translate-35B-A3B"
DEFAULT_GLOSSARY = os.path.join(os.path.expanduser("~"), ".config", "md2zh", "glossary.json")

RETRY_TIMES = 2
REQUEST_TIMEOUT = 120


class TranslateError(Exception):
    """翻译 API 调用失败(网络错误/HTTP 错误/空结果,重试耗尽)。"""


# 每次请求携带的 markdown 格式约束
FORMAT_CONSTRAINTS = [
    "严格保留 markdown 语法结构。",
    "不得翻译或修改 @@@...@@@ 占位符。",
    "** 加黑标记必须成对出现、包裹对应的译文词语。",
    "链接 [显示文本](url) 只翻译显示文本,url 原样保留。",
    "表格保持行数与列数,分隔行保持。",
]


def load_glossary(path: str | None) -> list[str]:
    """加载术语表,返回 "A→B" 列表。

    显式指定的文件不存在/格式错误时抛异常,由调用方映射退出码;
    默认文件缺失或格式错误时警告并返回空列表。
    """
    explicit = path is not None
    target = path if explicit else DEFAULT_GLOSSARY
    if not os.path.isfile(target):
        if explicit:
            raise FileNotFoundError(f"术语表文件不存在: {target}")
        return []
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        if explicit:
            raise ValueError(f"术语表文件格式错误: {target}: {e}") from e
        sys.stderr.write(f"md2zh: 警告: 默认术语表格式错误,已忽略: {e}\n")
        return []
    if not isinstance(data, dict):
        if explicit:
            raise ValueError(f"术语表文件必须是 JSON 对象: {target}")
        return []
    return [f"{k.strip()}→{str(v).strip()}" for k, v in data.items()]


_OUTPUT_ONLY = "只输出译文,不要有任何额外说明。"


def _append_requirements(constraints: list[str], glossary: list[str], fix_notes: str) -> None:
    """向约束列表追加术语表与修复说明(两个提示词构建器共用)。"""
    if glossary:
        constraints.append("【硬性要求】专名/术语对照: " + "、".join(glossary))
    if fix_notes:
        constraints.append(f"【硬性要求】上次翻译存在以下问题,请修正: {fix_notes}")


def build_prompt(text: str, glossary: list[str], fix_notes: str = "", context: str = "") -> str:
    """构建翻译提示词:【源文】+【约束要求】(格式约束+术语表+修复说明)。"""
    constraints = list(FORMAT_CONSTRAINTS)
    _append_requirements(constraints, glossary, fix_notes)
    req_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(constraints))
    parts = ["请将以下文本翻译为中文,并且严格遵循所有约束要求。", ""]
    if context:
        parts += ["【上下文参考】(仅供术语一致参考,不要翻译本段)", context, ""]
    parts += [
        "【源文】",
        text.strip(),
        "",
        "【约束要求】",
        req_lines,
        "",
        _OUTPUT_ONLY,
    ]
    return "\n".join(parts)


def build_frontmatter_prompt(text: str, glossary: list[str], fix_notes: str = "") -> str:
    """构建 frontmatter 翻译提示词:key 不变、仅译 value、保留 --- 标记。"""
    constraints = [
        "这是 YAML frontmatter:key 保持不变,只翻译 value。",
        "保持首尾 --- 标记、行数与整体结构不变。",
        "不得翻译或修改 @@@...@@@ 占位符。",
        "** 加黑标记必须成对出现、包裹对应的译文词语。",
        "链接 [显示文本](url) 只翻译显示文本,url 原样保留。",
    ]
    _append_requirements(constraints, glossary, fix_notes)
    req_lines = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(constraints))
    return (
        "请将以下 YAML frontmatter 翻译为中文,并且严格遵循所有约束要求。\n\n"
        f"【源文】\n{text.strip()}\n\n"
        f"【约束要求】\n{req_lines}\n\n"
        f"{_OUTPUT_ONLY}"
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api.py -v`
Expected: `9 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/api.py tests/test_api.py
git commit -m "feat: api 模块实现术语表加载与提示词构建

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: api.py — 流式翻译请求与重试(预计 25 分钟)

**Files:**
- Modify: `src/md2zh/api.py`
- Test: `tests/test_api.py`(追加)

**Interfaces:**
- Produces: `translate_text(api_base: str, model: str, prompt: str, max_tokens: int) -> str`——流式调用 chat/completions,网络/HTTP 错误自动重试 `RETRY_TIMES` 次,最终失败抛 `TranslateError`;剥离 `<think>` 前缀,空结果视为错误

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_api.py`)

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api.py -v -k translate_text`
Expected: FAIL(`AttributeError: module 'md2zh.api' has no attribute 'translate_text'`)

- [ ] **Step 3: 追加实现到 src/md2zh/api.py**

```python
def translate_text(api_base: str, model: str, prompt: str, max_tokens: int) -> str:
    """流式调用 chat/completions,失败自动重试,重试耗尽抛 TranslateError。

    采用流式请求规避非流式长文本的网关 504 超时(见 references/call_api.py)。
    """
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    # 网关要求非默认 User-Agent,否则返回 412(见 references/call_api.py)
    headers = {"User-Agent": "Index-Translate-Client/1.0"}
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
    raise TranslateError(str(last_error))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api.py -v`
Expected: `15 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/api.py tests/test_api.py
git commit -m "feat: api 模块实现流式翻译请求与重试

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: translator.py — 单文件核心管线(预计 30 分钟)

**Files:**
- Create: `src/md2zh/translator.py`、`tests/test_translator.py`

**Interfaces:**
- Consumes: `api.translate_text/TranslateError`、`markdown.protect_code_blocks/restore_code_blocks`
- Produces:
  - 常量:`EX_OK=0, EX_PARTIAL=1, EX_USAGE=64, EX_DATAERR=65, EX_NOINPUT=66, EX_IOERR=74, EX_TEMPFAIL=75, EX_SIGINT=130`(全 CLI 唯一出处,cli.py 从此导入)
  - `TranslateResult(status: str, detail: str, exit_code: int)`
  - `translate_file(src_path, *, force, glossary, api_base, model) -> TranslateResult`(基础版:单次调用,无修复循环与 frontmatter 独立翻译,Task 9 扩展)
  - `_zh_path(src_path) -> str`、`_atomic_write(path, content) -> None`

- [ ] **Step 1: 写失败测试** `tests/test_translator.py`

```python
from md2zh import api
from md2zh import translator


def test_zh_path():
    assert translator._zh_path("/tmp/ABC.md") == "/tmp/ABC_zh.md"


def test_translate_file_writes_zh(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("# Hello\n\n正文", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好\n\n译文")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    out = tmp_path / "ABC_zh.md"
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "# 你好\n\n译文"


def test_translate_file_skips_existing(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("# Hello", encoding="utf-8")
    zh = tmp_path / "ABC_zh.md"
    zh.write_text("已有", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "skipped"
    assert zh.read_text(encoding="utf-8") == "已有"


def test_translate_file_force_overwrites(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("# Hello", encoding="utf-8")
    zh = tmp_path / "ABC_zh.md"
    zh.write_text("已有", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=True, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert zh.read_text(encoding="utf-8") == "# 你好"


def test_translate_file_preserves_code_block(monkeypatch, tmp_path):
    src = tmp_path / "ABC.md"
    src.write_text("前文\n```python\nprint(1)\n```\n后文", encoding="utf-8")

    def fake(api_base, model, prompt, max_tokens):
        return "译文前\n@@@CODEBLOCK_0@@@\n译文后"

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "ABC_zh.md").read_text(encoding="utf-8")
    assert "print(1)" in content
    assert "```python" in content


def test_translate_file_missing(monkeypatch, tmp_path):
    result = translator.translate_file(str(tmp_path / "no.md"), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_NOINPUT


def test_translate_file_not_md(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    result = translator.translate_file(str(p), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_NOINPUT


def test_translate_file_api_error(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")

    def fake(*a, **k):
        raise api.TranslateError("网络错误")

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_TEMPFAIL


def test_translate_file_preserves_crlf(monkeypatch, tmp_path):
    # CRLF 源文件输出必须保持 CRLF(格式一致)
    src = tmp_path / "A.md"
    src.write_bytes(b"# Hello\r\n\r\nBody\r\n")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert (tmp_path / "A_zh.md").read_bytes() == "# 你好\r\n".encode("utf-8")


def test_translate_file_preserves_lf(monkeypatch, tmp_path):
    # LF 源文件输出必须保持 LF(格式一致)
    src = tmp_path / "A.md"
    src.write_bytes(b"# Hello\n\nBody\n")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert (tmp_path / "A_zh.md").read_bytes() == "# 你好\n".encode("utf-8")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_translator.py -v`
Expected: FAIL(`ImportError: cannot import name 'translator' from 'md2zh'`(Python 3.11+ 对缺失子模块的实际措辞))

- [ ] **Step 3: 实现 src/md2zh/translator.py(基础版,Task 9/10 扩展)**

```python
"""翻译编排:单文件全流程、修复循环、文件列表批量处理。"""

import os
import sys
import tempfile
from dataclasses import dataclass

from md2zh import api, markdown

# 退出码契约(规格 §8),全 CLI 唯一出处
EX_OK = 0
EX_PARTIAL = 1       # 批量模式存在失败文件
EX_USAGE = 64        # 命令行用法错误
EX_DATAERR = 65      # 术语表文件格式错误
EX_NOINPUT = 66      # 输入文件不存在
EX_IOERR = 74        # 输出写入失败
EX_TEMPFAIL = 75     # 翻译 API 临时不可用
EX_SIGINT = 130

# 翻译策略常量(规格 §11)
SINGLE_CALL_LIMIT = 15000   # 可译文本超过该长度则分段
CHUNK_SIZE = 3000
CONTEXT_TAIL = 800          # 分段时附前段上下文参考的字符数
REPAIR_RETRIES = 2
MAX_TOKENS_SINGLE = 8192
MAX_TOKENS_CHUNK = 4096


@dataclass
class TranslateResult:
    status: str       # "ok" / "skipped" / "failed"
    detail: str = ""  # 状态说明(ok 时为译文路径)
    exit_code: int = 0  # failed 时的具体退出码


def _zh_path(src_path: str) -> str:
    """ABC.md → ABC_zh.md(同目录)。"""
    stem, ext = os.path.splitext(src_path)
    return f"{stem}_zh{ext}"


def _atomic_write(path: str, content: str, newline: str = "\n") -> None:
    """同目录临时文件写入后原子替换,失败时清理临时文件。

    newline 控制换行符输出(保持源文件行尾风格)。
    """
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def translate_file(src_path: str, *, force: bool, glossary: list[str],
                   api_base: str, model: str) -> TranslateResult:
    """翻译单个文件;已存在译文且未 --force 时跳过。"""
    if not src_path.lower().endswith(".md"):
        return TranslateResult("failed", "不是 .md 文件", EX_NOINPUT)
    if not os.path.isfile(src_path):
        return TranslateResult("failed", "文件不存在", EX_NOINPUT)
    dst_path = _zh_path(src_path)
    if os.path.exists(dst_path) and not force:
        return TranslateResult("skipped", "译文已存在(使用 --force 覆盖)")
    try:
        # newline="" 关闭读取期行尾翻译,保留源文件行尾风格供检测;内部管线随后统一为 LF
        with open(src_path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
        # 保持源文件行尾风格:CRLF 源输出 CRLF,LF 源输出 LF
        newline = "\r\n" if "\r\n" in text else "\n"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        translated = _translate_document(text, glossary, api_base, model)
        _atomic_write(dst_path, translated.replace("\r\n", "\n"), newline=newline)
    except api.TranslateError as e:
        return TranslateResult("failed", f"翻译 API 错误: {e}", EX_TEMPFAIL)
    except UnicodeDecodeError as e:
        return TranslateResult("failed", f"源文件不是 UTF-8 编码: {e}", EX_DATAERR)
    except OSError as e:
        return TranslateResult("failed", f"读写文件失败: {e}", EX_IOERR)
    return TranslateResult("ok", dst_path)


def _translate_document(text: str, glossary: list[str], api_base: str, model: str) -> str:
    """文档级翻译(基础版:整文单次调用,Task 9 扩展修复循环/frontmatter/分段)。"""
    protected, mapping = markdown.protect_code_blocks(text)
    prompt = api.build_prompt(protected, glossary)
    translated = api.translate_text(api_base, model, prompt, MAX_TOKENS_SINGLE)
    return markdown.restore_code_blocks(translated, mapping)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_translator.py -v`
Expected: `10 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: translator 模块实现单文件翻译核心管线

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: translator.py — 自动修复循环、frontmatter 与超长分段(预计 40 分钟)

**Files:**
- Modify: `src/md2zh/translator.py`(替换 `_translate_document` 并新增函数)
- Test: `tests/test_translator.py`(追加)

**Interfaces:**
- Consumes: `checks.*`、`markdown.split_frontmatter/chunk_text`、`api.build_prompt/build_frontmatter_prompt`
- Produces:
  - `_translate_chunk(src, glossary, api_base, model, max_tokens, context="") -> str`——校验失败带错误说明重译(≤ `REPAIR_RETRIES` 次),仍失败回退原文
  - `_translate_long(text, glossary, api_base, model) -> str`——分段翻译,每段附前段上下文
  - `_translate_frontmatter(fm, glossary, api_base, model) -> str`——frontmatter 独立翻译,校验失败重译,仍失败保留原文
  - `_check_block(src, dst) -> list[str]`
  - 升级后的 `_translate_document(text, glossary, api_base, model) -> str`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_translator.py`)

```python
def test_chunk_repair_then_success(monkeypatch):
    # 第一次译文加黑不成对,第二次修复
    outputs = iter(["好 **格式 好", "好 **格式** 好"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("好 **格式** 好", [], "http://x", "m", 4096)
    assert result == "好 **格式** 好"


def test_chunk_repair_exhausted_falls_back(monkeypatch):
    # 始终丢失链接:3 次尝试(1 次初译 + 2 次重译)后回退原文
    outputs = iter(["坏译文", "还是坏", "依然坏"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    result = translator._translate_chunk("[a](https://x)", [], "http://x", "m", 4096)
    assert result == "[a](https://x)"


def test_frontmatter_translated(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("---\ntitle: Hello\n---\n\n正文", encoding="utf-8")
    outputs = iter(["---\ntitle: 你好\n---", "译文正文"])

    def fake(*a, **k):
        return next(outputs)

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "title: 你好" in content
    assert "译文正文" in content


def test_frontmatter_fallback_to_original(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("---\ntitle: Hello\n---\n\n正文", encoding="utf-8")
    # frontmatter 3 次尝试都改了 key,正文正常
    outputs = iter(["---\n标题: 错\n---", "---\n标题: 错\n---", "---\n标题: 错\n---", "译文"])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: next(outputs))
    translator.translate_file(str(src), force=False, glossary=[],
                              api_base="http://x", model="m")
    content = (tmp_path / "A_zh.md").read_text(encoding="utf-8")
    assert "title: Hello" in content  # 原文 frontmatter 保留


def test_long_document_chunked(monkeypatch, tmp_path):
    src = tmp_path / "long.md"
    paras = "\n\n".join(f"第 {i} 段内容" for i in range(100))
    src.write_text(paras, encoding="utf-8")
    monkeypatch.setattr(translator, "SINGLE_CALL_LIMIT", 100)
    monkeypatch.setattr(translator, "CHUNK_SIZE", 100)
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "译文段"

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert calls["n"] > 1  # 发生了分段,多次调用
    # 每块译文回挂源块尾随空白(除末块外均为 "\n\n"),分段边界不得焊接
    expected = ("译文段" + "\n\n") * (calls["n"] - 1) + "译文段"
    assert (tmp_path / "long_zh.md").read_text(encoding="utf-8") == expected


def test_translate_file_non_utf8(tmp_path):
    # 非 UTF-8 源文件应返回 EX_DATAERR,而不是让 UnicodeDecodeError 崩溃
    src = tmp_path / "A.md"
    src.write_bytes("# 标题".encode("gbk"))
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "failed"
    assert result.exit_code == translator.EX_DATAERR


def test_oversized_chunk_budget_scaled(monkeypatch, tmp_path):
    # 不可分割的超限块(大表格)按块长放大输出预算,避免确定性截断
    big_table = "| " + "a" * 5000 + " | b |\n"
    src = tmp_path / "big.md"
    src.write_text(big_table, encoding="utf-8")
    monkeypatch.setattr(translator, "SINGLE_CALL_LIMIT", 100)
    budgets = []

    def fake(api_base, model, prompt, max_tokens):
        budgets.append(max_tokens)
        return big_table.rstrip()  # 原样返回(API 层 strip 后的形态)

    monkeypatch.setattr(api, "translate_text", fake)
    result = translator.translate_file(str(src), force=False, glossary=[],
                                       api_base="http://x", model="m")
    assert result.status == "ok"
    assert budgets[0] > translator.MAX_TOKENS_CHUNK  # 预算被放大
    assert budgets[0] >= len(big_table) * 2  # 覆盖两倍块长的输出需求
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_translator.py -v -k "repair or frontmatter or long"`
Expected: FAIL(`AttributeError: ... has no attribute '_translate_chunk'`)

- [ ] **Step 3: 替换 `_translate_document` 并新增函数到 src/md2zh/translator.py**

在文件头部 `from md2zh import api, markdown` 改为:

```python
from md2zh import api, checks, markdown
```

先对 `translate_file` 应用计划 Task 8 修订(非 UTF-8 输入不再崩溃):在 `except api.TranslateError` 与 `except OSError` 两个分支之间插入:

```python
    except UnicodeDecodeError as e:
        return TranslateResult("failed", f"源文件不是 UTF-8 编码: {e}", EX_DATAERR)
```

将原 `_translate_document` 整体替换为:

```python
def _translate_document(text: str, glossary: list[str], api_base: str, model: str) -> str:
    """文档级翻译:frontmatter 独立翻译,正文按单次/分段策略处理。"""
    fm, rest = markdown.split_frontmatter(text)
    protected, mapping = markdown.protect_code_blocks(rest)

    if fm is None:
        head = ""
    else:
        head = _translate_frontmatter(fm, glossary, api_base, model)

    if len(protected) <= SINGLE_CALL_LIMIT:
        body = _translate_chunk(protected, glossary, api_base, model, MAX_TOKENS_SINGLE)
    else:
        body = _translate_long(protected, glossary, api_base, model)

    body = markdown.restore_code_blocks(body, mapping)
    if head:
        return f"{head.rstrip()}\n\n{body.lstrip()}"
    return body


def _check_block(src: str, dst: str) -> list[str]:
    """块级校验汇总:加黑/链接/表格/占位符。"""
    problems: list[str] = []
    for fn in (checks.check_bold, checks.check_links, checks.check_tables, checks.check_placeholders):
        problems.extend(fn(src, dst))
    return problems


def _trailing_whitespace(text: str) -> str:
    """返回文本末尾的空白串(回挂译文以保持分段边界与文件末尾布局)。"""
    return text[len(text.rstrip()):]


def _repair(make_prompt, check, *, api_base: str, model: str,
            max_tokens: int, label: str) -> tuple[bool, str]:
    """通用修复循环:校验失败带错误说明重译,重译耗尽返回 (False, "")。

    make_prompt(fix_notes) 构建带修复说明的提示词;check(dst) 返回问题列表,空列表表示通过。
    """
    problems: list[str] = []
    for attempt in range(REPAIR_RETRIES + 1):
        dst = api.translate_text(api_base, model, make_prompt(";".join(problems)), max_tokens)
        problems = check(dst)
        if not problems:
            return True, dst
        sys.stderr.write(f"md2zh: 警告: {label}校验失败,重译({attempt + 1}/{REPAIR_RETRIES}): {';'.join(problems)}\n")
    sys.stderr.write(f"md2zh: 警告: {label}重译耗尽,保留原文: {';'.join(problems)}\n")
    return False, ""


def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "") -> str:
    """翻译一段文本:校验失败带错误说明重译,仍失败回退原文。"""
    ok, dst = _repair(
        make_prompt=lambda fix: api.build_prompt(src, glossary, fix_notes=fix, context=context),
        check=lambda d: _check_block(src, d),
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
    )
    if not ok:
        return src
    # 译文经 API strip,回挂源块尾随空白,保持分段边界与文件末尾布局
    return dst + _trailing_whitespace(src)


def _translate_long(text: str, glossary: list[str], api_base: str, model: str) -> str:
    """超长文本:分段翻译,每段附前段上下文参考保证术语延续。"""
    parts: list[str] = []
    prev_context = ""
    half = CONTEXT_TAIL // 2
    for chunk in markdown.chunk_text(text, CHUNK_SIZE):
        # 不可分割的超限块(如大表格)按块长放大输出预算,避免确定性截断
        budget = max(MAX_TOKENS_CHUNK, len(chunk) * 2 + 200)
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context)
        parts.append(translated)
        # 前段上下文:上一段(原文+译文)尾部,供下一段术语保持一致
        prev_context = f"原文: {chunk[-half:]}\n译文: {translated[-half:]}"
    return "".join(parts)


def _translate_frontmatter(fm: str, glossary: list[str], api_base: str, model: str) -> str:
    """frontmatter 独立翻译:仅译 value;校验失败重译,仍失败保留原文。"""
    ok, dst = _repair(
        make_prompt=lambda fix: api.build_frontmatter_prompt(fm, glossary, fix_notes=fix),
        check=lambda d: checks.check_frontmatter(fm, d),
        api_base=api_base, model=model, max_tokens=MAX_TOKENS_SINGLE, label="frontmatter",
    )
    return dst if ok else fm
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_translator.py -v`
Expected: `17 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: translator 支持自动修复循环、frontmatter 独立翻译与超长分段

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: translator.py — 文件列表与批量编排(预计 20 分钟)

**Files:**
- Modify: `src/md2zh/translator.py`
- Test: `tests/test_translator.py`(追加)

**Interfaces:**
- Produces:
  - `parse_filelist(path: str) -> list[str]`——逐行读取,跳过空行与 `#` 注释行,行首尾去空白
  - `run_single(path, *, force, glossary, api_base, model) -> int`——成功/跳过 0,失败返回具体退出码
  - `run_batch(paths, *, force, glossary, api_base, model) -> int`——逐文件处理,stdout 输出译文路径,stderr 输出跳过/失败/汇总,存在失败返回 `EX_PARTIAL`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_translator.py`)

```python
def test_parse_filelist(tmp_path):
    lst = tmp_path / "list.txt"
    lst.write_text("# 注释\n\na.md\n  b.md  \n\n", encoding="utf-8")
    assert translator.parse_filelist(str(lst)) == ["a.md", "b.md"]


def test_parse_filelist_with_bom(tmp_path):
    # 带 BOM 的文件列表(Windows 记事本保存)首个条目不得被 ﻿ 污染
    lst = tmp_path / "list.txt"
    lst.write_bytes("﻿a.md\nb.md\n".encode("utf-8"))
    assert translator.parse_filelist(str(lst)) == ["a.md", "b.md"]


def test_run_single_ok_prints_path(monkeypatch, tmp_path, capsys):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_single(str(src), force=False, glossary=[],
                               api_base="http://x", model="m")
    assert rc == translator.EX_OK
    assert str(tmp_path / "A_zh.md") in capsys.readouterr().out


def test_run_single_missing_returns_66(tmp_path, capsys):
    rc = translator.run_single(str(tmp_path / "no.md"), force=False, glossary=[],
                               api_base="http://x", model="m")
    assert rc == translator.EX_NOINPUT
    assert "md2zh:" in capsys.readouterr().err


def test_run_batch_partial_success(monkeypatch, tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    # 坏文件在前:钉住"失败后继续处理"语义
    paths = [str(tmp_path / "missing.md"), str(good)]
    rc = translator.run_batch(paths, force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_PARTIAL
    captured = capsys.readouterr()
    assert "成功 1" in captured.err
    assert "失败 1" in captured.err
    assert str(tmp_path / "good_zh.md") in captured.out
    assert (tmp_path / "good_zh.md").exists()


def test_run_batch_all_ok_returns_0(monkeypatch, tmp_path):
    files = []
    for name in ("a.md", "b.md"):
        p = tmp_path / name
        p.write_text("# Hi", encoding="utf-8")
        files.append(str(p))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_batch(files, force=False, glossary=[],
                              api_base="http://x", model="m")
    assert rc == translator.EX_OK
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_translator.py -v -k "filelist or run_single or run_batch"`
Expected: FAIL(`AttributeError: ... has no attribute 'parse_filelist'`)

- [ ] **Step 3: 追加实现到 src/md2zh/translator.py 末尾**

```python
def parse_filelist(path: str) -> list[str]:
    """解析文件列表:跳过空行与 # 注释行,行首尾去空白。

    utf-8-sig 兼容带 BOM 的文件列表(如 Windows 记事本保存)。
    """
    with open(path, encoding="utf-8-sig") as f:
        return [line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")]


def run_single(path: str, *, force: bool, glossary: list[str],
               api_base: str, model: str) -> int:
    """单文件模式:失败返回具体退出码(65/66/74/75)。"""
    result = translate_file(path, force=force, glossary=glossary,
                            api_base=api_base, model=model)
    if result.status == "ok":
        print(result.detail)
        return EX_OK
    if result.status == "skipped":
        print(f"md2zh: 跳过 {path}: {result.detail}", file=sys.stderr)
        return EX_OK
    print(f"md2zh: 失败 {path}: {result.detail}", file=sys.stderr)
    return result.exit_code


def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str) -> int:
    """批量模式:继续处理所有文件,最后汇总;存在失败返回 EX_PARTIAL。"""
    ok = skipped = failed = 0
    for p in paths:
        result = translate_file(p, force=force, glossary=glossary,
                                api_base=api_base, model=model)
        if result.status == "ok":
            print(result.detail)
            ok += 1
        elif result.status == "skipped":
            print(f"md2zh: 跳过 {p}: {result.detail}", file=sys.stderr)
            skipped += 1
        else:
            print(f"md2zh: 失败 {p}: {result.detail}", file=sys.stderr)
            failed += 1
    print(f"md2zh: 汇总: 成功 {ok},跳过 {skipped},失败 {failed}", file=sys.stderr)
    return EX_PARTIAL if failed else EX_OK
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_translator.py -v`
Expected: `23 passed`

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: translator 支持文件列表与批量编排

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: cli.py — 参数解析与退出码映射(预计 30 分钟)

**Files:**
- Create: `src/md2zh/cli.py`、`tests/test_cli.py`

**Interfaces:**
- Consumes: `translator.EX_*`、`translator.run_single/run_batch/parse_filelist`、`api.load_glossary/DEFAULT_API_BASE/DEFAULT_MODEL/DEFAULT_GLOSSARY`、`__version__`
- Produces: `main(argv: list[str] | None = None) -> int`(console script `md2zh` 入口);用法错误经自定义 `_Parser.error` 以 64 退出

- [ ] **Step 1: 写失败测试** `tests/test_cli.py`

```python
import pytest

from md2zh import api
from md2zh import cli
from md2zh import translator


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "md2zh" in capsys.readouterr().out


def test_missing_args_exit_usage(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == translator.EX_USAGE
    assert "md2zh" in capsys.readouterr().err


def test_file_and_filelist_conflict(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["a.md", "--filelist", "l.txt"])
    assert e.value.code == translator.EX_USAGE


def test_single_file_missing_exit_66(tmp_path):
    assert cli.main([str(tmp_path / "no.md")]) == translator.EX_NOINPUT


def test_single_file_ok(monkeypatch, tmp_path):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main([str(src)]) == translator.EX_OK


def test_glossary_missing_exit_66(tmp_path):
    assert cli.main([str(tmp_path / "a.md"),
                     "--glossary", "/nonexistent/g.json"]) == translator.EX_NOINPUT


def test_glossary_bad_json_exit_65(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("不是 json", encoding="utf-8")
    assert cli.main([str(tmp_path / "a.md"),
                     "--glossary", str(bad)]) == translator.EX_DATAERR


def test_filelist_mode(monkeypatch, tmp_path, capsys):
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(str(src) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    assert str(tmp_path / "A_zh.md") in capsys.readouterr().out
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL(`ImportError: cannot import name 'cli' from 'md2zh'`(Python 3.11+ 对缺失子模块的实际措辞))

- [ ] **Step 3: 实现 src/md2zh/cli.py**

```python
"""命令行入口:参数解析、退出码映射。"""

import argparse
import sys

from md2zh import __version__, api
from md2zh import translator


class _Parser(argparse.ArgumentParser):
    """用法错误按 unix-cli 规范以 EX_USAGE(64) 退出,附简短用法提示。"""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: 错误: {message}", file=sys.stderr)
        print(f"试用 '{self.prog} --help' 获取更多信息。", file=sys.stderr)
        sys.exit(translator.EX_USAGE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _Parser(
        prog="md2zh",
        description="将英文 Markdown 文件翻译为中文,保存为 *_zh.md(同目录)。",
    )
    parser.add_argument("file", nargs="?", metavar="FILE", help="要翻译的 Markdown 文件")
    parser.add_argument("--filelist", metavar="LIST",
                        help="文件列表(每行一个 md 文件,# 开头的行被忽略)")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的 *_zh.md(默认跳过)")
    parser.add_argument("--glossary", metavar="FILE",
                        help=f"术语表文件(JSON);缺省加载 {api.DEFAULT_GLOSSARY}")
    parser.add_argument("--api-base", default=api.DEFAULT_API_BASE,
                        help=f"翻译 API 地址(默认 {api.DEFAULT_API_BASE})")
    parser.add_argument("--model", default=api.DEFAULT_MODEL,
                        help=f"模型(默认 {api.DEFAULT_MODEL})")
    parser.add_argument("--version", action="version", version=f"md2zh {__version__}")
    args = parser.parse_args(argv)
    if args.file and args.filelist:
        parser.error("FILE 与 --filelist 不能同时使用")
    if not args.file and not args.filelist:
        parser.error("需要 FILE 或 --filelist 其中之一")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        try:
            glossary = api.load_glossary(args.glossary)
        except FileNotFoundError as e:
            print(f"md2zh: 错误: {e}", file=sys.stderr)
            return translator.EX_NOINPUT
        except ValueError as e:
            print(f"md2zh: 错误: {e}", file=sys.stderr)
            return translator.EX_DATAERR

        if args.filelist:
            try:
                paths = translator.parse_filelist(args.filelist)
            except OSError as e:
                print(f"md2zh: 错误: 无法读取文件列表 {args.filelist}: {e}", file=sys.stderr)
                return translator.EX_NOINPUT
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model)
        return translator.run_single(args.file, force=args.force, glossary=glossary,
                                     api_base=args.api_base, model=args.model)
    except KeyboardInterrupt:
        print("\nmd2zh: 已中断", file=sys.stderr)
        return translator.EX_SIGINT
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_cli.py -v`
Expected: `8 passed`

- [ ] **Step 5: 验证 console script 并提交**

```bash
md2zh --version   # Expected: md2zh 0.1.0
md2zh             # Expected: 用法提示到 stderr,退出码 64(用 echo $? 确认)
```

```bash
git add src/md2zh/cli.py tests/test_cli.py
git commit -m "feat: cli 模块实现参数解析与退出码映射

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: 样例数据、README 与手工验证(预计 40 分钟)

**Files:**
- Create: `data/sample_en.md`、`README.md`

**Interfaces:**
- Consumes: 全部模块(集成验证)

- [ ] **Step 1: 创建样例数据 data/sample_en.md**

```markdown
---
title: Sample Document
author: Tester
---

# Introduction

This is a **sample** document for [the translator](https://example.com).

## Table

| Name | Value |
|------|-------|
| Alpha | 10 |
| Beta | 20 |

## Code

```python
def hello():
    return "world"
```

Use `os.replace` for atomic writes.
```

- [ ] **Step 2: 创建 README.md**

```markdown
# md2zh

将英文 Markdown 文件翻译为中文的命令行工具,基于 Bilibili Index-Translate 免费翻译 API。
译文保存于原文件同目录,命名为 `*_zh.md`。

## 安装

```bash
python -m pip install -e ".[dev]"
```

## 用法

```bash
md2zh ABC.md                     # 翻译单个文件
md2zh --filelist list.txt        # 批量翻译(每行一个 md 文件,# 开头的行被忽略)
md2zh ABC.md --force             # 覆盖已存在的 ABC_zh.md
md2zh ABC.md --glossary g.json   # 指定术语表文件
```

术语表格式为 JSON:`{"英文术语": "中文译法"}`。未指定 `--glossary` 时自动加载
`~/.config/md2zh/glossary.json`(Windows 下为 `%USERPROFILE%\.config\md2zh\glossary.json`),
文件不存在则视为无术语表。

## 行为约定

- 代码块与行内代码不翻译(占位符保护,内容不会发送给 API);
- 译文格式与原文一致:frontmatter 的 key 与 `---` 标记不变、`**` 加黑成对、链接 url 不变、表格行列不变;
- 校验失败自动重译修复,重试耗尽后该块保留原文并输出警告;
- stdout 只输出成功生成的译文路径(每行一个);进度与警告输出到 stderr;
- 退出码:0 成功 / 1 存在失败(批量) / 64 用法错误 / 65 术语表格式错误或源文件非 UTF-8 / 66 输入不存在 / 74 写失败 / 75 API 不可用 / 130 中断。

## 开发

```bash
python -m pytest -v            # 运行全部测试(API 已 mock,不依赖网络)
```
```

- [ ] **Step 3: 运行完整测试套件并生成报告**

```bash
mkdir -p reports
python -m pytest -v --junitxml=reports/junit.xml
```

Expected: 全部通过(`76 passed`,以实际为准)。

- [ ] **Step 4: 真实 API 手工验证**

```bash
md2zh data/sample_en.md
```

检查 `data/sample_en_zh.md`:
1. frontmatter 为 `---` 包裹、key 仍为 `title`/`author`、value 为中文;
2. 代码块 `def hello(): return "world"` 与行内 `os.replace` 原样保留;
3. 表格仍是 2 列 3 行;
4. 链接 url 仍为 `https://example.com`,显示文本已译;
5. `**sample**` 加黑成对、包裹对应译文。

再验证批量与容错:

```bash
mkdir -p temp
printf '# 注释\n\ndata/sample_en.md\nmissing.md\n' > temp/list.txt
md2zh --filelist temp/list.txt; echo "退出码: $?"
```

Expected: 汇总显示成功 1、失败 1,退出码 1;`missing.md` 报"文件不存在"。

- [ ] **Step 5: 提交**

```bash
git add data/sample_en.md README.md
git commit -m "docs: 添加样例数据与 README

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

**验证后注意**:`data/sample_en_zh.md` 为真实 API 产物,若已生成,从 `data/` 中移走或删除,保持仓库只含样例英文原文(在提交前确认 `git status`)。

---

## Self-Review(计划自审记录)

- **规格覆盖**:规格 §4(结构)→ Task 1/11;§5(CLI 接口)→ Task 11;§6(管线:块解析/分段/修复循环/frontmatter)→ Task 2/3/4/9;§7(文件列表/容错)→ Task 10;§8(退出码)→ Task 8/10/11;§9(术语表)→ Task 6;§10(测试)→ 各任务;§11(常量)→ Task 8;§13(手工验证)→ Task 12。无缺口。
- **占位符扫描**:无 TBD/TODO;所有步骤含完整代码与命令。
- **类型一致性**:`split_frontmatter/protect_code_blocks/restore_code_blocks/chunk_text/check_*/load_glossary/build_prompt/build_frontmatter_prompt/translate_text/translate_file/run_single/run_batch/main` 的签名在各任务间一致;退出码常量统一出自 translator.py。
