# 变更日志

本项目所有值得注意的变更都将记录于此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/),
本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.0] - 2026-10-13

### 新增

- `--repair N` 修复重译开关:校验失败后的重译次数 0-2,默认 0(关闭)

### 变更

- 校验失败不再回退原文:一律采用最后一次译文并打印警告(取舍:损坏块如丢链接/占位符将以译文形态写出,警告为唯一提示;实证修复重译对链接类失败无收敛)

## [0.2.5] - 2026-10-12

### 变更

- 不再校验 frontmatter:按现有提示词规则翻译后译文直接采用,不重译、不回退(消除 YAML 折叠标量续行被冒号启发式误判导致的整块回退;取舍:模型若改 key 或丢 --- 标记将直接写出,由提示词约束保持)

## [0.2.4] - 2026-10-12

### 修复

- 重译计数器越界:耗尽路径不再打印「重译(3/2)」,仅在后续确有重译时打印「重译(x/2)」

### 变更

- 不再校验加黑 ** 标记:块级校验收敛为链接/表格/占位符三重,模型自行增删加黑不再触发重译/回退(取舍:译文可能含不成对 **,由提示词约束与模型自行保持)

## [0.2.3] - 2026-10-12

### 修复

- 链接 URL 以 `@@@URL_n@@@` 占位符物理隔离:URL 不再进入 API 请求,模型无从改写;还原时拼回原 url(残余:多链接间占位符错位仍会触发校验回退,损害有界)

### 变更

- 提示词格式约束由 5 条并为 3 条,不再逐项点名加黑与链接标记(稀疏化,降低模型对标记的过度改写)

## [0.2.2] - 2026-10-12

### 修复

- 长文分段上下文发送前还原占位符:占位符令牌不再进入 API 请求,消除「出现未知占位符」警告与整块回退英文原文的根因;携带上下文的提示词追加硬约束,输出不得包含上下文参考内容

## [0.2.1] - 2026-10-12

### 修复

- 块级修复警告补文件路径前缀(如 `md2zh: 警告: docs/a.md: 块重译耗尽,保留原文: ...`),批量模式下可定位问题文件;stdin 模式显示 `<stdin>`

## [0.2.0] - 2026-10-12

### 新增

- `md2zh -` 从 stdin 读入、译文写 stdout,可用作管道过滤器
- `--filelist` 批量模式自动读取当前目录 `.translateignore`,命中文件略过不翻译(精确路径 + 通配模式)

### 修复

- 下游管道提前关闭(如 `md2zh x | head`)按 128+SIGPIPE 静默退出,不再打印堆栈
- 数据输出改为 flush-through 并识别 errno(EPIPE/EINVAL),静默退出覆盖文件/批量模式的缓冲写路径
- stdin 输出前折叠 API 混入的 CRLF,保证 LF 源输出 LF

### 变更

- `--help` 增加实用示例
- 批量汇总增加「忽略」计数,格式为 成功/跳过/忽略/失败

## [0.1.0] - 2026-10-12

首个版本:基于 Bilibili Index-Translate 免费翻译 API 的英文 Markdown 转中文命令行工具。

### 新增

- 五模块分层架构:cli(参数解析与退出码)/ api(请求与提示词)/ markdown(块解析)/ checks(格式校验)/ translator(编排与批量)
- 代码块与行内代码占位符物理隔离,内容不发送给翻译 API
- frontmatter 拆分与独立翻译(仅译 value)
- 超长文档按逻辑边界分段,附前段上下文保证术语延续
- 块级格式校验(加黑配对、链接、表格、frontmatter、占位符)与自动修复循环(≤2 次重译,失败回退原文)
- 术语表支持:`--glossary` 与用户配置目录默认术语表
- 流式翻译请求与网络重试,User-Agent 防网关 412
- CLI:单文件与 `--filelist` 批量模式、`--force`、`--api-base`、`--model`
- 标准退出码契约:0 / 1 / 64 / 65 / 66 / 74 / 75 / 130
- 76 项自动化测试(API 全 mock,不依赖网络)
- MIT 开源许可证(LICENSE 文件与 pyproject.toml 声明)

### 修复

- 嵌套反引号围栏被错误截断
- 逻辑块合并分支分隔符顺序颠倒
- 源文奇数加黑时校验死锁
- 分段边界焊接、超限块输出预算、修复循环重复
- 翻译请求缺少 User-Agent 触发网关 412
- SSE 畸形分片防护、CRLF/LF 换行保真、BOM 文件列表解析
- 非 UTF-8 文件列表返回 EX_DATAERR 而非打印堆栈
- 翻译失败异常保留原始异常链
- 默认术语表非 JSON 对象时输出警告

### 变更

- 抽取提示词约束装配共享逻辑
- README 补充代码仓库链接、git clone 安装路径与许可证章节
- CLAUDE.md 更新远程仓库与文件跟踪状态说明

[Unreleased]: https://github.com/wzlu/bilibli-translator/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.3.0
[0.2.5]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.5
[0.2.4]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.4
[0.2.3]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.3
[0.2.2]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.2
[0.2.1]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.1
[0.2.0]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.2.0
[0.1.0]: https://github.com/wzlu/bilibli-translator/releases/tag/v0.1.0
