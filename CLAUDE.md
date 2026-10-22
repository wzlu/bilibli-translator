# md2zh

## Overview

将英文 Markdown / HTML / TXT 文件翻译为中文的 Python 命令行工具(≥3.10),基于 Bilibili Index-Translate 免费翻译 API。亦支持本地 ollama 离线翻译(`--ollama`)。格式按扩展名自动推断(`.md/.markdown→md`、`.html/.htm→html`、`.txt→txt`,未知扩展名回落 md),可用 `--format` 显式覆盖;文件模式译文保存于原文件同目录,命名为 `*_zh.<原扩展名>`(如 `ABC.md → ABC_zh.md`);`md2zh -` 支持 stdin 读入、译文写 stdout(管道过滤器);`txt2zh` 为同一入口的命令别名。符合 unix-cli 规范,全流程自动化、无人值守。当前版本 0.6.0。

## Architecture

九模块分层(职责边界严格,不跨层):

- `cli.py` — 参数解析(用法错误退出 64)、`-` 路由到 stdin 模式、退出码映射、main 入口(SIGINT/SIGPIPE 捕获);`--format` 选项与 `txt2zh` 别名程序名显示
- `translator.py` — 编排层:单文件全流程、修复循环、批量处理、stdin 模式(run_stdin)、原子写;退出码常量全 CLI 唯一出处;调用点按格式注册表分派(`fmt=None` 回落 md)
- `api.py` — 术语表加载、按格式注入约束的提示词构建、流式翻译请求与重试(运行期依赖仅 `requests`)
- `formats.py` — 格式注册表:Format(frozen dataclass:split_frontmatter/protect/restore/chunk_text/validators/constraints)与 md/html/txt 三条目;`infer_format` 按扩展名推断、未知回落 md
- `html.py` — HTML 适配器:引号感知状态机单遍扫描,标签/属性/注释/doctype/实体/script·style·pre·code 原始块占位保护(令牌 `@@@HTMLBLOCK_n@@@`/`@@@HTMLTAG_n@@@`/`@@@HTMLENT_n@@@`),还原字节级保真
- `txt.py` — TXT 适配器:零保护直通、空行分段
- `markdown.py` — Markdown 适配实现与共享分段工具:frontmatter 拆分、代码块/行内代码占位符保护、逻辑分段;`pack_blocks`/`split_blank_lines`/朴素还原供 html/txt 单向复用
- `checks.py` — 纯函数块级校验:链接、表格、占位符、HTML 文本(模型自造标签/实体计数)
- `ignore.py` — 忽略列表解析与通配匹配(精确路径 + `**`/段内通配,UTF-8-sig→GBK 回退)

**核心设计决策:**

- **代码块物理隔离**:围栏/行内代码以 `@@@CODEBLOCK_n@@@` / `@@@INLINE_n@@@` 占位符替换后才发送 API,模型看不到代码内容
- **链接 URL 物理隔离**:[显示文本](url) 的 url 以 `@@@URL_n@@@` 占位符替换后才发送 API,模型不可见,还原时拼回
- **格式注册表与分派**:Format 适配面(md/html/txt 三条目)统一保护/还原/分段/校验/提示词约束;translator 调用点改派 `fmt.split_frontmatter/protect/restore/chunk_text/validators/constraints`;`api.build_prompt` 按格式注入约束(缺省回落 `markdown.CONSTRAINTS`,默认输出与既有逐字节一致);内部函数 `fmt=None` 回落 md,CLI `--format` 显式覆盖推断,批量模式缺省逐文件推断
- **HTML 状态机占位保护**:引号感知单遍扫描——标签内引号含 `>` 不误切,script/style/pre/code 原始块整体保护至首个 `</name`(不区分大小写),字面 `<` 与未知实体不误判,命名实体按 `html.entities.html5` 最长匹配;保护顺序 块→标签→实体 保证 mapping 值不含令牌,朴素顺序 replace 还原往返字节级安全;不引入解析器、不重序列化(spike 实证:正则与 html.parser 方案均被否决)
- **单次调用为主**:可译文本 ≤ 15000 字符整文一次流式调用(术语天然一致);超长按逻辑边界分段(≤3000 字符/段,附前段上下文参考保证术语延续;上下文发送前还原占位符,占位符令牌不进 API 请求),不可分割的超限块按块长缩放输出预算
- **四重格式保障**:占位符隔离 + 提示词格式约束 + 块级校验 + 可选自动修复循环(--repair 默认关闭;校验失败一律采用译文并警告,不回退原文)
- **frontmatter 独立翻译**:仅译 value,key 与 `---` 标记由提示词约束保持,不校验、不重译、不回退
- **术语表**:`--glossary` 指定 JSON 文件(`{"英文": "中文"}`);缺省自动加载 `~/.config/md2zh/glossary.json`(不存在视为无术语表);以【硬性要求】专名/术语对照附加到每段请求
- **忽略列表**:`--filelist` 批量模式自动读取当前目录 `.translateignore`(不存在视为无规则);命中文件略过不翻译,计入汇总「忽略」数(交叉情形:非 `--force` 且译文已存在时计「跳过」;忽略优先于扩展名/存在性检查与 `--force` 不变)
- **批量多线程**:`--filelist` 用 ThreadPoolExecutor(默认 10,可 `-c` 调整)并行翻译,译文已存在(非 `--force`)与忽略命中均前置不提交,完成即输出(乱序),计数与汇总在主线程聚合;未知异常兜底计失败;任意基类异常(中断/下游管道关闭)取消未启动任务后重抛,不等待运行中请求;批量 stderr 串行化:批量模式线程内与主线程的 stderr 打印统一经模块级锁 `_warn` 串行化,消除行间交错;stdout 仅主线程写
- **本地 ollama 后端**:`--ollama` 经布尔标志贯穿(cli→translator→api),ollama 分支省略 `chat_template_kwargs` 与特殊 UA(仅 B 站网关 412 要求);强制单线程在 CLI 层完成(`max_threads=1`),translator 线程池逻辑不变
- **换行保真**:文件模式 CRLF 源输出 CRLF,LF 源输出 LF(读取期关闭行尾翻译、检测后管线内部统一 LF、写回源风格);stdin 模式统一 LF 输出(写前折叠混入的 CRLF)
- **stdin 字节保真**:`md2zh -` 译文经 `sys.stdout.buffer` 字节写出(绕开平台行尾翻译),结尾无换行时补一个 `\n`;空输入直接成功退出不调 API

## Setup & Installation

```bash
python -m pip install -e ".[dev]"
```

- Python ≥ 3.10;运行期依赖仅 `requests`;开发依赖 `pytest`
- 无需 API Key(免费公开接口);翻译 API 需联网

## Development Workflow

- **严格 TDD**:先写失败测试 → 确认 RED → 最小实现 → 确认 GREEN → 提交
- 测试:`python -m pytest -v`(247 项,API 全部 mock,不依赖真实网络);报告输出 `python -m pytest -v --junitxml=reports/junit.xml`
- **真实 API 不进自动化测试**;手工验证清单见各版规格(md 基线 `docs/superpowers/specs/2026-10-12-md2zh-translator-design.md` §13;多格式 `2026-10-15-multiformat-html-txt-design.md` §6)
- 目录规则:源码 `src/`、测试 `tests/`、样例数据 `data/`、报告 `reports/`、临时文件 `temp/`
- 代码注释与用户可见输出一律中文
- 提交信息以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾
- 子代理驱动开发(SDD)台账:`.superpowers/sdd/progress.md`(任务完成记录与提交哈希)

## API Documentation

**调用的外部翻译 API(OpenAI 兼容):**

```
POST {api_base}/chat/completions   # 默认 https://index-translate.bilibili.com/v1
```

关键请求参数:`model=Index-Translate-35B-A3B`、`stream=true`(规避非流式长文本 504)、`temperature=0.0`、`chat_template_kwargs={"enable_thinking": false}`;**必须携带 `User-Agent: Index-Translate-Client/1.0`,否则网关返回 412**。网络错误自动重试 2 次,耗尽抛 `TranslateError`。参考实现:`references/call_api.py`(勿修改)。

`--ollama` 模式下改用本地 ollama 的 OpenAI 兼容端点(需本机运行 ollama 且已拉取 `index-translate-9b:latest`):`POST http://localhost:11434/v1/chat/completions`,请求省略 `chat_template_kwargs` 与特殊 User-Agent 要求,其余参数(stream/temperature/max_tokens)与 SSE 解析逻辑一致。

**CLI 接口:**

```
md2zh FILE | md2zh - | md2zh --filelist LIST [选项]   # txt2zh 为同一入口的别名
  FILE              .md/.markdown/.html/.htm/.txt(格式按扩展名推断,可被 --format 覆盖)
  --format FMT      输入格式 md/html/txt(默认按扩展名推断;stdin 模式缺省 md;批量模式显式值全局覆盖)
  --filelist LIST   文件列表(每行一个文件,# 注释行忽略)
  -c/--max-threads N   --filelist 模式最大线程数(默认 10;仅批量生效)
  --force           覆盖已存在的 *_zh.<原扩展名>(默认跳过)
  --repair N        校验失败后的重译次数 0-2(默认 0;失败一律采用译文)
  --glossary FILE   术语表 JSON 文件(缺省加载用户配置目录默认文件)
  --api-base URL    默认 https://index-translate.bilibili.com/v1
  --model M         默认 Index-Translate-35B-A3B
  --ollama          使用本地 ollama 翻译(端点 http://localhost:11434/v1,模型 index-translate-9b:latest,强制单线程;与显式 --api-base/--model/-c N≠1 冲突报错退出 64)
  -h/--help/--version
```

批量模式自动读取当前目录 `.translateignore`(命中文件略过,计入「忽略」统计)。

**退出码契约:** 0 成功(含全部跳过/忽略/校验失败采用译文) / 1 批量部分失败 / 64 用法错误 / 65 术语表格式错误或源文件非 UTF-8 / 66 输入不存在 / 74 写失败 / 75 API 临时不可用 / 130 SIGINT / 141 SIGPIPE(下游管道提前关闭)。

**流约定:** stdout 只输出数据(文件/批量模式输出译文路径,每行一个,可管道;stdin 模式输出译文正文);进度、跳过/忽略提示、警告、汇总全部走 stderr;错误消息 GNU 格式 `md2zh: 上下文: 信息`;用户可见错误不打 Python 堆栈。块级修复警告带文件路径前缀(stdin 模式为 `<stdin>`)。

## File Structure

```
├── CLAUDE.md / README.md / CHANGELOG.md / LICENSE / pyproject.toml / .gitignore
├── src/md2zh/           # 九模块实现(__init__.py 存版本号)
├── tests/               # pytest:test_markdown / test_checks / test_api / test_translator / test_cli / test_version / test_ignore / test_formats / test_html / test_txt
├── data/                # 手工验证样例(sample_en.md/html/txt;真实 API 产物 *_zh.* 不入库)
├── reports/             # 测试报告(生成物,gitignore)
├── docs/superpowers/    # specs/(规格) 与 plans/(实施计划)
└── references/call_api.py   # Bilibili 官方参考实现,保持不动
```

## Recent Updates (Updated: 2026-10-15)

v0.6.0 多格式支持(HTML/TXT):74e59b3..6a38b20 共 17 个提交(规格 + 计划 + 任务 1-6 实施与审查修复 + 终审修复波 + 验证结果回填),247/247 测试通过(含合并结果复验)。CLI 从仅 .md 扩展为多格式翻译工具:格式按扩展名推断(`.md/.markdown`、`.html/.htm`、`.txt`;未知扩展名回落 md,非 .md 文件不再拒绝),新增 `--format md|html|txt` 显式覆盖(stdin 模式缺省 md;批量模式显式值全局覆盖、缺省逐文件推断)与 `txt2zh` 命令别名(同一入口,usage/--version 随入口名显示,非别名回落 md2zh)。新增格式注册表(formats.py)与 HTML/TXT 适配器:HTML 经引号感知状态机单遍扫描——标签/属性/注释/doctype/实体与 script/style/pre/code 原始块占位隔离(还原字节级保真,不引入解析器),校验新增 `check_html_text`;提示词约束按格式分派(md 默认输出逐字节不变);共享分段工具抽取(pack_blocks/split_blank_lines);translator/api 按 `fmt` 贯穿分派(内部缺省回落 md)。实施与审查期修复:块级译文首尾空白回挂(原仅末尾,HTML 令牌边界分段暴露块首空白丢失)、`_find_close` 改定宽切片比较(修复 `text.lower()` 偏移错位致静默 HTML 损坏)。保护机制经 spike 实证(正则与 html.parser 方案否决,自研状态机 16/16 陷阱语料 + CRLF 页面全 PASS)。已 fast-forward 合并回 main、功能分支已删除,终审修复波闭环,已推送 origin 并打 tag v0.6.0。真实 API 手工验证(规格 §6 全部 6 项)实测完成:①HTML 单文件——标签/属性/实体字节级完好(`title="a &gt; b example"`、`href="/docs?a=1&b=2"` 原样)、script/style/pre 原样、文本节点全译、0 警告、无 @@@ 残留;②TXT 直通正确(术语 API/SDK 保留);③stdin `--format html` 退出 0、stderr 空、输出与文件模式一致;④重装后 `txt2zh --version` = `txt2zh 0.6.0`;⑤混合格式批量(md/html/txt)3/3 成功、退出 0、乱序输出、零警告;⑥md 回归 0 警告。发布门槛通过。

v0.5.0 `--ollama` 本地后端:dfd1e91..77f02a9 共 10 个提交(规格 + 计划 + 任务 1-4 实施 + 终审修复波与口径同步),164/164 测试通过。新增 `--ollama`:改用本地 ollama 的 OpenAI 兼容端点(`http://localhost:11434/v1`,模型 `index-translate-9b:latest`)离线翻译,api 层按标志省略 B 站特有的 `chat_template_kwargs` 与 User-Agent 要求;`ollama` 布尔标志经 cli→translator→api 贯穿(translator 线程池逻辑不变);cli 层冲突检测:与显式 `--api-base`/`--model`/`-c N(N≠1)` 冲突报错退出 64(`-c 1` 合法),并在 CLI 层强制单线程(`max_threads=1`)。终审修复波:边界透传守卫测试(frontmatter+分段长文)、`-c N≠1` 冲突语义(用户裁决)、文档回填与 .gitignore 真实 API 产物忽略。已 fast-forward 合并回 main,已推送 origin 并打 tag v0.5.0。真实 ollama 手工验证:规格 §6 全部 6 项实测完成。第 1/2/4/6 项(单文件 34s、stdin 17s、三组冲突均退出 64、无 @@@ 与 `</think>` 残留);真实 README 单文件复验(译文 8.8KB)0 警告、退出 0,总耗时 >120s 未触发超时——120s 为单次请求上限,首次调用含模型加载,超时风险集中于单个超限块的单次推理(实测未见);第 3 项 filelist 批量:3 文件 31s 全部成功、单线程顺序输出、汇总「成功 3」零警告、译文无残留;第 5 项停服:终止 ollama 进程后运行,重试耗尽退出 75(13s,stderr 报 WinError 10061 连接拒绝),服务恢复后连通正常。

v0.4.0 filelist 批量多线程:bbbc777..b48ec5b 共 10 个提交(设计/计划 + 任务 1-4 实施与审查修复),本提交为文档同步;148/148 测试通过。新增 `-c N, --max-threads N`(默认 10,仅批量模式生效);`run_batch` 改 ThreadPoolExecutor 并行:忽略命中前置不提交、译文路径完成即输出(乱序)、未知异常兜底计失败;批量 stderr(线程内与主线程)统一经模块级锁 `_warn` 串行化;终审修复:任意基类异常(KeyboardInterrupt/下游管道关闭)取消未启动任务后重抛——此前管道关闭时 run_batch 未关停线程池,atexit 哨兵排在任务队列尾部,进程退出前会译完整批剩余文件,现已闭环并由 broken_pipe 测试锁定。汇总与退出码契约不变;已 fast-forward 合并回 main 并推送 origin,已打 tag v0.4.0。真实 API 复验(opencode 130 文件,`-c 5`):成功 117、跳过 13、失败 0,完成即输出(乱序)与 stderr 无行间交错;3 块「占位符丢失」警告(2.6%,不回退语义既定取舍)。

v0.3.0 修复重译开关与不回退语义:0e8aa87..880c704 共 7 个提交(计划 + 任务 1-2 实施),本提交为文档同步;129/129 测试通过。--repair N 开关(默认 0);校验失败一律采用译文,不再回退原文。真实 API 复验:opensre 默认 repair=0 无「保留原文」警告、链接失败块仅 1 次「校验失败,采用译文」警告(默认不重译生效),该块为中译文且无 @@@ 残留;SKILL.md 0 警告;观察项 --repair 2:重译(1/2)→(2/2)→耗尽,链接类重译仍不收敛(与历史一致),耗尽后采用译文。

v0.2.5 frontmatter 校验移除:d83ee6f..4175751 共 2 个提交(计划 + 任务 1 实施),本提交为文档同步;124/124 测试通过。frontmatter 翻译后不再校验,译文直接采用。真实 API 复验:SKILL.md 0 警告,frontmatter 全译为中文(key 与 --- 标记完好,折叠标量续行不再误判);opensre_system_prompt.md 回归:加黑 0、链接 1 块(v0.2.3 已知错位残余,≤1 达标)。

v0.2.4 重译计数器修复与加黑校验移除:7777b6b..ca43b2a 共 3 个提交(规格/计划 + 任务 1-2 实施),本提交为文档同步;127/127 测试通过。真实 API 复验(opensre_system_prompt.md):失败块 2→1,加黑类 1→0(验收达标),链接残留 1 块为 v0.2.3 已知占位符错位残余(≤1 达标);计数器序列为 重译(1/2)→重译(2/2)→重译耗尽,无越界。

v0.2.3 链接 URL 占位符化与提示词稀疏化:9896253..20f5945 共 3 个提交(规格/计划 + 任务 1-2 实施),本提交为文档同步;128/128 测试通过。链接 URL 以 @@@URL_n@@@ 物理隔离(模型不可见),提示词格式约束并条去枚举;真实 API 验证:失败块 4→2(加黑 3→1),链接残留 1 块为多链接占位符错位(URL 改写已结构性杜绝),已裁决随行发布。

v0.2.2 上下文占位符泄漏修复:2dff2fa..913c0b8 共 3 个提交(规格/计划 + 任务 1-2 实施),本提交为文档同步;123/123 测试通过。长文分段上下文发送前还原占位符(占位符令牌不进 API 请求),提示词追加上下文隔离硬约束,消除「出现未知占位符」整块回退根因。

v0.2.1 警告补文件上下文:295781c..9b637d5 共 5 个提交(规格/计划 + SDD 3 任务 × 实施/审查),120/120 测试通过。块级修复的两条警告(校验失败重译、重译耗尽保留原文)补 `{路径}: ` 前缀,批量模式下可定位问题文件;stdin 模式显示 `<stdin>`;`source` 为空(内部直接调用)时保持原格式。

v0.2.0 忽略列表功能:29091d2..0c42ffa 共 18 个提交(SDD 6 任务 × 实施/审查 + 4 次审查修复波),114/114 测试通过,opus 全分支终审 "Ready to merge: Yes",已推送 origin/main 并打 tag v0.2.0。`--filelist` 批量模式自动读取当前目录 `.translateignore`(精确路径 + `**`/段内通配,`UTF-8-sig→GBK` 回退,非法规则警告降级),命中文件略过并计入「忽略」汇总。

v0.1.0 初版完成:12 个任务全部落地(20 个提交,主分支 main),终审 "Ready to merge: Yes",76/76 测试通过,真实 API 手工验证 5/5。执行期经审查修复的计划缺陷:嵌套反引号围栏截断、分段分隔符颠倒、源文奇数加黑校验死锁、提示词装配重复、分段边界焊接/超限块预算/修复循环重复、User-Agent 412、SSE 非 dict 分片防护、换行保真、BOM 文件列表。

同日发布至 GitHub:添加远程 origin(https://github.com/wzlu/bilibli-translator),main 建立上游跟踪并推送全部 21 个提交;发布版 README 改写、CLAUDE.md、docs/ 与 references/ 由未跟踪转为入库(提交 0c3b03a)。

同日完成 stdin 管道过滤器与 unix-cli 审计修复:新增 `md2zh -`(stdin 读入、译文写 stdout,字节保真输出);unix-cli 44 规则审计修复 SIGPIPE 静默退出(141,flush-through + errno 感知)与 `--help` 示例;88/88 测试通过。SDD 全流程:3 任务 × 实施/双重审查 + opus 全分支终审 "Ready to merge: Yes"(修复波后),推送 origin/main(提交 5eb2da4..86fcb14)。

## Important Notes

- **`references/call_api.py` 是参考实现,不得修改**
- stdin 模式注意:`--force` 为 no-op;纯空白输入静默退出(退出 0、无输出,不调用 API);输出统一 LF(与文件模式行尾保真不同);`run_stdin` 的断管/读写错误分支无专属测试(行为经 main 处理器等价覆盖)
- 已知限制(终审裁决随行发布):SSE `delta` 为非 dict 时的极端畸形分片未防护(与参考实现同款);表格行跨表按全局下标配对、紧凑表格 `|--|--|` 不识别等启发式边界——最坏后果为无谓重译或该块以损坏译文写出(警告提示),损害有界
- v0.3.0 已知限制(终审分流随行发布):`repair` 为负值的库级误用会静默产出空译文(CLI `choices` 已拦截,仅直接库调用可达);校验失败被采用的块可能残留字面 `@@@...@@@` 令牌(不回退语义的既定取舍,实测无残留);stdin/批量模式的 `repair` 透传无经 `main()` 的专属测试(与文件模式同构,行为经代码核验与 file 模式测试覆盖)
- v0.4.0 已知限制(终审随行发布):批量模式 Ctrl+C/下游管道关闭后,运行中的请求至多延续重试×超时(最坏约 6 分钟)进程才退出(未启动任务已取消,`test_run_batch_broken_pipe_cancels_pending` 锁定该语义);`-c` 无上界(线程按文件数懒创建,用户自限);批量译文路径完成即输出、顺序不定(按设计);两个时序测试依赖 0.5s/0.05s 时差(10 倍余量,复跑稳定);真实 API 复验实测 3/117 块「占位符丢失」(INLINE 令牌,采用译文并警告,不回退语义既定取舍)
- v0.5.0 已知限制(终审观察项随行发布):本地 ollama 模型 thinking 输出会消耗 max_tokens 预算(超长输出可能被静默截断,finish_reason 未检测);120s 超时对本地慢速推理余量有限;代理环境下 localhost 请求未豁免 HTTP_PROXY(如需直连需自行设置 no_proxy)。均为本地后端边缘行为,损害有界
- v0.6.0 已知限制(终审随行发布):HTML 属性(alt/title/placeholder)不译,`lang`/`meta` 不改写;HTML5 双重转义态(如 script 内 `<!--<script>`)与 textarea/title 的 RCDATA 语义不特判,CDATA 内含 `>` 在首个 `>` 截断;正文以 `<`+字母 开头(如 `<apple`)误判为标签,最坏该段误保护不翻译;畸形 HTML(未闭合标签/引号)余文不保护地进入送译文本(protect→restore 往返恒等;译文若改写余文将触发裸字符校验警告);模型可能自造 `**` 等非 HTML 格式标记(提示词硬约束缓解,校验无法拦截);源文字面 `@@@...@@@` 与占位符令牌冲突概率极低(与 md 同取舍);minified HTML 依赖占位符令牌边界分段,超长单块保持完整(按块长缩放输出预算);未知扩展名回落 md;`txt2zh` 调用的 stderr 前缀仍为 `md2zh:`;库级 fmt 非法值仅库调用可达
- 忽略列表已知限制(规格 §11):无 `**` 的相对模式可能轻微过匹配段边界(如 `docs/a*.md` 会命中 `xdocs/a.md`);含字面 `*`/`?` 的路径按通配处理;不支持 `!` 反排除与逐目录继承;目录模式为直接子文件语义(与 ds-translator 追加 `**` 的递归行为略有差异)。项目根 `.translateignore` 为用户本地文件(已入 .gitignore,不入库)
- 环境提示:anaconda 全局 pytest-asyncio 插件会产生 `PytestDeprecationWarning`(非本项目代码所致);Pyright 对可编辑安装的 `md2zh` 导入解析警告同理可忽略
- 远程仓库:https://github.com/wzlu/bilibli-translator(main 跟踪 origin/main,最新 tag v0.6.0);`temp/`、`reports/`、`.superpowers/` 由 .gitignore 忽略,`.serena/`、`.pytest_cache/` 有意不入库
