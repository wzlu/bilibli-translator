# md2zh stdin 支持设计规格

日期:2026-10-12
状态:已批准

## 背景

unix-cli 审计(44 条规则)指出 io-support-stdin(HIGH)缺口:md2zh 仅接受文件参数,无法作为管道过滤器使用。本规格为 v0.1.0 的增量功能。

## 接口

- `md2zh -`:FILE 位置参数接受 `-`,从 stdin 读取 Markdown,译文写 stdout。
- 无参数行为不变(用法错误,退出 64)。
- `-` 与 `--filelist` 同用仍报用法错误(64),复用现有互斥校验。
- `--force` 对 stdin 为 no-op(无目标文件,不报错)。
- 其余选项(`--glossary`/`--api-base`/`--model`)照常生效。

## 数据流

新增 `translator.run_stdin(*, glossary, api_base, model) -> int`:

1. 从 `sys.stdin.buffer` 按 `utf-8-sig` 解码(与文件读取一致,容忍 BOM)。
2. 空输入(去空白后为空)直接返回 0,不调用 API。
3. CRLF 归一为 LF(与 `translate_file` 内部管线一致)。
4. 复用 `_translate_document`:frontmatter 独立翻译、代码块占位符保护、单次/分段策略、校验修复循环、失败回退原文——全部不变。
5. 译文经 `sys.stdout.buffer` 字节写出(绕开平台行尾翻译),结尾无换行时补一个 `\n`——与文件模式输出字节一致(换行保真)。

cli.py:`main` 中 `args.file == "-"` 时调用 `run_stdin`,不走文件路径。

## 错误处理

退出码复用现有契约:

| 场景 | 退出码 |
|------|--------|
| stdin 非 UTF-8(`UnicodeDecodeError`) | 65 |
| 翻译 API 失败(`TranslateError`) | 75 |
| stdin 读取失败(`OSError`) | 74 |
| 下游管道提前关闭(`BrokenPipeError`) | 141(main 已有处理) |

流约定不变:stdout 只输出译文,进度/警告/错误走 stderr,GNU 格式 `md2zh: 上下文: 信息`。

## 测试(TDD)

新增 4 项,`tests/test_translator.py` 与 `tests/test_cli.py` 各就其位:

1. `run_stdin` 正常路径:monkeypatch `sys.stdin`(含 BOM 字节)与 `api.translate_text`,断言返回 0、stdout 为译文。
2. `cli.main(["-"])` 端到端:monkeypatch API,断言 stdout 为译文、stderr 为空。
3. 非 UTF-8 stdin → 65,无堆栈。
4. 空 stdin 直接返回 0 且不调用 API(monkeypatch 计数)。

## 文档更新

- README:快速开始加 `cat ABC.md | md2zh -` 示例;CLI 参数说明提及 `-`。
- `--help` epilog 加管道示例。
- CHANGELOG [Unreleased] 记录该功能。
- CLAUDE.md CLI 接口说明同步。

## 非目标

- 无 `--output` 选项(stdin 译文只写 stdout,YAGNI)。
- 不改变无参数时的用法错误行为(保持契约)。
- 不实现 stdin 的 `--force` 语义。
