# md2zh:翻译期警告补文件上下文 设计文档

- 日期:2026-10-12
- 状态:已确认(用户批准设计,格式决策经多选确认)
- 相关规格:`2026-10-12-md2zh-translator-design.md`(修复循环与流约定)

## 1. 背景与目标

批量翻译时,块级修复警告不带文件名,用户无法定位问题文件:

```
md2zh: 警告: 块重译耗尽,保留原文: 出现未知占位符: ['@@@INLINE_355@@@', '@@@INLINE_356@@@']
```

目标:上述警告补充文件上下文,格式与现有「跳过/失败」消息风格一致。

## 2. 需求清单

### 2.1 原始需求

1. 「校验失败,重译」与「重译耗尽,保留原文」两类警告补文件路径;
2. stdin 模式(`md2zh -`)无路径,用 `<stdin>` 标识。

### 2.2 澄清决策(与用户确认)

| 决策点 | 结论 |
|---|---|
| 警告行格式 | `md2zh: 警告: {路径}: 块重译耗尽,保留原文: ...`(路径紧跟「警告:」,与 `md2zh: 失败 {p}: ...` 一致) |
| stdin 标识 | `<stdin>`(如 `md2zh: 警告: <stdin>: 块校验失败,重译(1/2): ...`) |
| 路径形式 | 用户传入原样(批量模式与文件列表写法一致) |

## 3. 方案选型

- **方案 A(选定):`source` 参数贯穿调用链**。文件路径由 `translate_file`/`run_stdin` 作为仅关键字参数逐层传入 `_translate_document` → `_translate_frontmatter`/`_translate_chunk`/`_translate_long` → `_repair`,`_repair` 组装警告前缀。与现有 `context` 参数的贯穿风格一致,显式、无全局状态、易测。
- 方案 B(警告上移,文件层打印):`_repair` 不打印改为向上返回问题列表,需重构三层返回类型,改动大且违背现有低层直接打印惯例,不采用。
- 方案 C(模块级当前文件上下文变量):隐式全局状态,重入易错,不采用。

## 4. 详细设计

### 4.1 输出格式

- 文件模式:`md2zh: 警告: {source}: {label}校验失败,重译(1/2): {问题}`
  `md2zh: 警告: {source}: {label}重译耗尽,保留原文: {问题}`
- stdin 模式:`source` 为 `<stdin>`。

### 4.2 签名改动(均仅关键字、默认 `""`,向后兼容)

| 函数 | 改动 |
|---|---|
| `_translate_document` | 增 `source: str = ""`,下传 |
| `_translate_frontmatter` | 增 `source: str = ""`,下传 `_repair` |
| `_translate_chunk` | 增 `source: str = ""`,下传 `_repair` |
| `_translate_long` | 增 `source: str = ""`,下传 `_translate_chunk` |
| `_repair` | 增 `source: str = ""`,两条警告加前缀 |
| `translate_file` | 调 `_translate_document` 时传 `source=src_path` |
| `run_stdin` | 调 `_translate_document` 时传 `source="<stdin>"` |

### 4.3 兼容性

`_repair` 组装前缀时 `source` 非空才加 `f"{source}: "`,空值保持原格式——测试直接调用 `_translate_chunk`(不带 source)的警告文本与现状一致。生产路径(`translate_file`/`run_stdin`)必传非空 source。

### 4.4 范围界定

仅 `_repair` 的两条块级警告(覆盖正文块与 frontmatter 修复循环)。术语表、忽略列表的加载期警告无文件归属,不改。

## 5. 测试计划(严格 TDD)

新增测试(先写、确认 RED,再实现至 GREEN):

| 测试 | 断言 |
|---|---|
| `_translate_chunk` 重译耗尽警告含 source | `md2zh: 警告: docs/a.md: 块重译耗尽` 出现在 stderr |
| `translate_file` 端到端警告含实际路径 | stderr 含 tmp_path 源文件路径 |
| frontmatter 修复耗尽警告含 source | stderr 含 `{path}: frontmatter 重译耗尽` |
| `run_stdin` 警告含 `<stdin>` | stderr 含 `<stdin>: 块` |
| 无 source 直接调用警告格式不变(兼容) | stderr 不含空前缀 `警告: :` |

现有 114 项测试全部保持通过(现有测试无断言警告文本,成功路径 stderr 无输出断言不受影响)。

## 6. 文档与发布

- CHANGELOG 新增小节(警告补文件上下文);
- CLAUDE.md「流约定」补一句:块级修复警告带文件前缀,stdin 模式为 `<stdin>`;
- 版本号按语义化版本提升至 0.2.1。

## 7. 非目标(YAGNI)

- 长文分段警告加「第 N 段」序号;
- 术语表/忽略列表加载警告加文件归属;
- 警告中显示绝对路径或行号。
