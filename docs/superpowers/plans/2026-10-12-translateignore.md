# .translateignore 忽略列表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 md2zh 的 `--filelist` 批量模式增加 `.translateignore` 忽略列表支持:命中文件略过不翻译,汇总增加独立「忽略」计数。

**Architecture:** 新增纯模块 `src/md2zh/ignore.py`(解析 + 统一正则翻译的通配匹配);`cli.py` 在 filelist 分支自动读取当前工作目录的 `.translateignore` 并传入 `run_batch`;`run_batch` 循环内先查忽略再翻译。匹配语义与 ds-translator 对齐。

**Tech Stack:** Python ≥3.10(仅标准库,无新依赖),pytest。

**规格:** `docs/superpowers/specs/2026-10-12-translateignore-design.md`

## Global Constraints

- 严格 TDD:每个任务先写失败测试 → 运行确认 RED → 最小实现 → 运行确认 GREEN → 提交
- 源码 src/、测试 tests/、数据 data/、报告 reports/、临时 temp/
- 代码注释与用户可见输出一律中文;运行期依赖仅 requests,本特性不新增依赖
- 测试全部 mock、不依赖真实网络;完整测试命令 `python -m pytest -v`
- 提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- 真实翻译 API 不进自动化测试;`references/call_api.py` 不得修改
- 现有 88 项测试必须保持全绿(各任务收尾跑全量套件)

---

### Task 1: ignore.py — 解析与精确路径匹配

**Files:**
- Create: `src/md2zh/ignore.py`
- Test: `tests/test_ignore.py`

**Interfaces:**
- Consumes: 无(首个任务)
- Produces(后续任务依赖,签名不可变):
  - `load_ignore(path: str = ".translateignore") -> IgnoreMatcher` — 文件不存在返回空匹配器(静默)
  - `IgnoreMatcher.is_ignored(path: str) -> bool` — 命中任一规则返回 True
  - 模块内 `_norm(p: str) -> str`、`_is_glob(line: str) -> bool`

- [ ] **Step 1: 编写失败测试**

创建 `tests/test_ignore.py`:

```python
"""ignore 模块测试:解析与精确路径匹配。"""

from md2zh import ignore


def test_load_missing_returns_empty(tmp_path):
    m = ignore.load_ignore(str(tmp_path / "no.ti"))
    assert not m.is_ignored(str(tmp_path / "A.md"))


def test_load_skips_blank_and_comments(tmp_path):
    f = tmp_path / ".translateignore"
    f.write_text("# 注释\n\n  \nD:\\x\\a.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a.md")
    assert not m.is_ignored("D:\\x\\b.md")


def test_exact_match_normalized(tmp_path):
    # 大小写与分隔符形态归一:Windows 路径小写化,/ 与 \ 等价
    f = tmp_path / ".translateignore"
    f.write_text("D:\\X\\Sub\\A.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("d:/x/sub/a.md")


def test_exact_relative_entry_resolves_from_cwd(tmp_path, monkeypatch):
    # 相对条目按当前工作目录解析(与 cli 的 CWD 自动发现一致)
    monkeypatch.chdir(tmp_path)
    f = tmp_path / ".translateignore"
    f.write_text("docs\\a.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored(str(tmp_path / "docs" / "a.md"))
    assert not m.is_ignored(str(tmp_path / "docs" / "b.md"))


def test_load_default_cwd(tmp_path, monkeypatch):
    # 缺省路径 ".translateignore" 相对 CWD 打开
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".translateignore").write_text("D:\\x\\a.md\n", encoding="utf-8")
    m = ignore.load_ignore()
    assert m.is_ignored("D:\\x\\a.md")


def test_load_with_bom(tmp_path):
    # 带 BOM(Windows 记事本保存)首个条目不得被 ﻿ 污染
    f = tmp_path / ".translateignore"
    f.write_bytes("﻿D:\\x\\a.md\n".encode("utf-8"))
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a.md")
```

- [ ] **Step 2: 运行测试确认 RED**

运行:`python -m pytest tests/test_ignore.py -v`
期望:FAIL,错误为 `ModuleNotFoundError: No module named 'md2zh.ignore'`

- [ ] **Step 3: 最小实现**

创建 `src/md2zh/ignore.py`:

```python
"""忽略列表:解析 .translateignore,提供精确路径与通配模式匹配。"""

import os


def _norm(p: str) -> str:
    """路径归一化:绝对化、折叠、小写、分隔符统一为 /。"""
    return os.path.normcase(os.path.abspath(os.path.normpath(p))).replace("\\", "/")


def _is_glob(line: str) -> bool:
    """含 *、? 或成对 [] 视为通配模式,否则为精确路径。"""
    return "*" in line or "?" in line or ("[" in line and "]" in line)


class IgnoreMatcher:
    """.translateignore 匹配器。"""

    def __init__(self, exact: set[str], patterns: list[str]):
        self._exact = exact

    def is_ignored(self, path: str) -> bool:
        """命中任一忽略规则返回 True(通配模式在任务 2 接入)。"""
        return _norm(path) in self._exact


def load_ignore(path: str = ".translateignore") -> IgnoreMatcher:
    """读取忽略列表;文件不存在返回空匹配器。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return IgnoreMatcher(set(), [])
    exact: set[str] = set()
    patterns: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _is_glob(line):
            patterns.append(line)
        else:
            exact.add(_norm(line))
    return IgnoreMatcher(exact, patterns)
```

- [ ] **Step 4: 运行测试确认 GREEN**

运行:`python -m pytest tests/test_ignore.py -v && python -m pytest -v`
期望:PASS;全量 94 项(88 旧 + 6 新)全绿

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/ignore.py tests/test_ignore.py
git commit -m "feat: ignore 模块解析 .translateignore 精确路径

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: ignore.py — 通配模式匹配(统一正则翻译)

**Files:**
- Modify: `src/md2zh/ignore.py`(整体替换)
- Test: `tests/test_ignore.py`(追加)

**Interfaces:**
- Consumes: 任务 1 的 `load_ignore` / `IgnoreMatcher` / `_norm` / `_is_glob`
- Produces: 模块内 `_is_absolute_pattern(p: str) -> bool`、`_pattern_regex(pattern: str) -> str`;`IgnoreMatcher` 持有预编译正则列表

- [ ] **Step 1: 编写失败测试**

追加到 `tests/test_ignore.py` 末尾:

```python
def test_glob_double_star_recursive(tmp_path):
    # ** 跨段递归:任意层级下的 i18n 目录直接子文件
    f = tmp_path / ".translateignore"
    f.write_text("**\\i18n\\*\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\any\\deep\\i18n\\x.md")
    assert not m.is_ignored("D:\\any\\deep\\i18n\\sub\\x.md")  # 段内 * 不跨分隔符
    assert not m.is_ignored("D:\\any\\deep\\xi18n\\x.md")     # 段边界不过匹配


def test_glob_relative_right_aligned(tmp_path):
    # 相对模式从右侧匹配:任意前缀下的 docs 直接子文件
    f = tmp_path / ".translateignore"
    f.write_text("docs\\*.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\proj\\docs\\a.md")


def test_glob_relative_overmatch_known_limitation(tmp_path):
    # 规格 §11 固化的已知限制:无 ** 相对模式前缀 .* 可能过匹配段边界
    f = tmp_path / ".translateignore"
    f.write_text("docs\\a*.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\proj\\xdocs\\a.md")


def test_glob_question_and_class(tmp_path):
    f = tmp_path / ".translateignore"
    f.write_text("**\\v?.md\n**\\a[0-9].md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\v1.md")
    assert not m.is_ignored("D:\\x\\v12.md")
    assert m.is_ignored("D:\\x\\a7.md")
    assert not m.is_ignored("D:\\x\\a7x.md")


def test_glob_trailing_separator_direct_children(tmp_path):
    # 目录形式(尾部 \)追加段内 *:只匹配直接子文件,不递归
    f = tmp_path / ".translateignore"
    f.write_text("**\\reports\\\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\reports\\a.md")
    assert not m.is_ignored("D:\\x\\reports\\sub\\a.md")


def test_glob_absolute_pattern(tmp_path):
    # 绝对模式(盘符开头)不加右对齐前缀:锚定盘符
    f = tmp_path / ".translateignore"
    f.write_text("D:\\x\\**\\*.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a\\b.md")
    assert not m.is_ignored("D:\\y\\a\\b.md")


def test_unpaired_bracket_treated_literal(tmp_path):
    # 不成对 [ 不视为通配符,按精确路径处理
    f = tmp_path / ".translateignore"
    f.write_text("D:\\x\\a[b.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a[b.md")
```

- [ ] **Step 2: 运行测试确认 RED**

运行:`python -m pytest tests/test_ignore.py -v`
期望:FAIL,全部新测试断言失败(通配行当前不参与匹配)

- [ ] **Step 3: 实现通配匹配**

整体替换 `src/md2zh/ignore.py`:

```python
"""忽略列表:解析 .translateignore,提供精确路径与通配模式匹配。"""

import os
import re


def _norm(p: str) -> str:
    """路径归一化:绝对化、折叠、小写、分隔符统一为 /。"""
    return os.path.normcase(os.path.abspath(os.path.normpath(p))).replace("\\", "/")


def _is_glob(line: str) -> bool:
    """含 *、? 或成对 [] 视为通配模式,否则为精确路径。"""
    return "*" in line or "?" in line or ("[" in line and "]" in line)


def _is_absolute_pattern(p: str) -> bool:
    """归一化后的模式以盘符或 / 开头视为绝对,不加右对齐前缀。"""
    return p.startswith("/") or (len(p) >= 3 and p[1:3] == ":/")


def _pattern_regex(pattern: str) -> str:
    """通配模式转正则:** 跨段递归;段内 *、? 不跨分隔符;字符类原样保留。"""
    parts: list[str] = []
    for i, seg in enumerate(pattern.split("**")):
        if i > 0:
            parts.append(".*")
        out: list[str] = []
        j = 0
        while j < len(seg):
            ch = seg[j]
            if ch == "*":
                out.append("[^/]*")
                j += 1
            elif ch == "?":
                out.append("[^/]")
                j += 1
            elif ch == "[":
                end = seg.find("]", j + 1)
                if end == -1:  # 不成对的 [ 按字面处理
                    out.append(re.escape(ch))
                    j += 1
                else:
                    out.append(seg[j:end + 1])
                    j = end + 1
            else:
                out.append(re.escape(ch))
                j += 1
        parts.append("".join(out))
    return "".join(parts)


class IgnoreMatcher:
    """.translateignore 匹配器:精确路径集合 + 预编译通配正则。"""

    def __init__(self, exact: set[str], patterns: list[str]):
        self._exact = exact
        self._regexes = [
            re.compile(("" if _is_absolute_pattern(p) else ".*") + _pattern_regex(p))
            for p in patterns
        ]

    def is_ignored(self, path: str) -> bool:
        """命中任一忽略规则返回 True。"""
        norm = _norm(path)
        if norm in self._exact:
            return True
        return any(rx.fullmatch(norm) for rx in self._regexes)


def load_ignore(path: str = ".translateignore") -> IgnoreMatcher:
    """读取忽略列表;文件不存在返回空匹配器。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return IgnoreMatcher(set(), [])
    exact: set[str] = set()
    patterns: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _is_glob(line):
            p = os.path.normcase(line).replace("\\", "/")
            if p.endswith("/"):
                p += "*"  # 目录形式:追加段内 * 表示直接子文件
            patterns.append(p)
        else:
            exact.add(_norm(line))
    return IgnoreMatcher(exact, patterns)
```

- [ ] **Step 4: 运行测试确认 GREEN**

运行:`python -m pytest tests/test_ignore.py -v && python -m pytest -v`
期望:PASS;全量 101 项(94 旧 + 7 新)全绿

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/ignore.py tests/test_ignore.py
git commit -m "feat: ignore 模块支持 ** 与段内通配匹配

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: ignore.py — 编码回退与解码失败警告

**Files:**
- Modify: `src/md2zh/ignore.py`(仅 `load_ignore`)
- Test: `tests/test_ignore.py`(追加)

**Interfaces:**
- Consumes: 任务 2 的模块
- Produces: 完整的 `load_ignore`(UTF-8-sig → GBK → 警告 + 空表)

- [ ] **Step 1: 编写失败测试**

追加到 `tests/test_ignore.py` 末尾:

```python
def test_load_gbk_fallback(tmp_path):
    # 与 ds-translator 对齐:UTF-8 失败回退 GBK(中文 Windows 常见)
    f = tmp_path / ".translateignore"
    f.write_bytes("D:\\x\\文档.md\n".encode("gbk"))
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\文档.md")


def test_load_undecodable_warns_empty(tmp_path, capsys):
    # 两种编码都无法解码:警告后视为空表,不中断翻译
    f = tmp_path / ".translateignore"
    f.write_bytes(b"\xff\xff\xff")
    m = ignore.load_ignore(str(f))
    assert not m.is_ignored("D:\\x\\a.md")
    assert "md2zh: 警告" in capsys.readouterr().err


def test_bare_directory_line_matches_children(tmp_path):
    # 裁决:裸目录行(不含通配符)按"直接子文件"语义生效,不静默空转
    f = tmp_path / ".translateignore"
    f.write_text("reports\\\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\reports\\a.md")
    assert not m.is_ignored("D:\\x\\reports\\sub\\a.md")


def test_invalid_char_class_warns_and_skips(tmp_path, capsys):
    # 非法字符类按 §8 降级:警告并跳过该规则,其余规则继续生效
    f = tmp_path / ".translateignore"
    f.write_text("src\\a[z-a]*.md\nD:\\x\\b.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert not m.is_ignored("D:\\x\\src\\a1.md")
    assert m.is_ignored("D:\\x\\b.md")
    assert "md2zh: 警告" in capsys.readouterr().err


def test_unpaired_bracket_in_wildcard_pattern(tmp_path):
    # 通配模式内不成对 [ 按字面处理(补齐 _pattern_regex 该分支覆盖)
    f = tmp_path / ".translateignore"
    f.write_text("**\\a[bc.md\n", encoding="utf-8")
    m = ignore.load_ignore(str(f))
    assert m.is_ignored("D:\\x\\a[bc.md")
    assert not m.is_ignored("D:\\x\\ab.md")


def test_load_directory_warns_empty(tmp_path, capsys):
    # 忽略路径为目录等 OSError 场景:警告 + 空表(§8 降级)
    d = tmp_path / "asdir"
    d.mkdir()
    m = ignore.load_ignore(str(d))
    assert not m.is_ignored("D:\\x\\a.md")
    assert "md2zh: 警告" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试确认 RED**

运行:`python -m pytest tests/test_ignore.py -v`
期望:FAIL,GBK 文件抛出 UnicodeDecodeError(未捕获)

- [ ] **Step 3: 实现编码回退**

用以下内容整体替换 `load_ignore`;新增 `import sys` 到文件头部;并按文末说明替换 `IgnoreMatcher.__init__`:

```python
def load_ignore(path: str = ".translateignore") -> IgnoreMatcher:
    """读取忽略列表;文件不存在返回空匹配器;解码失败警告后视为空表。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return IgnoreMatcher(set(), [])
    except UnicodeDecodeError:
        # 与 ds-translator 对齐:UTF-8 失败回退 GBK
        try:
            with open(path, encoding="gbk") as f:
                lines = f.read().splitlines()
        except (UnicodeDecodeError, OSError) as e:
            return _warn_unreadable(path, e)
    except OSError as e:
        return _warn_unreadable(path, e)
    exact: set[str] = set()
    patterns: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(("/", "\\")):
            line += "*"  # 目录形式:先追加段内 * 再分类,裸目录行同样生效
        if _is_glob(line):
            patterns.append(os.path.normcase(line).replace("\\", "/"))
        else:
            exact.add(_norm(line))
    return IgnoreMatcher(exact, patterns)
```

文件头部 import 区改为:

```python
import os
import re
import sys
```

同时在 `load_ignore` 定义之前插入辅助函数:

```python
def _warn_unreadable(path: str, e: Exception) -> IgnoreMatcher:
    """忽略文件读取失败统一告警:返回空匹配器。"""
    sys.stderr.write(f"md2zh: 警告: 无法读取忽略文件 {path},不使用忽略规则: {e}\n")
    return IgnoreMatcher(set(), [])
```

同时将 `IgnoreMatcher.__init__`(第 18-20 行)替换为(模式构造在外、仅 `re.compile` 入 try,捕获非法模式时警告并跳过该规则):

```python
    def __init__(self, exact: set[str], patterns: list[str]):
        self._exact = exact
        regexes: list[re.Pattern] = []
        for p in patterns:
            pattern = ("" if _is_absolute_pattern(p) else ".*") + _pattern_regex(p)
            try:
                regexes.append(re.compile(pattern))
            except re.error as e:
                # 非法模式(如写错的字符类)按 §8 降级:警告并跳过该规则
                sys.stderr.write(f"md2zh: 警告: 忽略规则无效,已跳过: {p}: {e}\n")
        self._regexes = regexes
```

- [ ] **Step 4: 运行测试确认 GREEN**

运行:`python -m pytest tests/test_ignore.py -v && python -m pytest -v`
期望:PASS;全量 107 项(101 旧 + 6 新)全绿

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/ignore.py tests/test_ignore.py
git commit -m "feat: ignore 模块 UTF-8 回退 GBK 与解码失败警告

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: translator.py — run_batch 忽略接线与汇总

**Files:**
- Modify: `src/md2zh/translator.py`(import 区、`run_batch`)
- Test: `tests/test_translator.py`(追加)

**Interfaces:**
- Consumes: `ignore.IgnoreMatcher`、`ignore.load_ignore`(任务 1-3)
- Produces: `run_batch(paths, *, force, glossary, api_base, model, ignore_matcher: ignore.IgnoreMatcher | None = None) -> int`(关键字参数,缺省 None 表示不启用;忽略命中先于扩展名/存在性检查与 --force)

- [ ] **Step 1: 编写失败测试**

`tests/test_translator.py` 头部 import 区(第 4-5 行)改为:

```python
from md2zh import api
from md2zh import ignore
from md2zh import translator
```

追加到 `tests/test_translator.py` 末尾:

```python
def test_run_batch_ignored_files_skipped(monkeypatch, tmp_path, capsys):
    # 忽略命中:不调用翻译 API,计入「忽略」数
    good = tmp_path / "good.md"
    good.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(good) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "# 你好"

    monkeypatch.setattr(api, "translate_text", fake)
    rc = translator.run_batch([str(good)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert calls["n"] == 0
    captured = capsys.readouterr()
    assert "md2zh: 忽略 " in captured.err
    assert "成功 0" in captured.err


def test_run_batch_all_ignored_returns_0(tmp_path, capsys):
    # 全部被忽略 → 退出 0(符合"0 成功含全部跳过"契约)
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    rc = translator.run_batch([str(p)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert "汇总: 成功 0,跳过 0,忽略 1,失败 0" in capsys.readouterr().err


def test_run_batch_ignored_and_failed_returns_1(tmp_path, capsys):
    # 忽略与失败混合:忽略不算失败,存在失败仍退出 1
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    rc = translator.run_batch([str(p), str(tmp_path / "missing.md")], force=False,
                              glossary=[], api_base="http://x", model="m",
                              ignore_matcher=matcher)
    assert rc == translator.EX_PARTIAL
    assert "汇总: 成功 0,跳过 0,忽略 1,失败 1" in capsys.readouterr().err


def test_run_batch_ignore_wins_over_force(monkeypatch, tmp_path):
    # --force 不覆盖忽略:被忽略文件即使已有译文也不翻译
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    (tmp_path / "a_zh.md").write_text("已有", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return "# 你好"

    monkeypatch.setattr(api, "translate_text", fake)
    rc = translator.run_batch([str(p)], force=True, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert calls["n"] == 0
```

- [ ] **Step 2: 运行测试确认 RED**

运行:`python -m pytest tests/test_translator.py -v`
期望:FAIL,错误为 `TypeError: run_batch() got an unexpected keyword argument 'ignore_matcher'`

- [ ] **Step 3: 实现 run_batch 接线**

`src/md2zh/translator.py` 第 8 行 import 区改为:

```python
from md2zh import api, checks, ignore, markdown
```

`run_batch`(第 205-222 行)整体替换为:

```python
def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str,
              ignore_matcher: ignore.IgnoreMatcher | None = None) -> int:
    """批量模式:继续处理所有文件,最后汇总;存在失败返回 EX_PARTIAL。

    忽略列表命中优先于扩展名与存在性检查,且不受 --force 影响。
    """
    ok = skipped = ignored = failed = 0
    for p in paths:
        if ignore_matcher is not None and ignore_matcher.is_ignored(p):
            print(f"md2zh: 忽略 {p}: 命中忽略列表", file=sys.stderr)
            ignored += 1
            continue
        result = translate_file(p, force=force, glossary=glossary,
                                api_base=api_base, model=model)
        if result.status == "ok":
            print(result.detail, flush=True)
            ok += 1
        elif result.status == "skipped":
            print(f"md2zh: 跳过 {p}: {result.detail}", file=sys.stderr)
            skipped += 1
        else:
            print(f"md2zh: 失败 {p}: {result.detail}", file=sys.stderr)
            failed += 1
    print(f"md2zh: 汇总: 成功 {ok},跳过 {skipped},忽略 {ignored},失败 {failed}", file=sys.stderr)
    return EX_PARTIAL if failed else EX_OK
```

- [ ] **Step 4: 运行测试确认 GREEN**

运行:`python -m pytest tests/test_translator.py -v && python -m pytest -v`
期望:PASS;全量 111 项(107 旧 + 4 新)全绿(既有批量测试仅断言子串,不受汇总格式扩展影响)

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: run_batch 忽略接线与四类汇总计数

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: cli.py — 自动读取 CWD 的 .translateignore

**Files:**
- Modify: `src/md2zh/cli.py`(import 区、filelist 分支)
- Test: `tests/test_cli.py`(追加 3 项,加固 1 项既有测试)

**Interfaces:**
- Consumes: `ignore.load_ignore()`、`run_batch(..., ignore_matcher=...)`(任务 1-4)
- Produces: 端到端行为:filelist 模式自动读取 CWD 的 `.translateignore`,不存在则等效无规则

- [ ] **Step 1: 编写失败测试**

追加到 `tests/test_cli.py` 末尾:

```python
def test_filelist_ignores_translateignore(monkeypatch, tmp_path, capsys):
    # 端到端:--filelist 自动读取 CWD 的 .translateignore,命中文件略过
    monkeypatch.chdir(tmp_path)
    kept = tmp_path / "keep.md"
    kept.write_text("# Hi", encoding="utf-8")
    skipped = tmp_path / "skip.md"
    skipped.write_text("# Hi", encoding="utf-8")
    (tmp_path / ".translateignore").write_text(str(skipped) + "\n", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(f"{kept}\n{skipped}\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    captured = capsys.readouterr()
    assert "md2zh: 忽略 " in captured.err
    assert "汇总: 成功 1,跳过 0,忽略 1,失败 0" in captured.err
    assert (tmp_path / "keep_zh.md").exists()
    assert not (tmp_path / "skip_zh.md").exists()


def test_filelist_no_ignore_file(monkeypatch, tmp_path, capsys):
    # 无 .translateignore 时行为不变:全部翻译,无「忽略」提示
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(str(src) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    captured = capsys.readouterr()
    assert "md2zh: 忽略" not in captured.err
    assert "汇总: 成功 1,跳过 0,忽略 0,失败 0" in captured.err


def test_filelist_ignore_gbk(monkeypatch, tmp_path, capsys):
    # GBK 编码的忽略文件可用(与 ds-translator 对齐);混入非 ASCII 注释强制走 GBK 回退分支
    monkeypatch.chdir(tmp_path)
    skipped = tmp_path / "skip.md"
    skipped.write_text("# Hi", encoding="utf-8")
    (tmp_path / ".translateignore").write_bytes(("# 注释:文档\n" + str(skipped) + "\n").encode("gbk"))
    lst = tmp_path / "list.txt"
    lst.write_text(str(skipped) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    assert "忽略 1" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试确认 RED**

运行:`python -m pytest tests/test_cli.py -v`
期望:FAIL,新测试断言失败(`skip_zh.md` 被生成、err 无「忽略」提示)

- [ ] **Step 3: 实现 cli 接线**

`src/md2zh/cli.py` 第 8-9 行 import 区改为:

```python
from md2zh import __version__, api, ignore
from md2zh import translator
```

filelist 分支(第 72-83 行)中,以下旧代码:

```python
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model)
```

改为:

```python
            matcher = ignore.load_ignore()  # 自动读取当前目录 .translateignore
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        ignore_matcher=matcher)
```

同时加固既有测试 `test_filelist_mode`(第 54-61 行),在函数体首行加入 CWD 隔离,防止项目根目录的真实 `.translateignore` 干扰测试:

```python
def test_filelist_mode(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)  # 隔离 CWD,避免加载项目根目录真实 .translateignore
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    lst = tmp_path / "list.txt"
    lst.write_text(str(src) + "\n", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main(["--filelist", str(lst)]) == translator.EX_OK
    assert str(tmp_path / "A_zh.md") in capsys.readouterr().out
```

- [ ] **Step 4: 运行测试确认 GREEN**

运行:`python -m pytest tests/test_cli.py -v && python -m pytest -v`
期望:PASS;全量 114 项(111 旧 + 3 新)全绿

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/cli.py tests/test_cli.py
git commit -m "feat: cli 自动读取 .translateignore 并接入批量模式

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 版本 0.2.0 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`、`pyproject.toml`、`tests/test_version.py`、`CHANGELOG.md`、`README.md`、`CLAUDE.md`、`.gitignore`

**Interfaces:**
- Consumes: 任务 1-5 全部产物
- Produces: 版本号 0.2.0;README/CLAUDE.md/CHANGELOG 反映忽略列表功能;`.translateignore` 入 .gitignore(用户本地文件不入库)

- [ ] **Step 1: 版本号测试先行(RED)**

`tests/test_version.py` 第 5 行改为:

```python
    assert __version__ == "0.2.0"
```

运行:`python -m pytest tests/test_version.py -v`
期望:FAIL,`AssertionError: assert '0.1.0' == '0.2.0'`

- [ ] **Step 2: 提升版本号(GREEN)**

`src/md2zh/__init__.py` 第 3 行改为:

```python
__version__ = "0.2.0"
```

`pyproject.toml` 第 7 行改为:

```toml
version = "0.2.0"
```

运行:`python -m pytest tests/test_version.py -v`
期望:PASS

- [ ] **Step 3: CHANGELOG 0.2.0 条目**

`CHANGELOG.md` 中 `## [Unreleased]`(第 8 行)改为 `## [0.2.0] - 2026-10-12`;在「### 新增」末尾追加一行:

```markdown
- `--filelist` 批量模式自动读取当前目录 `.translateignore`,命中文件略过不翻译(精确路径 + 通配模式)
```

在「### 变更」末尾追加一行:

```markdown
- 批量汇总增加「忽略」计数,格式为 成功/跳过/忽略/失败
```

- [ ] **Step 4: README 同步**

1. 徽章行(第 6-7 行):

```markdown
![Version](https://img.shields.io/badge/version-0.2.0-brightgreen)
![Tests](https://img.shields.io/badge/tests-114%20passed-brightgreen)
```

2. 目录(第 17 行后)追加一行:

```markdown
- [忽略列表](#忽略列表)
```

3. 特性区(第 32 行后)追加一条:

```markdown
- 🚫 **忽略列表**:`--filelist` 批量模式自动读取当前目录 `.translateignore`(精确路径 + 通配模式),命中文件略过不翻译
```

4. 快速开始示例(第 53 行 `md2zh --filelist list.txt` 之后)追加一行:

```bash
# .translateignore 中列出的文件在批量模式下略过(每行一个路径或通配模式,# 注释)
```

5. 批量汇总描述(第 65 行)`成功 N,跳过 M,失败 K` 改为 `成功 N,跳过 M,忽略 L,失败 K`

6. 「## 术语表」节(第 104 行 `- 优先级:命令行 `--glossary` > 默认文件。` 之后、`## 翻译 API 说明` 之前)插入新节:

```markdown
## 忽略列表

`--filelist` 批量模式下自动读取当前目录的 `.translateignore`(文件不存在则视为无规则),每行一条规则:

- 精确路径(相对路径按当前目录解析),或通配模式:`**` 匹配任意层级、`*`/`?` 匹配路径段内字符、`[...]` 字符类;
- `#` 开头的行与空行被忽略;以 `\` 结尾的模式匹配目录直接子文件;
- 编码须为 UTF-8(GBK 亦可);命中文件计入汇总的「忽略」数,不算失败。
```

7. 行为约定 stdout 一条(第 74 行)`进度、跳过提示、警告、汇总全部走 stderr` 改为 `进度、跳过/忽略提示、警告、汇总全部走 stderr`

8. 开发节测试计数(第 123、137 行)`88 项` 改为 `114 项`;项目结构树(第 135-136 行)第二行注释改为:

```
├── src/md2zh/          # cli(参数与退出码) / api(请求与提示词) / markdown(块解析)
│                       # checks(格式校验) / translator(编排与批量) / ignore(忽略列表)
```

9. 已知限制区(第 148 行后)追加一条:

```markdown
- 忽略列表通配匹配:`**` 与段内 `*` 语义同 gitignore 子集;无 `**` 的相对模式可能轻微过匹配段边界(如 `docs/a*.md` 会命中 `xdocs/a.md`),损害有界(多跳过可在 stderr 审计);
```

- [ ] **Step 5: CLAUDE.md 同步**

1. 「## Architecture」`五模块分层(职责边界严格,不跨层):` 改为 `六模块分层(职责边界严格,不跨层):`;在 `checks.py` 条目后追加一行:

```markdown
- `ignore.py` — 忽略列表解析与通配匹配(精确路径 + `**`/段内通配,UTF-8-sig→GBK 回退)
```

2. 「**核心设计决策:**」列表在术语表条目后追加一行:

```markdown
- **忽略列表**:`--filelist` 批量模式自动读取当前目录 `.translateignore`(不存在视为无规则);命中文件略过不翻译(忽略优先于扩展名/存在性检查与 `--force`),计入汇总「忽略」数
```

3. 「**流约定:**」一行中 `进度、跳过提示、警告、汇总全部走 stderr` 改为 `进度、跳过/忽略提示、警告、汇总全部走 stderr`

4. 「## File Structure」`# 五模块实现(__init__.py 存版本号)` 改为 `# 六模块实现(__init__.py 存版本号)`

5. 「## Development Workflow」测试行 `(88 项,API 全部 mock,不依赖真实网络)` 改为 `(114 项,API 全部 mock,不依赖真实网络)`

- [ ] **Step 6: .gitignore 追加**

`.gitignore` 末尾追加一行:

```
.translateignore
```

- [ ] **Step 7: 全量测试**

运行:`python -m pytest -v`
期望:114 项全绿

- [ ] **Step 8: 提交**

```bash
git add src/md2zh/__init__.py pyproject.toml tests/test_version.py CHANGELOG.md README.md CLAUDE.md .gitignore
git commit -m "docs: 0.2.0 版本号与忽略列表文档同步

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

- [ ] **Step 9: CLAUDE.md Recent Updates 补记(依据实际提交哈希)**

运行:`git log --format="%h %s" -n 8`
随后在 CLAUDE.md 「## Recent Updates」节首追加一条(格式仿照既有条目,日期与哈希取自上方命令输出,任务提交范围为任务 1 至任务 6 的首尾哈希):

```markdown
v0.2.0 忽略列表功能:<首哈希>..<尾哈希> 六个任务全部落地,110/110 测试通过。--filelist 批量模式自动读取当前目录 .translateignore(精确路径 + **/段内通配,UTF-8-sig→GBK 回退),命中文件略过并计入「忽略」汇总。
```

追加后单独提交:

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 补记 v0.2.0 忽略列表功能

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 自检记录

- 规格覆盖:§2 范围(Task 4/5,单文件与 stdin 未触碰)、§5 解析(Task 1/3)、§6 匹配(Task 2)、§7 接线统计(Task 4/5)、§8 错误处理(Task 3)、§9 测试(Task 1-5)、§10 文档版本(Task 6)、§11 已知限制(Task 2 固化过匹配用例);
- 类型一致性:`load_ignore(path: str = ".translateignore") -> IgnoreMatcher`、`is_ignored(path: str) -> bool`、`run_batch(..., ignore_matcher: ignore.IgnoreMatcher | None = None)` 各任务间签名一致;
- 测试计数:88 → 94(任务 1)→ 101(任务 2)→ 107(任务 3,含审查修复)→ 111(任务 4)→ 114(任务 5),任务 6 维持 114。
