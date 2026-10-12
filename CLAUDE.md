# md2zh

## Overview

将英文 Markdown 文件翻译为中文的 Python 命令行工具(≥3.10),基于 Bilibili Index-Translate 免费翻译 API。译文保存于原文件同目录,命名为 `*_zh.md`(如 `ABC.md → ABC_zh.md`)。符合 unix-cli 规范,全流程自动化、无人值守。当前版本 0.1.0。

## Architecture

五模块分层(职责边界严格,不跨层):

- `cli.py` — 参数解析(用法错误退出 64)、退出码映射、main 入口
- `translator.py` — 编排层:单文件全流程、修复循环、批量处理、原子写;退出码常量全 CLI 唯一出处
- `api.py` — 术语表加载、提示词构建、流式翻译请求与重试(运行期依赖仅 `requests`)
- `markdown.py` — 纯文本块解析:frontmatter 拆分、代码块/行内代码占位符保护、逻辑分段
- `checks.py` — 纯函数块级校验:加黑配对、链接、表格、frontmatter、占位符

**核心设计决策:**

- **代码块物理隔离**:围栏/行内代码以 `@@@CODEBLOCK_n@@@` / `@@@INLINE_n@@@` 占位符替换后才发送 API,模型看不到代码内容
- **单次调用为主**:可译文本 ≤ 15000 字符整文一次流式调用(术语天然一致);超长按逻辑边界分段(≤3000 字符/段,附前段上下文参考保证术语延续),不可分割的超限块按块长缩放输出预算
- **四重格式保障**:占位符隔离 + 提示词格式约束 + 块级校验 + 自动修复循环(校验失败带错误说明重译 ≤2 次,仍失败该块回退保留原文)
- **frontmatter 独立翻译**:仅译 value,key 与 `---` 标记严格保留,校验失败回退原文
- **术语表**:`--glossary` 指定 JSON 文件(`{"英文": "中文"}`);缺省自动加载 `~/.config/md2zh/glossary.json`(不存在视为无术语表);以【硬性要求】专名/术语对照附加到每段请求
- **换行保真**:CRLF 源输出 CRLF,LF 源输出 LF(读取期关闭行尾翻译、检测后管线内部统一 LF、写回源风格)

## Setup & Installation

```bash
python -m pip install -e ".[dev]"
```

- Python ≥ 3.10;运行期依赖仅 `requests`;开发依赖 `pytest`
- 无需 API Key(免费公开接口);翻译 API 需联网

## Development Workflow

- **严格 TDD**:先写失败测试 → 确认 RED → 最小实现 → 确认 GREEN → 提交
- 测试:`python -m pytest -v`(76 项,API 全部 mock,不依赖真实网络);报告输出 `python -m pytest -v --junitxml=reports/junit.xml`
- **真实 API 不进自动化测试**;手工验证清单见 `docs/superpowers/specs/2026-10-12-md2zh-translator-design.md` §13
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

**CLI 接口:**

```
md2zh FILE | md2zh --filelist LIST [选项]
  --filelist LIST   文件列表(每行一个 md 文件,# 注释行忽略)
  --force           覆盖已存在的 *_zh.md(默认跳过)
  --glossary FILE   术语表 JSON 文件(缺省加载用户配置目录默认文件)
  --api-base URL    默认 https://index-translate.bilibili.com/v1
  --model M         默认 Index-Translate-35B-A3B
  -h/--help/--version
```

**退出码契约:** 0 成功(含全部跳过/回退原文) / 1 批量部分失败 / 64 用法错误 / 65 术语表格式错误或源文件非 UTF-8 / 66 输入不存在 / 74 写失败 / 75 API 临时不可用 / 130 SIGINT / 141 SIGPIPE(下游管道提前关闭)。

**流约定:** stdout 只输出数据(成功生成的译文路径,每行一个,可管道);进度、跳过提示、警告、汇总全部走 stderr;错误消息 GNU 格式 `md2zh: 上下文: 信息`;用户可见错误不打 Python 堆栈。

## File Structure

```
├── CLAUDE.md / README.md / pyproject.toml / .gitignore
├── src/md2zh/           # 五模块实现(__init__.py 存版本号)
├── tests/               # pytest:test_markdown / test_checks / test_api / test_translator / test_cli / test_version
├── data/sample_en.md    # 手工验证样例(真实 API 产物 *_zh.md 不入库)
├── reports/             # 测试报告(生成物,gitignore)
├── docs/superpowers/    # specs/(规格) 与 plans/(实施计划)
└── references/call_api.py   # Bilibili 官方参考实现,保持不动
```

## Recent Updates (Updated: 2026-10-12)

v0.1.0 初版完成:12 个任务全部落地(20 个提交,主分支 main),终审 "Ready to merge: Yes",76/76 测试通过,真实 API 手工验证 5/5。执行期经审查修复的计划缺陷:嵌套反引号围栏截断、分段分隔符颠倒、源文奇数加黑校验死锁、提示词装配重复、分段边界焊接/超限块预算/修复循环重复、User-Agent 412、SSE 非 dict 分片防护、换行保真、BOM 文件列表。

同日发布至 GitHub:添加远程 origin(https://github.com/wzlu/bilibli-translator),main 建立上游跟踪并推送全部 21 个提交;发布版 README 改写、CLAUDE.md、docs/ 与 references/ 由未跟踪转为入库(提交 0c3b03a)。

## Important Notes

- **`references/call_api.py` 是参考实现,不得修改**
- 已知限制(终审裁决随行发布):SSE `delta` 为非 dict 时的极端畸形分片未防护(与参考实现同款);表格行跨表按全局下标配对、frontmatter 冒号启发式、紧凑表格 `|--|--|` 不识别等启发式边界——最坏后果为无谓重译或该块回退原文,损害有界
- 环境提示:anaconda 全局 pytest-asyncio 插件会产生 `PytestDeprecationWarning`(非本项目代码所致);Pyright 对可编辑安装的 `md2zh` 导入解析警告同理可忽略
- 远程仓库:https://github.com/wzlu/bilibli-translator(main 跟踪 origin/main);`temp/`、`reports/`、`.superpowers/` 由 .gitignore 忽略,`.serena/`、`.pytest_cache/` 有意不入库
