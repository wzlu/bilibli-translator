# md2zh 多格式支持(HTML/TXT)设计规格

日期:2026-10-15 版本:v0.6.0

## 1. 背景与目标

md2zh v0.5.0 仅接受 `.md` 文件(`translator.py:74-75` 硬性拦截),不支持 HTML 等其他文本格式。本版本将 CLI 扩展为多格式翻译工具:

- 新增 HTML 与 TXT 两种格式(保留 MD);
- 格式按扩展名自动推断,新增 `--format` 显式覆盖;
- 新增 `txt2zh` 命令别名(与 md2zh 同一入口);
- 退出码契约、批量/忽略/术语表/修复循环/ollama/CRLF 保真等既有能力保持不变。

核心结论:管线 ~80% 格式无关(API 传输/SSE/重试、批量线程、修复循环、原子写、退出码、术语表、忽略列表),格式接缝极小——全为 `str` + 占位符 `dict` 流转,无块对象。改造而非新建(决策分析见 §3.1)。

## 2. 需求清单

- **R1 格式推断**:按扩展名(小写)推断——`.md/.markdown→md`、`.html/.htm→html`、`.txt→txt`;未知扩展名回落 `md`(向后兼容,不再拒绝非 .md 文件)。
- **R2 --format 显式覆盖**:`--format {md,html,txt}`;非法值退出 64;stdin 模式(无扩展名)缺省 `md`;批量模式显式 `--format` 全局覆盖、缺省逐文件推断。
- **R3 HTML 保护**:标签、属性、注释、doctype、实体、`script/style/pre/code` 原始块全部占位保护(模型不可见);仅文本节点送译;还原字节级保真(标签/属性/实体与源文逐字节一致);不引入解析器、不重序列化。
- **R4 TXT 直通**:零保护,空行分段。
- **R5 校验分派**:md=[链接,表格,占位符];html=[占位符,html 文本];txt=[占位符]。校验失败进入既有修复循环,耗尽采用译文(不回退语义不变)。
- **R6 提示词分派**:各格式自带约束文本,`build_prompt` 按格式注入;md 默认行为逐字节不变。
- **R7 退出码契约不变**:0/1/64/65/66/74/75/130/141;EX_NOINPUT 仅保留「文件不存在」。
- **R8 txt2zh 别名**:`pyproject.toml` console_scripts 加一行;usage/--version 中程序名随入口名显示(回落 `md2zh`)。
- **R9 版本 0.6.0** 双处同步(`__init__.py`、`pyproject.toml`)。
- **R10 运行期依赖仅 requests**;零新依赖(HTML 实体表用 stdlib `html.entities`)。

## 3. 方案选型

### 3.1 改造本项目 vs 新建项目

| 维度(权重) | 改造本项目 | 新建独立项目 |
|---|---|---|
| 开发工作量(30) | 4/5:复用全部管线 | 2/5:重写 API 层+编排层+测试基建 |
| 长期维护(25) | 4/5:单仓,修复惠及全格式 | 2/5:双仓漂移(UA 412/SSE 分片/线程池关停等历史修复需双份同步) |
| markdown 回归风险(15) | 3/5:164 项测试+适配器隔离 | 5/5:零触碰 |
| 新格式边际成本(15) | 4/5 | 4/5:两者都要同样的适配机制 |
| 命名定位(10) | 3/5:需 txt2zh 别名 | 5/5 |
| 基础设施复用(5) | 5/5 | 1/5 |
| **加权合计** | **380** | **300** |

判定:两向门决策(适配层增量化,失控可剥离);反事实检验——从零设计多格式翻译器也会得到「共用管线 + 每格式适配器」架构。**结论:改造本项目。**

### 3.2 HTML 保护机制选型(spike 实证)

陷阱语料 16 项(引号内 `>`、转义/十六进制/无分号实体、属性内 `&`、跨行/大写标签、script 内 `</script>` 字面量、style 内 `>`、注释内 `-->`、doctype+minified、void 元素、无引号属性 `>`、pre/code 整块、文本裸 `<`)+ CRLF 完整页面,Python 3.11 实测(`temp/html_spike.py`):

| 机制 | 实测结果 | 缺陷 |
|---|---|---|
| 正则占位 | 理论分析即否决 | 属性内 `>` 误切(属性泄漏给模型且还原错位)、裸 `<` 误判、无分号实体盲区 |
| html.parser + 偏移切片 | 4 项失败 | legacy 实体(`&nbspb`)字面泄漏;script/style/pre/code 的 CDATA 内容需额外缓冲管理;保真依赖 CPython 不做 CRLF 归一化的内部行为 |
| **自研引号感知状态机** | **16/16 + 页面全 PASS** | 无(修正 2 处后:裸 `<` 首字符检查、实体表最长匹配) |

**结论:自研引号感知状态机**——与项目手写纯函数风格一致,行为完全可控、可单元测试,~130 行。

## 4. 详细设计

### 4.1 模块结构(导入方向单向无环)

```
formats.py(注册表)→ markdown.py / html.py / txt.py / checks.py
translator.py → formats.py + api.py
api.py → markdown.py(仅默认约束)
cli.py → translator.py / api.py
```

共享工具(贪心装包 `pack_blocks`、空行切分 `split_blank_lines`、朴素还原 `restore_code_blocks`)留在 `markdown.py`(模块升格为「文本分段与占位符通用工具 + Markdown 适配实现」),html/txt 单向导入 markdown,规避循环导入。

### 4.2 格式注册表(formats.py,新)

```python
@dataclass(frozen=True)
class Format:
    name: str
    extensions: tuple[str, ...]
    split_frontmatter: Callable[[str], tuple[str | None, str]]
    protect: Callable[[str], tuple[str, dict[str, str]]]
    restore: Callable[[str, dict[str, str]], str]
    chunk_text: Callable[[str, int], list[str]]
    validators: tuple[Callable[[str, str], list[str]], ...]
    constraints: tuple[str, ...]

FORMATS: dict[str, Format]          # md/html/txt 三条目
get_format(name) -> Format          # 未知名抛 KeyError(库级契约,CLI choices 拦截)
infer_format(path) -> str           # 扩展名小写映射,未知回落 "md"
```

### 4.3 HTML 适配器(html.py,新)——状态机七分支

`protect(text) -> (protected, mapping)` 单遍扫描:
1. `<!--` → 保护至首个 `-->`(无闭合则余文整体按原文输出);
2. `<!` → 声明/doctype,保护至 `>`(CDATA 内含 `>` 为已知限制);
3. `</` → 结束标签,保护至 `>`;
4. `<`+字母 → 开始标签:**引号感知**扫描至引号外的 `>`;标签名为 script/style/pre/code(不区分大小写)→ **原始文本块**整体保护至首个 `</name`(不区分大小写,与 HTML 规范一致);
5. `<`+非字母/`!`/`/` → 字面 `<`("5 < 10" 不误判);
6. `&` → 实体:数字 `&#n;`/`&#xH;`(分号可省);命名按 `html.entities.html5` 表**最长匹配**(无分号仅保护表内 legacy 名,未知 `&xyz` 字面);
7. 其余字符照抄。

占位符令牌:`@@@HTMLBLOCK_n@@@`(注释/script/style/pre/code 块)、`@@@HTMLTAG_n@@@`(其余标签与声明)、`@@@HTMLENT_n@@@`(实体),统一匹配 `checks.py:6` 正则。

**不变量(测试锁定)**:mapping 值永不包含占位符令牌(保护顺序:先块、再标签、后实体)→ 朴素顺序 replace 还原往返字节级安全。

其余接口:`restore` 委托 `markdown.restore_code_blocks`;`split_frontmatter` 恒 `(None, text)`;`chunk_text` = 每个占位符令牌边界 + 空行 单次正则切分后经 `markdown.pack_blocks` 装包(minified HTML 靠令牌边界分段;令牌原子不跨块,还原文档级全局拼回)。

### 4.4 TXT 适配器(txt.py,新)

`protect(text) -> (text, {})` 直通;`restore` 委托通用替换(空映射恒等);`split_frontmatter` 恒 `(None, text)`;`chunk_text` = `split_blank_lines` + `pack_blocks`(无表格/列表合并)。

### 4.5 校验(checks.py 增量)

`check_html_text(src, dst)`:计数式——保护态 src 中合法裸 `<`/`&` 可能残留,故「dst 裸 `<` 或 `&` 计数超过 src 即计问题」(零假阳性,防模型自造标签/实体)。

### 4.6 提示词(api.py 增量)

- `FORMAT_CONSTRAINTS` 三条文案逐字迁移至 `markdown.CONSTRAINTS`(各格式约束自包含于适配器模块)。
- `build_prompt(text, glossary, fix_notes="", context="", constraints=None)`:缺省回落 `markdown.CONSTRAINTS`,默认输出与现状逐字节一致。
- `build_frontmatter_prompt` 不动(仅 md 路径触达:`fm is None` 自然跳过)。

### 4.7 编排层(translator.py 增量)

- `translate_file(..., fmt=None)`:删除 `.md` 门;`fmt` 缺省按扩展名推断;`formats.get_format(...)` 传入 `_translate_document`。
- `_translate_document/_translate_long/_translate_chunk/_check_block` 增 `fmt: Format | None = None`(缺省回落 md,保 11 处既有直调测试);调用点改派 `fmt.split_frontmatter/protect/restore/chunk_text/validators/constraints`。
- `run_single/run_batch` 增 `fmt: str | None = None` 透传(批量 None=逐文件推断);`run_stdin` 增 `fmt: str = "md"`。
- `_repair`、`_zh_path`、`_atomic_write`、退出码、frontmatter 翻译、`parse_filelist` 零改动。

### 4.8 CLI 层(cli.py 增量)

- `_prog()`:取 `os.path.basename(sys.argv[0])` 去 `.exe` 后缀,仅 `md2zh`/`txt2zh` 采用,否则回落 `md2zh`(pytest 环境保断言);`prog` 与 `--version` 改动态。
- 新增 `--format {md,html,txt}`(choices,默认 None);description/help/epilog 更新(示例补 html/txt/txt2zh/`--format html` stdin 行)。
- main 三分支透传 `fmt`;`--ollama` 分支零改动(正交)。

### 4.9 分派总表

| 格式 | 提示词约束(占位符禁译为通用条) | 校验器 | 分段策略 | frontmatter |
|---|---|---|---|---|
| md | 保留 markdown 语法;表格行列保持(现三条原样迁移) | links / tables / placeholders | 现状(空行+表格合并) | 有(专用提示词) |
| html | 只输出纯文本,不得添加标签/实体/格式标记 | placeholders / html_text | 每个占位符令牌边界 + 空行 | 无 |
| txt | 只输出纯文本,不得添加格式标记 | placeholders | 空行 | 无 |

## 5. 测试策略

- 新增:`tests/test_formats.py`(注册表/infer/回落)、`tests/test_html.py`(spike 16 陷阱语料 + 往返恒等性质测试 + 映射不变量 + chunk 不变量 + CRLF 页面)、`tests/test_txt.py`、`tests/test_checks.py` 追加 `check_html_text` 4 例、`tests/test_api.py` 追加 constraints 2 例、`tests/test_translator.py` 重写 1 例 + 新增 5 例、`tests/test_cli.py` 追加 7 例。
- 存量破坏面(必改):`test_translate_file_not_md`(:77-83)重写为非 .md 推断成功;`test_version.py:5` 改 0.6.0;`test_translator.py:497/:502` 的 `translator.markdown` 改直接导入 `markdown`;三处 `fake_run_batch`(:209/:268/:290)机械加 `fmt=None`。
- 存量零改动(回归验证):test_markdown.py 18 项(抽取无损)、test_api.py 22 项(默认回落逐字节一致)、test_checks.py 8 项、test_ignore.py 19 项、其余 translator/cli 测试(内部函数 `fmt=None` 默认保 11 处直调;`_prog()` 回落保 `"md2zh"` 断言)。
- 预计新增约 45 项,总约 209 项。

## 6. 手工验证清单(真实 API,不进自动化)

1. `md2zh data/sample_en.html --force` → `*_zh.html` 标签/属性/实体字节级完好、无 `@@@` 残留、零警告;
2. `md2zh data/sample_en.txt` 直通翻译;
3. `cat x.html | md2zh - --format html` stdin 模式;
4. `txt2zh --version` 与 usage 显示 `txt2zh`;
5. `--filelist` 混合格式批量(逐文件推断,乱序输出);
6. 回归:md 单文件翻译零警告。

## 7. 文档与发布

- spec/plan 成对落盘 `docs/superpowers/`;
- `data/sample_en.html`、`data/sample_en.txt` 样例(真实 API 产物不入库);
- README(特性/快速开始/行为约定/项目结构/已知限制/参考/测试徽章)、CHANGELOG v0.6.0 条目、CLAUDE.md 同步;
- 发布收尾:fast-forward 合并回 main、推送 origin、打 tag v0.6.0、CLAUDE.md 回填真实 API 验证结果。

### 已知限制(终审随行发布)

- HTML 属性(alt/title/placeholder)不译;`lang`/`meta` 不改写。
- HTML5 双重转义态(`<!--<script>` 在 script 内不闭合)不实现;CDATA 内含 `>` 在首个 `>` 截断;textarea/title 的 RCDATA 语义不特判。
- 正文以 `<`+字母 开头误判为标签(如 "<apple")——最坏该段误保护不翻译。
- 畸形 HTML(未闭合标签/引号):余文不保护地进入送译文本(protect→restore 往返恒等;译文若改写余文将触发裸字符校验警告)。
- 模型可能自造 `**` 等非 HTML 格式标记,校验无法拦截(提示词硬约束缓解)。
- 源文字面 `@@@...@@@` 与占位符令牌冲突概率极低(与 md 同取舍)。
- 未知扩展名回落 md;txt2zh 调用的 stderr 前缀仍为 `md2zh:`;库级 fmt 非法值仅库调用可达。
