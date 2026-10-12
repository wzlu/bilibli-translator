# filelist 多线程批量翻译 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `md2zh --filelist` 批量模式增加线程池并行翻译,最大线程数由 `-c/--max-threads` 指定(默认 10)。

**Architecture:** `run_batch` 用 `ThreadPoolExecutor` 并行提交 `translate_file`,主线程经 `as_completed` 乱序输出结果并聚合计数;忽略命中文件在主线程前置处理;线程内 stderr 警告经模块级锁串行化。单文件/stdin 路径零改动。

**Tech Stack:** Python ≥ 3.10 标准库(`argparse`、`concurrent.futures`、`threading`),运行期依赖仍仅 `requests`。

**规格:** `docs/superpowers/specs/2026-10-13-filelist-multithreading-design.md`

## Global Constraints

- Python ≥ 3.10;运行期依赖仅 `requests`,**不新增任何依赖**
- 严格 TDD:先写失败测试 → 确认 RED → 最小实现 → 确认 GREEN → 提交
- 测试命令 `python -m pytest -v`(全量,API 全部 mock);报告 `python -m pytest -v --junitxml=reports/junit.xml`
- 退出码契约不变:0 成功 / 1 批量部分失败 / 64 用法错误 / 65 数据错误 / 66 输入不存在 / 74 写失败 / 75 API 临时不可用 / 130 SIGINT / 141 SIGPIPE
- stdout 只输出数据(批量模式输出译文路径,每行一个);进度、跳过/忽略提示、警告、汇总全部走 stderr;错误消息 GNU 格式 `md2zh: 上下文: 信息`
- 代码注释与用户可见输出一律中文;提交信息末尾附 `Co-Authored-By: Claude Code <noreply@anthropic.com>`
- 目录规则:源码 `src/`、测试 `tests/`、临时文件 `temp/`、报告 `reports/`
- `references/call_api.py` 不得修改
- 基线 129 项测试全绿,每任务结束必须全量 GREEN 且无回归
- 每个任务独立提交(一个逻辑变更一个 commit)

---

### Task 1: CLI 选项 `-c/--max-threads`

**Files:**
- Modify: `src/md2zh/cli.py:28-56`(parse_args 新增选项与校验、epilog 示例)
- Modify: `src/md2zh/cli.py:86-89`(main 批量分支透传)
- Modify: `src/md2zh/translator.py:224-226`(run_batch 签名新增 `max_threads` 形参,本任务暂不使用)
- Test: `tests/test_cli.py`(文件末尾追加 5 个测试)

**Interfaces:**
- Consumes: `translator.run_batch(paths, *, force, glossary, api_base, model, repair, ignore_matcher)`(现行签名)
- Produces: `run_batch(..., max_threads: int = 10)`;`args.max_threads`(int,默认 10,已校验 ≥1)

- [ ] **Step 1: 写失败测试**

在 `tests/test_cli.py` 末尾追加:

```python
def test_max_threads_default_10(monkeypatch, tmp_path):
    # 缺省 -c 10 透传到 run_batch
    seen: dict = {}

    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads):
        seen["max_threads"] = max_threads
        return translator.EX_OK

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(translator, "parse_filelist", lambda p: ["a.md"])
    monkeypatch.setattr(translator, "run_batch", fake_run_batch)
    monkeypatch.setattr(ignore, "load_ignore", lambda *a, **k: None)
    assert cli.main(["--filelist", "l.txt"]) == translator.EX_OK
    assert seen["max_threads"] == 10


def test_max_threads_flag_passthrough(monkeypatch, tmp_path):
    # -c 5 透传到 run_batch
    seen: dict = {}

    def fake_run_batch(paths, *, force, glossary, api_base, model, repair,
                       ignore_matcher, max_threads):
        seen["max_threads"] = max_threads
        return translator.EX_OK

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(translator, "parse_filelist", lambda p: ["a.md"])
    monkeypatch.setattr(translator, "run_batch", fake_run_batch)
    monkeypatch.setattr(ignore, "load_ignore", lambda *a, **k: None)
    assert cli.main(["--filelist", "l.txt", "-c", "5"]) == translator.EX_OK
    assert seen["max_threads"] == 5


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_max_threads_invalid_exits_64(bad, capsys):
    # 非正整数按用法错误退出 64
    with pytest.raises(SystemExit) as e:
        cli.main(["--filelist", "l.txt", "-c", bad])
    assert e.value.code == translator.EX_USAGE
    assert "-c/--max-threads 必须是正整数" in capsys.readouterr().err


def test_max_threads_ignored_in_single_file_mode(monkeypatch, tmp_path):
    # 单文件模式下 -c 被接受且不影响行为(静默忽略)
    src = tmp_path / "A.md"
    src.write_text("# Hi", encoding="utf-8")
    monkeypatch.setattr(api, "load_glossary", lambda *a, **k: [])
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    assert cli.main([str(src), "-c", "5"]) == translator.EX_OK
    assert (tmp_path / "A_zh.md").exists()


def test_help_contains_max_threads(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    assert "-c N, --max-threads N" in capsys.readouterr().out
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_cli.py -k max_threads -v`

Expected: FAIL——`test_max_threads_default_10`/`test_max_threads_flag_passthrough` 报 `TypeError: fake_run_batch() missing 1 required keyword-only argument: 'max_threads'`;`test_max_threads_invalid_exits_64` 报 `SystemExit`(未知选项 -c,`assert e.value.code == translator.EX_USAGE` 通过但错误消息断言失败);`test_max_threads_ignored_in_single_file_mode` 抛 `SystemExit`(未知选项);`test_help_contains_max_threads` 断言失败(帮助无此选项)。

- [ ] **Step 3: 最小实现**

`src/md2zh/cli.py` 三处修改:

(1) `parse_args` 在 `--repair` 之后、`--version` 之前新增选项:

```python
    parser.add_argument("-c", "--max-threads", type=int, default=10, metavar="N",
                        help="--filelist 模式最大并发线程数(默认 10;仅批量模式生效)")
```

(2) `parse_args` 末尾(`return args` 之前)新增校验:

```python
    if args.max_threads < 1:
        parser.error("-c/--max-threads 必须是正整数")
```

(3) `main` 批量分支透传(`cli.py:87-89` 改为):

```python
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        ignore_matcher=matcher, repair=args.repair,
                                        max_threads=args.max_threads)
```

(4) epilog 在 `--filelist` 示例行之后插入一行:

```python
        "  md2zh --filelist list.txt -c 5     批量翻译,最多 5 个线程并行(默认 10)\n"
```

`src/md2zh/translator.py` 签名修改(`run_batch` 增加形参,本任务暂不使用;Task 2 重写函数体):

```python
def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str, repair: int = 0,
              ignore_matcher: ignore.IgnoreMatcher | None = None,
              max_threads: int = 10) -> int:
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest -v`

Expected: 全部 PASS(129 旧 + 6 新 = 135 项;`test_max_threads_invalid_exits_64` 参数化为 2 项)。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/cli.py src/md2zh/translator.py tests/test_cli.py
git commit -m "feat: 新增 -c/--max-threads 选项(默认 10),CLI 透传至 run_batch

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: run_batch 线程池并发化

**Files:**
- Modify: `src/md2zh/translator.py:3-9`(import 区)、`src/md2zh/translator.py:224-249`(run_batch 函数体整体替换)
- Test: `tests/test_translator.py`(文件头部 import 区、末尾追加 7 个测试)

**Interfaces:**
- Consumes: Task 1 的 `run_batch(..., max_threads: int = 10)` 签名;`TranslateResult(status: str, detail: str = "", exit_code: int = 0)`;`EX_OK`/`EX_PARTIAL` 常量
- Produces: 线程池并行翻译、乱序输出、忽略前置、未知异常兜底、KeyboardInterrupt 不等待关停

- [ ] **Step 1: 写失败测试**

`tests/test_translator.py` 头部 import 区(第 1-6 行)追加:

```python
import threading
import time

import pytest
```

文件末尾追加:

```python
def test_run_batch_parallel_submits_all(monkeypatch, capsys):
    # 三个文件的门闩全部到达后才放行:证明并发提交(顺序版会卡在第一个门闩上)
    started: list[str] = []
    gate = threading.Event()

    def fake(src_path, *, force, glossary, api_base, model, repair):
        started.append(src_path)
        gate.wait()
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    paths = ["f0.md", "f1.md", "f2.md"]
    out: dict[str, int] = {}

    def run():
        out["rc"] = translator.run_batch(paths, force=False, glossary=[],
                                         api_base="http://x", model="m", max_threads=3)

    t = threading.Thread(target=run)
    t.start()
    try:
        deadline = time.time() + 5
        while len(started) < 3 and time.time() < deadline:
            time.sleep(0.01)
        assert len(started) == 3, "线程池未同时启动全部任务"
    finally:
        gate.set()  # 无论断言成败都放行,避免后台线程悬挂
    t.join(10)
    assert not t.is_alive()
    assert out["rc"] == translator.EX_OK
    assert set(capsys.readouterr().out.splitlines()) == {"f0.md_zh", "f1.md_zh", "f2.md_zh"}


def test_run_batch_completed_first_printed_first(monkeypatch, capsys):
    # 慢文件先提交、快文件后提交:完成即输出,快文件路径先出现(乱序)
    def fake(src_path, *, force, glossary, api_base, model, repair):
        time.sleep(0.5 if src_path.endswith("slow.md") else 0.05)
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch(["slow.md", "fast.md"], force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=2)
    assert rc == translator.EX_OK
    assert capsys.readouterr().out.splitlines() == ["fast.md_zh", "slow.md_zh"]


def test_run_batch_ignored_not_submitted(monkeypatch, tmp_path, capsys):
    # 忽略命中的文件不进入线程池(顺序版语义保留)
    def fake(src_path, **k):
        raise AssertionError(f"忽略文件不应提交翻译: {src_path}")

    monkeypatch.setattr(translator, "translate_file", fake)
    p = tmp_path / "a.md"
    p.write_text("# Hi", encoding="utf-8")
    ti = tmp_path / ".translateignore"
    ti.write_text(str(p) + "\n", encoding="utf-8")
    matcher = ignore.load_ignore(str(ti))
    rc = translator.run_batch([str(p)], force=False, glossary=[],
                              api_base="http://x", model="m", ignore_matcher=matcher)
    assert rc == translator.EX_OK
    assert "汇总: 成功 0,跳过 0,忽略 1,失败 0" in capsys.readouterr().err


def test_run_batch_unexpected_error_continues(monkeypatch, capsys):
    # 未知异常兜底:计入失败并继续处理其余文件
    def fake(src_path, *, force, glossary, api_base, model, repair):
        if src_path == "bad.md":
            raise RuntimeError("模拟未知回归")
        return translator.TranslateResult("ok", src_path + "_zh")

    monkeypatch.setattr(translator, "translate_file", fake)
    rc = translator.run_batch(["bad.md", "good.md"], force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=2)
    assert rc == translator.EX_PARTIAL
    err = capsys.readouterr().err
    assert "失败 bad.md" in err
    assert "汇总: 成功 1,跳过 0,忽略 0,失败 1" in err


def test_run_batch_keyboard_interrupt_reraises(monkeypatch):
    # 中断从 fut.result() 传出后经外层 shutdown 不等待关停并重新抛出
    def fake(src_path, *, force, glossary, api_base, model, repair):
        raise KeyboardInterrupt

    monkeypatch.setattr(translator, "translate_file", fake)
    with pytest.raises(KeyboardInterrupt):
        translator.run_batch(["a.md"], force=False, glossary=[],
                             api_base="http://x", model="m", max_threads=1)


def test_run_batch_max_threads_one_matches_sequential(monkeypatch, tmp_path, capsys):
    # max_threads=1 与顺序版行为一致(回归对照)
    good = tmp_path / "good.md"
    good.write_text("# Hello", encoding="utf-8")
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    paths = [str(tmp_path / "missing.md"), str(good)]
    rc = translator.run_batch(paths, force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=1)
    assert rc == translator.EX_PARTIAL
    captured = capsys.readouterr()
    assert "成功 1" in captured.err
    assert "失败 1" in captured.err
    assert str(good)[:-3] + "_zh.md" in captured.out


def test_run_batch_threads_write_zh_files(monkeypatch, tmp_path):
    # 真实线程小规模集成:多线程并行写盘,全部译文生成且内容正确
    files = []
    for name in ("a.md", "b.md", "c.md"):
        p = tmp_path / name
        p.write_text("# Hi", encoding="utf-8")
        files.append(str(p))
    monkeypatch.setattr(api, "translate_text", lambda *a, **k: "# 你好")
    rc = translator.run_batch(files, force=False, glossary=[],
                              api_base="http://x", model="m", max_threads=4)
    assert rc == translator.EX_OK
    for p in files:
        zh = p[:-3] + "_zh.md"
        assert os.path.exists(zh)
        with open(zh, encoding="utf-8") as f:
            assert "# 你好" in f.read()
```

注意:文件顶部需补充 `import os`(现仅 import io、sys);如已有则跳过。

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py -k "run_batch" -v`

Expected: 新测试 FAIL——`test_run_batch_parallel_submits_all` 等待约 5 秒后断言 `len(started) == 3` 失败(顺序版只启动 1 个);`test_run_batch_completed_first_printed_first` 输出顺序为 slow 在前,断言失败;`test_run_batch_unexpected_error_continues` 抛 `RuntimeError`(未捕获)导致 error;`test_run_batch_max_threads_one_matches_sequential` 与 `test_run_batch_threads_write_zh_files` 报 `TypeError: run_batch() got an unexpected keyword argument 'max_threads'`。旧批量测试(partial_success、all_ok、ignored 系列)保持 PASS。注意 `test_run_batch_ignored_not_submitted` 与 `test_run_batch_keyboard_interrupt_reraises` 在顺序版下即已 PASS——它们是守卫测试,非 RED 驱动。

- [ ] **Step 3: 最小实现**

(1) `src/md2zh/translator.py` import 区(`import tempfile` 之后)新增:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

(2) `run_batch` 函数体整体替换(`translator.py:224-249`):

```python
def run_batch(paths: list[str], *, force: bool, glossary: list[str],
              api_base: str, model: str, repair: int = 0,
              ignore_matcher: ignore.IgnoreMatcher | None = None,
              max_threads: int = 10) -> int:
    """批量模式:线程池并行翻译,主线程乱序输出并汇总;存在失败返回 EX_PARTIAL。

    忽略列表命中优先于扩展名与存在性检查,且不受 --force 影响;
    命中文件在主线程前置处理,不提交线程池。
    """
    ok = skipped = ignored = failed = 0
    todo: list[str] = []
    for p in paths:
        if ignore_matcher is not None and ignore_matcher.is_ignored(p):
            print(f"md2zh: 忽略 {p}: 命中忽略列表", file=sys.stderr)
            ignored += 1
        else:
            todo.append(p)
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        try:
            futures = {executor.submit(translate_file, p, force=force, glossary=glossary,
                                       api_base=api_base, model=model, repair=repair): p
                       for p in todo}
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    # 未知回归兜底:单文件异常不拖垮批量,计入失败继续;
                    # KeyboardInterrupt 是 BaseException,不在此列,走外层处理
                    print(f"md2zh: 失败 {p}: {e}", file=sys.stderr)
                    failed += 1
                    continue
                if result.status == "ok":
                    print(result.detail, flush=True)
                    ok += 1
                elif result.status == "skipped":
                    print(f"md2zh: 跳过 {p}: {result.detail}", file=sys.stderr)
                    skipped += 1
                else:
                    print(f"md2zh: 失败 {p}: {result.detail}", file=sys.stderr)
                    failed += 1
        except KeyboardInterrupt:
            # 取消未启动任务、不等待运行中任务;cli.main 捕获后返回 130
            executor.shutdown(wait=False, cancel_futures=True)
            raise
    print(f"md2zh: 汇总: 成功 {ok},跳过 {skipped},忽略 {ignored},失败 {failed}",
          file=sys.stderr)
    return EX_PARTIAL if failed else EX_OK
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest -v`

Expected: 全部 PASS(135 + 7 = 142 项)。旧批量测试改走线程路径,断言仅用 `in` 匹配,不受输出乱序影响。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: run_batch 线程池并行翻译(完成即输出,忽略前置,异常兜底)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: stderr 写入互斥(_warn + 模块级锁)

**Files:**
- Modify: `src/md2zh/translator.py:3-9`(import threading)、常量区之后(`_warn` 与 `_stderr_lock`)、`_repair` 内 3 处 `sys.stderr.write`(translator.py:142、144、146)
- Test: `tests/test_translator.py`(末尾追加 1 个测试)

**Interfaces:**
- Consumes: 既有 `_repair(make_prompt, check, *, api_base, model, max_tokens, label, source, retries)`
- Produces: `_warn(message: str) -> None`(模块私有,stderr 串行化输出)

- [ ] **Step 1: 写失败测试**

`tests/test_translator.py` 末尾追加:

```python
def test_warn_writes_message(capsys):
    # _warn 串行化 stderr 写入;锁行为难以直接断言,此处钉住消息格式
    translator._warn("md2zh: 警告: 测试警告")
    assert "md2zh: 警告: 测试警告" in capsys.readouterr().err
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `python -m pytest tests/test_translator.py::test_warn_writes_message -v`

Expected: FAIL with `AttributeError: module 'md2zh.translator' has no attribute '_warn'`

- [ ] **Step 3: 最小实现**

(1) `translator.py` import 区新增:

```python
import threading
```

(2) 翻译策略常量区之后、`TranslateResult` 之前插入:

```python
_stderr_lock = threading.Lock()


def _warn(message: str) -> None:
    """stderr 警告串行化:批量多线程下避免行间交错。"""
    with _stderr_lock:
        print(message, file=sys.stderr)
```

(3) `_repair` 内 3 处 `sys.stderr.write(f"...\n")` 改为 `_warn(f"...")`(去掉行尾 `\n`,print 自带换行;消息文本与「md2zh: 警告: 」前缀原样保留):

```python
        if attempt < retries:
            _warn(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{retries}): {';'.join(problems)}")
    if retries:
        _warn(f"md2zh: 警告: {prefix}{label}重译耗尽,采用译文: {';'.join(problems)}")
    else:
        _warn(f"md2zh: 警告: {prefix}{label}校验失败,采用译文: {';'.join(problems)}")
```

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `python -m pytest -v`

Expected: 全部 PASS(142 + 1 = 143 项)。既有警告测试(`test_chunk_repair_warning_*`、`test_translate_file_warning_names_path` 等)断言消息文本不变,须原样通过。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/translator.py tests/test_translator.py
git commit -m "feat: 线程内 stderr 警告经模块级锁串行化(_warn)

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 版本号 0.4.0 与文档同步

**Files:**
- Modify: `src/md2zh/__init__.py`(第 3 行)、`pyproject.toml`(第 7 行)、`tests/test_version.py`
- Modify: `README.md`(快速开始示例、行为约定)、`CHANGELOG.md`(新增 0.4.0 节)、`CLAUDE.md`(Overview 版本、CLI 接口、核心设计决策、Recent Updates、测试数)
- Modify: `docs/superpowers/specs/2026-10-12-md2zh-translator-design.md`(§13 手工验证清单追加批量并发项)

**Interfaces:**
- Consumes: 无(纯文档与版本元数据)
- Produces: `__version__ == "0.4.0"`

- [ ] **Step 1: 写失败测试(版本)**

`tests/test_version.py` 改为:

```python
from md2zh import __version__


def test_version_exists():
    assert __version__ == "0.4.0"
```

Run: `python -m pytest tests/test_version.py -v`

Expected: FAIL with `AssertionError: assert '0.3.0' == '0.4.0'`

- [ ] **Step 2: 最小实现(版本)**

`src/md2zh/__init__.py` 第 3 行改为 `__version__ = "0.4.0"`;`pyproject.toml` 第 7 行改为 `version = "0.4.0"`。

Run: `python -m pytest tests/test_version.py -v`

Expected: PASS

- [ ] **Step 3: 文档同步**

**README.md:**
- 快速开始代码块中 `--filelist list.txt` 示例之后(第 57-58 行 `.translateignore` 注释行之后)插入:

```
# 批量翻译,最多 5 个线程并行(默认 10;完成即输出,顺序不定)
md2zh --filelist list.txt -c 5
```

- 「行为约定」列表(第 79-84 行)追加一条:

```
- `--filelist` 批量模式多线程并行(默认最多 10,可用 `-c N` 调整),译文路径完成即输出(顺序不定);
```

**CHANGELOG.md:** 在「格式基于…」说明之后、`## [0.3.0]` 之前插入:

```markdown
## [0.4.0] - 2026-10-13

### 新增

- `-c N, --max-threads N`:`--filelist` 批量模式最大并发线程数(默认 10,仅批量模式生效);译文路径完成即输出(乱序),汇总与退出码契约不变
```

**CLAUDE.md**(四处):
- Overview 首段「当前版本 0.3.0」→「当前版本 0.4.0」;
- CLI 接口代码块中 `--filelist LIST` 行之后加一行:

```
  -c/--max-threads N --filelist 模式最大线程数(默认 10;仅批量生效)
```

- 「核心设计决策」列表追加:

```
- **批量多线程**:--filelist 用 ThreadPoolExecutor(默认 10,可 -c 调整)并行翻译,忽略命中前置不提交,完成即输出(乱序),计数与汇总在主线程聚合;线程内 stderr 警告经模块级锁串行化
```

- 「Recent Updates」标题下插入 v0.4.0 条目(形式仿 v0.3.0 条目,内容:CLI 新增 -c/--max-threads,run_batch 线程池化、完成即输出、忽略前置、未知异常兜底、stderr 锁;测试数按 pytest 实际输出更新为 143);Overview 与「Development Workflow」中「129 项」同步为 143 项。

**docs/superpowers/specs/2026-10-12-md2zh-translator-design.md** §13 手工验证清单追加一条:

```
- 批量并发:md2zh --filelist data/untranslated_filelist.txt -c 5,观察多线程并行与乱序输出、汇总计数正确、退出码契约不变
```

- [ ] **Step 4: 全量验证**

Run: `python -m pytest -v --junitxml=reports/junit.xml`

Expected: 143/143 全部 PASS,`reports/junit.xml` 生成。

- [ ] **Step 5: 提交**

```bash
git add src/md2zh/__init__.py pyproject.toml tests/test_version.py README.md CHANGELOG.md CLAUDE.md docs/superpowers/specs/2026-10-12-md2zh-translator-design.md
git commit -m "chore: 版本提升 0.4.0,文档同步批量多线程功能

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## 自审记录

- **规格覆盖**:规格 §2 需求 1-7 分别由 Task 1(需求 1、2、6)、Task 2(需求 3、4、5)、Task 3(§4.3 互斥)、Task 4(需求 7)实现;§4.2 中断时序、§4.4 线程安全审计结论由 Task 2 代码与既有线程安全现状落实(审计为分析结论,无代码产物)。
- **占位符扫描**:无 TBD/TODO;所有代码步骤含完整代码。
- **类型一致性**:`run_batch` 签名(含 `max_threads: int = 10`)在 Task 1 与 Task 2 一致;`_warn(message: str) -> None` 在 Task 3 定义与测试一致;测试数预期 143 由逐任务累加计算。
