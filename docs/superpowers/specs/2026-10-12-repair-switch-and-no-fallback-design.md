# md2zh:修复重译参数开关与不回退语义 设计文档

- 日期:2026-10-12
- 状态:已确认(用户批准设计;批量实测日志分析驱动)
- 相关规格:`2026-10-12-repair-counter-and-bold-check-removal-design.md`(v0.2.4 计数器)、`2026-10-12-frontmatter-check-removal-design.md`(v0.2.5)

## 1. 背景与目标

批量实测(untranslated_filelist.txt,26 个新译文件)与历史数据一致表明:修复重译对链接丢失/错位类失败**从未收敛**(opensre 历次、adding-tools),每失败块却固定多花 2 次 API 调用;且校验失败后「回退原文」使整块保持英文,与「全流程自动化、全量中文化」目标冲突——中文文档里夹着英文块的体验比损失 2 个链接更差。

用户裁决:①修复重译做成参数开关 `--repair N`(默认关闭 0 次,可开至多 2 次);②校验失败**永不回退原文**,一律采用译文(警告提示)。

目标:默认路径每个失败块省 2 次注定失败的 API 调用;译文文件不再出现英文块;校验保留(驱动可选重试 + 产生警告)。

## 2. 需求清单

1. 新增 CLI `--repair N`(整数 0-2,默认 0);非法值经既有 argparse 错误路径退出 64;文件/批量/stdin 三模式一致生效;
2. 校验失败永不回退:repair=0 直接采用译文;repair=1-2 重译耗尽后采用**最后一次**译文;两种终点均打印警告;
3. 三重校验(链接/表格/占位符)、占位符管线、退出码契约(64 复用,无新增)、网络重试(translate_text 内部 2 次)、frontmatter 路径(v0.2.5 无校验)均不变;
4. `repair` 参数穿透全链:`translate_file` / `run_single` / `run_batch` / `run_stdin` / `_translate_document` / `_translate_chunk` / `_translate_long` / `_repair`;
5. 计数器语义保留:`重译(x/N)` = 第 x 次重译即将进行,守卫 `attempt < retries`,无越界;
6. 版本提升 **0.3.0**(新增 CLI 选项 + 默认行为变更);测试改写回退断言并新增开关/穿透/校验测试;真实 API 复验门槛重设。

## 3. 方案选型

- **方案 A(选定):`--repair N` 开关 + 永不回退**。默认 0 次省调用;开启时保留既有重译序列;终点统一采用译文。用户明确裁定。
- 方案 B:开关但开启时耗尽仍回退原文——开启开关反而可能得到英文块、默认关闭得到中文块,语义别扭,否(用户已裁决「也采用译文」)。
- 方案 C:固定重试 1 次(无开关)——与「参数开关」要求不符,否。

## 4. 详细设计

### 4.1 核心循环(translator.py `_repair`)

`_repair` 整体替换为(返回值由 `tuple[bool, str]` 改为 `str`,不再有失败分支):

```python
def _repair(make_prompt, check, *, api_base: str, model: str,
            max_tokens: int, label: str, source: str = "", retries: int = 0) -> str:
    """校验驱动的可选重译:失败打印警告,始终返回最后一次译文。

    retries 为校验失败后的重译次数(0 表示不重译);校验只决定是否重试,
    不回退原文——损坏块以译文形态写出,由警告提示(信任模型取舍)。
    """
    prefix = f"{source}: " if source else ""
    problems: list[str] = []
    dst = ""
    for attempt in range(retries + 1):
        dst = api.translate_text(api_base, model, make_prompt(";".join(problems)), max_tokens)
        problems = check(dst)
        if not problems:
            return dst
        if attempt < retries:
            sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{retries}): {';'.join(problems)}\n")
    if retries:
        sys.stderr.write(f"md2zh: 警告: {prefix}{label}重译耗尽,采用译文: {';'.join(problems)}\n")
    else:
        sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,采用译文: {';'.join(problems)}\n")
    return dst
```

要点:

- `attempt < retries` 守卫使 `重译(x/N)` 仅在确有后续重译时打印,越界不可能(v0.2.4 守卫推广);
- retries=0:循环恰 1 次,失败后打印「校验失败,采用译文」;retries>0:中间失败打印「重译(x/N)」,耗尽打印「重译耗尽,采用译文」;
- v0.2.1 前缀契约(`{source}: `/`<stdin>`)保留。

### 4.2 调用链(translator.py)

`_translate_chunk` 整体替换为(删除回退分支):

```python
def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "", *, source: str = "",
                     repair: int = 0) -> str:
    """翻译一段文本:校验失败按 repair 可选重译,始终采用译文。"""
    dst = _repair(
        make_prompt=lambda fix: api.build_prompt(src, glossary, fix_notes=fix, context=context),
        check=lambda d: _check_block(src, d),
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
        source=source, retries=repair,
    )
    # 译文经 API strip,回挂源块尾随空白,保持分段边界与文件末尾布局
    return dst + _trailing_whitespace(src)
```

`repair` 参数穿透(全部 keyword-only 追加,默认 0):

- `translate_file(src_path, *, force, glossary, api_base, model, repair)`
- `run_single(path, *, force, glossary, api_base, model, repair)`
- `run_batch(paths, *, force, glossary, api_base, model, repair, ignore_matcher=None)`
- `run_stdin(*, glossary, api_base, model, repair)`
- `_translate_document(text, glossary, api_base, model, *, source="", repair=0)`
- `_translate_long(text, glossary, api_base, model, *, mapping, source="", repair=0)`

`translate_file`/`run_*` 把 `repair` 透传给 `_translate_document`;`_translate_document` 传给 `_translate_chunk`/`_translate_long`;`_translate_long` 传给各段 `_translate_chunk`。frontmatter 路径(v0.2.5)不接收 repair(无校验)。

### 4.3 CLI(cli.py)

`parse_args` 在 `--model` 之后新增:

```python
    parser.add_argument("--repair", type=int, choices=range(3), default=0,
                        help="校验失败后的重译次数 0-2(默认 0;失败一律采用译文,不回退原文)")
```

非法值(N 不在 0-2、非整数)由既有 `_Parser.error` 路径退出 64;`main` 三个分支(run_stdin/run_batch/run_single)各自透传 `repair=args.repair`;`epilog` 示例追加一行 `--repair` 用法。

### 4.4 警告契约总表

| 场景 | stderr 行 |
|---|---|
| repair=0,校验失败 | `md2zh: 警告: {前缀}块校验失败,采用译文: {问题}` |
| repair>0,第 x 次重译前 | `md2zh: 警告: {前缀}块校验失败,重译(x/N): {问题}` |
| repair>0,耗尽 | `md2zh: 警告: {前缀}块重译耗尽,采用译文: {问题}` |
| 校验通过 | 无警告(现状) |

「块重译耗尽,保留原文」警告永久移除。

### 4.5 兼容性与残余风险(如实声明)

- **行为变更**:校验失败不再回退原文,损坏块(丢链接/表格行/占位符)以译文形态写入文件,警告是唯一提示;占位符丢失意味着对应代码块内容不会出现在输出中——「信任模型、全量中文化」取舍,由用户裁定;
- 网络错误路径不变:`translate_text` 抛 `TranslateError` → 既有 75 路径;空译文仍抛异常;
- 修复重译对链接/占位符类失败实证无收敛,`--repair 2` 与旧行为仅终点不同(采用译文而非回退);
- 校验函数本身零改动——未来若要放宽/删除任一校验,另开周期。

### 4.6 范围界定

仅修复循环语义与 CLI 开关。三重校验函数、占位符管线、退出码、流约定、换行保真、frontmatter 路径均不动。

## 5. 测试计划(严格 TDD)

| 测试 | 断言 |
|---|---|
| 新增:默认 0 次不重试且采用译文(translator) | `_translate_chunk` 校验失败(不传 repair)→ API 恰 1 次调用、stderr 含「块校验失败,采用译文」、不含「重译」、结果为译文 |
| 新增:repair=1 恰 2 次调用(translator) | 传 `repair=1`:两译皆失败 → 恰 2 次调用,警告序列 重译(1/1) + 「块重译耗尽,采用译文」,结果为第 2 次译文 |
| 改写:重译后成功(translator) | `test_chunk_repair_then_success` 显式传 `repair=1`(默认 0 下第 2 份输出永不被消费),断言成功且恰 2 次调用 |
| 改写:计数器不越界(translator) | `test_chunk_repair_warning_retry_counter_bounded` 传 `repair=2`:含 1/2、2/2、无 3/2、「块重译耗尽,采用译文」;结果为第 3 次译文(非原文) |
| 改写:长文耗尽警告(translator) | 原「保留原文」断言改「采用译文」:传 `repair=2`,结果=译文,耗尽行新文本 |
| 改写:端到端文件/批量/stdin 耗尽(translator) | `test_translate_file_warning_names_path` 与 stdin 对应测试:传 `repair=2`,文件/stdout 内容为译文,警告新文本 |
| 新增:CLI 非法值 64(cli) | `--repair 3` / `--repair -1` / `--repair x` → 退出码 64,stderr 含用法提示 |
| 新增:CLI 穿透(cli) | `main` 传 `--repair 2` → fake 恰 3 次调用;默认(不带选项)→ 恰 1 次 |
| 新增:stdin 默认 0 采用译文(translator) | `run_stdin` 校验失败 → stdout 为译文,警告「块校验失败,采用译文」 |

既有其余测试零改动;改写项 1:1 净 0。**终态 129 项全绿**(124 + 5 新增)。

真实 API 复验(发布前门槛,控制方执行):

1. `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md" --force`(默认 repair=0):无「保留原文」类警告;若链接块仍失败 → 警告为「块校验失败,采用译文」,`*_zh.md` 对应块为中译文(不再夹英文);加黑类警告 0;
2. `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\skills\analyzing-local-repositories\SKILL.md" --force`:0 警告(回归);
3. 观察项(不设硬验收):同一文件 `--repair 2` 对照跑,记录重译是否收敛,结论记入发布说明。

不达则裁决(回退对应改动或接受并如实记录)。

## 6. 文档与发布

- 版本按语义化版本提升至 **0.3.0**(minor:新增 CLI 选项 + 默认行为变更);
- CHANGELOG `[0.3.0]`:`### 新增`(--repair 开关)+`### 变更`(校验失败采用译文、不再回退原文,残余风险如实声明);
- CLAUDE.md:修复循环/四重格式保障条目改写(可选重译、采用译文);CLI 接口表加 `--repair`;Important Notes 已知限制「最坏后果为无谓重译或该块回退原文」改「无谓重译或损坏块以译文写出(警告提示)」;Overview 版本 0.3.0 与测试数 129;
- README:自动修复循环特性行重写;CLI 表加 `--repair`;已知限制行同步;徽章与测试数 129;
- Recent Updates 顶部新条目(真实 API 复验结果回填);台账记录。

## 7. 非目标(YAGNI)

- 校验函数的放宽或删除(保留三重校验,另开周期再议);
- fix_notes 具体化(把「少了哪两个链接」写进重译提示);
- 网络重试次数调整(translate_text 内部);
- 批量模式按文件独立 repair 配置;
- frontmatter 路径任何改动。
