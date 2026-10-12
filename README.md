# md2zh

将英文 Markdown 文件翻译为中文的命令行工具,基于 Bilibili Index-Translate 免费翻译 API(无需 API Key)。译文保存于原文件同目录,命名为 `*_zh.md`(如 `ABC.md → ABC_zh.md`),全流程自动化、无人值守。

![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
![Version](https://img.shields.io/badge/version-0.1.0-brightgreen)
![Tests](https://img.shields.io/badge/tests-76%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-blue)

## 目录

- [特性](#特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [行为约定](#行为约定)
- [退出码](#退出码)
- [术语表](#术语表)
- [翻译 API 说明](#翻译-api-说明)
- [开发](#开发)
- [项目结构](#项目结构)
- [已知限制](#已知限制)
- [许可证](#许可证)

## 特性

- 🔒 **代码零泄露**:代码块与行内代码经占位符物理隔离,内容绝不发送给翻译 API
- 📐 **格式保真**:frontmatter(仅译 value,key 与 `---` 标记不变)、`**` 加黑配对、链接 url、表格行列均与原文一致;CRLF/LF 行尾按源文件原样保持
- 🔁 **自动修复循环**:块级校验失败时携带具体错误说明自动重译(≤2 次),仍失败则该块回退保留原文(格式天然正确),全程无需人工干预
- 📄 **长文档可靠**:≤15000 字符整文一次调用(术语天然一致);超长文档按逻辑边界分段,每段附前段上下文保证术语延续,超限块自动放大输出预算
- 📚 **术语表**:支持自定义术语对照,缺省自动加载用户配置目录默认术语表
- 🐚 **unix-cli 规范**:stdout 只输出译文路径(可管道);进度/警告走 stderr;标准退出码;`--help`/`--version` 完备

## 安装

要求 Python ≥ 3.10,运行期依赖仅 `requests`。

```bash
git clone https://github.com/wzlu/bilibli-translator.git
cd bilibli-translator
python -m pip install -e ".[dev]"
```

安装后命令行入口为 `md2zh`。

## 快速开始

```bash
# 翻译单个文件 → 同目录生成 ABC_zh.md
md2zh ABC.md

# 批量翻译:list.txt 每行一个 md 文件,# 开头的行与空行被忽略
md2zh --filelist list.txt

# 覆盖已存在的译文(默认跳过)
md2zh ABC.md --force

# 指定术语表文件
md2zh ABC.md --glossary g.json

# 管道过滤器:stdin 读入,译文写 stdout
cat ABC.md | md2zh -
```

单文件失败时返回具体退出码;批量模式下单个文件失败不中断,结束时在 stderr 汇总 `成功 N,跳过 M,失败 K`,存在失败则退出码为 1。

完整参数见 `md2zh --help`。

## 行为约定

- 代码块与行内代码不翻译(占位符保护,内容不会发送给 API);
- 译文格式与原文一致:frontmatter 的 key 与 `---` 标记不变、`**` 加黑成对包裹对应译文、链接 url 原样保留、表格行列不变;
- 校验失败自动重译修复,重试耗尽后该块保留原文并输出警告(文件仍算成功生成);
- stdout 只输出成功生成的译文路径(每行一个);进度、跳过提示、警告、汇总全部走 stderr;
- 错误消息格式:`md2zh: 上下文: 信息`;用户可见错误不打印 Python 堆栈;
- 输出编码 UTF-8;源文件须为 UTF-8(含 BOM 亦可),否则返回退出码 65。

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功(含全部跳过、含"回退保留原文"的文件) |
| 1 | 批量模式存在失败文件(汇总后) |
| 64 | 命令行用法错误(缺参数、FILE 与 --filelist 冲突等) |
| 65 | 术语表格式错误或源文件非 UTF-8 |
| 66 | 输入文件不存在/无法读取 |
| 74 | 输出文件写入失败 |
| 75 | 翻译 API 临时不可用(重试耗尽) |
| 130 | 用户 Ctrl-C 中断 |
| 141 | 下游管道提前关闭(SIGPIPE) |

## 术语表

格式为 JSON:`{"英文术语": "中文译法"}`,以【硬性要求】专名/术语对照附加到每段翻译请求,保证专名与术语译法统一。

```json
{
  "carbon fiber": "碳纤维",
  "transformer": "Transformer"
}
```

- `--glossary FILE` 指定术语表文件;
- 未指定时缺省加载 `~/.config/md2zh/glossary.json`(Windows 下为 `%USERPROFILE%\.config\md2zh\glossary.json`),文件不存在则视为无术语表;
- 优先级:命令行 `--glossary` > 默认文件。

## 翻译 API 说明

调用 Bilibili Index-Translate 免费公共接口(OpenAI 兼容):

```
POST https://index-translate.bilibili.com/v1/chat/completions
```

- 默认模型 `Index-Translate-35B-A3B`(可用 `--model`/`--api-base` 覆盖);
- 流式请求(规避非流式长文本 504)、`temperature=0.0`、关闭思维链输出;
- 网络错误自动重试 2 次,耗尽报退出码 75;
- 完整协议参考 `references/call_api.py`(支持图片翻译、本地代理等更多能力,本工具未复制)。

## 开发

```bash
python -m pytest -v            # 运行全部测试(76 项,API 已 mock,不依赖网络)
python -m pytest -v --junitxml=reports/junit.xml   # 生成测试报告
```

- 开发依赖仅 `pytest`;测试与实现遵循严格 TDD;
- 真实 API 不进自动化测试(免费公共服务,避免限流),手工验证步骤见 `docs/superpowers/specs/2026-10-12-md2zh-translator-design.md` §13;
- 目录约定:源码 `src/`、测试 `tests/`、样例数据 `data/`、报告 `reports/`、临时文件 `temp/`。

## 项目结构

```
├── src/md2zh/          # cli(参数与退出码) / api(请求与提示词) / markdown(块解析)
│                       # checks(格式校验) / translator(编排与批量)
├── tests/              # 76 项测试,API 全 mock
├── data/sample_en.md   # 手工验证样例
├── docs/superpowers/   # 设计规格与实施计划
└── references/         # Bilibili 官方参考实现(保持不动)
```

## 已知限制

- 极罕见格式的畸形 API 响应(`delta` 字段为非对象)可能与参考实现同样触发错误(不影响正常使用);
- frontmatter 识别与表格分块采用启发式:复杂嵌套 YAML frontmatter、紧凑表格等边界场景由校验+回退原文兜底,格式正确性优先;
- 校验失败兜底意味着极端情况下个别块可能保留英文原文,stderr 会给出明确警告。

## 参考

- 代码仓库:https://github.com/wzlu/bilibli-translator
- 变更日志:`CHANGELOG.md`
- 设计规格:`docs/superpowers/specs/2026-10-12-md2zh-translator-design.md`
- 实施计划:`docs/superpowers/plans/2026-10-12-md2zh-translator.md`
- API 参考实现:`references/call_api.py`

## 许可证

本项目采用 [MIT](LICENSE) 许可证。
