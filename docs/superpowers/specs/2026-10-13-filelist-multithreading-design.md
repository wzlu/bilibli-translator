# md2zh:filelist 多线程批量翻译 设计文档

- 日期:2026-10-13
- 状态:已确认(用户批准设计)
- 相关规格:`2026-10-12-md2zh-translator-design.md`(总体设计)、`2026-10-12-translateignore-design.md`(v0.2.0 忽略列表)

## 1. 背景与目标

`--filelist` 批量模式当前为顺序逐文件翻译(translator.py `run_batch` 的 for 循环),大列表耗时随文件数线性增长。翻译任务是纯 I/O 密集型(流式 HTTP 请求),适合线程并发。

目标:批量模式使用线程池并行翻译;最大线程数由 `-c N` 指定,缺省 10;单文件与 stdin 模式不变。

## 2. 需求清单

1. 新增 CLI 选项 `-c N, --max-threads N`(正整数,默认 10);非法值(`-c 0`/负数)经 `_Parser.error` 以 64 退出;
2. `-c` 仅 `--filelist` 模式生效;单文件/stdin 模式静默忽略(帮助文本注明);
3. 译文路径输出保持「完成即输出」:哪个文件先译完先输出(乱序,用户裁决),格式不变;
4. 汇总行「成功/跳过/忽略/失败」与退出码契约不变(有失败→EX_PARTIAL=1,全成功/全跳过/全忽略→0);
5. `.translateignore` 忽略优先语义不变(前置匹配,命中文件不提交线程池);
6. `-c 1` 退化为现行顺序行为(便于调试与回归对照);
7. 版本提升 **0.4.0**;README/CHANGELOG/CLAUDE.md 同步。

## 3. 方案选型

- **方案 A(选定):ThreadPoolExecutor + as_completed,主线程统一输出**。忽略匹配前置,其余文件提交线程池;主线程迭代 `as_completed` 乱序输出;计数在主线程聚合;stderr 线程内警告加模块级锁。标准库零新依赖,`translate_file` 签名不变。
- 方案 B:executor.map 保序收集——输出确定,但列表后部文件即使先译完也要等前面完成,与用户裁决「完成即输出」相悖,否。
- 方案 C:进程池或 asyncio——进程池 Windows 下 spawn 开销大且需序列化参数,I/O 任务线程已够;asyncio 需将 api.py 的 requests 重写为 aiohttp,破坏单文件路径并新增依赖,违背 YAGNI,否。

## 4. 详细设计

### 4.1 CLI 接口变更(cli.py)

`parse_args` 新增:

```python
parser.add_argument("-c", "--max-threads", type=int, default=10, metavar="N",
                    help="--filelist 模式最大并发线程数(默认 10;仅批量模式生效)")
```

校验(在既有互斥检查后):

```python
if args.max_threads < 1:
    parser.error("-c/--max-threads 必须是正整数")
```

`main` 的批量分支透传:`run_batch(..., max_threads=args.max_threads)`。`run_single`/`run_stdin` 不收此参数。epilog 增加示例 `md2zh --filelist list.txt -c 5`。

### 4.2 run_batch 并发化(translator.py)

`run_batch` 新增关键字形参 `max_threads: int = 10`,整体替换为:

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
            _warn(f"md2zh: 忽略 {p}: 命中忽略列表")
            ignored += 1
        else:
            todo.append(p)
    executor = ThreadPoolExecutor(max_workers=max_threads)
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
                _warn(f"md2zh: 失败 {p}: {e}")
                failed += 1
                continue
            if result.status == "ok":
                print(result.detail, flush=True)
                ok += 1
            elif result.status == "skipped":
                _warn(f"md2zh: 跳过 {p}: {result.detail}")
                skipped += 1
            else:
                _warn(f"md2zh: 失败 {p}: {result.detail}")
                failed += 1
    except BaseException:
        # 任意基类异常(KeyboardInterrupt / 下游管道关闭等):取消未启动任务、
        # 不等待运行中请求,主线程立即返回;cli.main 按类型映射 130/141
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown()
    _warn(f"md2zh: 汇总: 成功 {ok},跳过 {skipped},忽略 {ignored},失败 {failed}")
    return EX_PARTIAL if failed else EX_OK
```

要点:

- **计数与输出全在主线程**:无共享计数器,无数据竞争;「跳过/失败/忽略」消息与路径输出格式与现行完全一致;
- **异常边界**:`translate_file` 已把 API/编码/OS 错误收敛为 `TranslateResult`;未知回归引发的异常由主线程 `except Exception` 兜底——计入失败并继续处理其余文件,不拖垮批量(维护「继续处理所有文件,最后汇总」契约);
- **中断与管道关闭**:try 覆盖提交与收集两阶段,任意基类异常(`KeyboardInterrupt`、stdout 打印遇下游管道关闭抛出的 `BrokenPipeError` 等)走 `shutdown(wait=False, cancel_futures=True)`:取消未启动任务、不等待运行中请求,主线程立即返回,`cli.main` 按类型映射 EX_SIGINT=130(已中断)/EX_SIGPIPE=141(下游管道关闭);若仅捕获 `KeyboardInterrupt`,`BrokenPipeError` 将穿出 `run_batch` 且跳过关停,排队任务仍被 worker 逐个执行(解释器退出时 atexit 哨兵排在任务队列尾部),批量全量翻译无法被打断;运行中 worker 为非守护线程,进程退出时由解释器 join(窗口为在跑请求的剩余重试×超时,最坏约 6 分钟,但不再阻塞反馈);
- **裸 executor 收尾**:不用 `with`(其 `__exit__` 无条件 `shutdown(wait=True)`,会抵消「不等待」语义);常规路径在 try 之外显式 `executor.shutdown()`——任务已全部完成,立即返回,库级重复调用不泄漏空闲线程;

### 4.3 stderr 写入互斥(translator.py)

翻译线程内的重译警告(`_repair`、`_translate_chunk` 等)直接写 stderr,并发下可能行间交错。在 `translator.py` 增加模块级锁,stderr 打印统一包装:

```python
_stderr_lock = threading.Lock()

def _warn(message: str) -> None:
    """stderr 警告串行化:多线程下避免行间交错。"""
    with _stderr_lock:
        print(message, file=sys.stderr)
```

线程内 stderr 打印点仅 `_repair` 的三条警告(重译/耗尽/采用译文),全部改用 `_warn`;`run_batch` 主线程的 stderr 打印(忽略/跳过/失败/兜底/汇总)同样经 `_warn` 串行化,闭环主线程↔worker 的交错窗口;stdout 仅主线程写,不加锁;`run_single` 单线程路径直写 stderr 不变。锁竞争仅存在于批量并发时,单文件路径无额外开销。

### 4.4 线程安全审计

- `api.translate_text` 每次调用独立 `requests.post`,无共享 Session,重试逻辑局部变量——线程安全;
- `glossary` 为只读 `list[str]`,全线程共享只读——安全;
- `IgnoreMatcher` 加载后只读——安全;
- 模块级可变状态仅 `__version__`(字符串)——安全;
- 结论:除 stderr 互斥外无需任何同步。

## 5. 测试策略

严格 TDD,API 全 mock,不依赖真实网络;先写失败测试再实现。

- **test_cli.py**:`-c` 缺省值为 10;`-c 0`/`-c -1` → 退出 64 且 stderr 含错误信息;`-c 5` 在单文件模式下被接受且不影响行为(翻译结果不变);帮助文本含新选项。
- **test_translator.py**:
  - 并发正确性:monkeypatch `translate_file` 为「Event 阻塞后返回」的替身,断言全部文件恰好各提交一次、完成顺序与事件释放顺序一致(乱序)、stdout 路径行数正确;
  - 忽略前置:命中忽略列表的文件不进入线程池(替身断言不被调用);
  - 聚合:ok/skipped/failed 混合替身,断言汇总行与退出码 0/1;
  - `max_threads=1`:行为与顺序版一致(回归对照);
  - 真实线程集成:mock `api.translate_text`,对 3-4 个临时 md 文件(放置 `temp/`)跑 `run_batch(max_threads=4)`,断言全部 `*_zh.md` 生成且内容正确;
  - 兜底:替身抛 `RuntimeError`,断言计入失败、其余文件继续处理、退出码 1;
  - 中断路径:两任务替身,首个任务待第二个进入运行态后抛 `KeyboardInterrupt`,断言第二个任务仍在运行期间 `run_batch` 已重新抛出(不等待关停;worker 取队竞态经事件排序消除);
  - 管道关闭路径:`_BrokenStdout` 替身令 stdout 打印抛 `BrokenPipeError`,三任务替身仅 f1 立即返回、f2/f3 阻塞于事件,断言 `BrokenPipeError` 从 `run_batch` 重抛且宽限窗内剩余队列不被启动(钉住 `except BaseException` 关停语义);
  - stderr 互斥:`test_warn_writes_message` 钉住 `_warn` 消息格式;并发行完整守卫:`_SplitWriter` 把每次 write 拆两半并让出 GIL,两线程并发 `_warn` 后断言每行完整(钉住锁);路由契约:monkeypatch `_warn`,断言 `run_batch` 主线程 stderr 打印(忽略/跳过/失败/兜底/汇总)全部经 `_warn`。
- **test_version.py**:版本号 0.4.0。

## 6. 文档与发布

- README:选项表新增 `-c/--max-threads`,批量示例补并发用法;
- CHANGELOG:v0.4.0 条目(新增 CLI 选项 + 批量并发);
- CLAUDE.md:CLI 接口、架构决策、版本同步;
- 提交信息末尾附 Co-Authored-By;真实 API 复验清单追加批量并发项。
