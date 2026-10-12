# md2zh:重译计数器修复与加黑校验移除 设计文档

- 日期:2026-10-12
- 状态:已确认(用户批准设计;用户实测反馈驱动)
- 相关规格:`2026-10-12-warning-file-context-design.md`(警告格式)、`2026-10-12-url-placeholder-and-sparse-prompt-design.md`(v0.2.3)

## 1. 背景与目标

用户实测(opensre 系列文件)发现两个问题:

1. **重译计数器越界**:耗尽路径打印 `块校验失败,重译(3/2)`——`_repair` 共 3 次调用(1 次初译 + 2 次重译),但每次失败都按 `attempt + 1` 打印,末次(第 2 次重译)失败打印成 3/2,超过声明的重译上限 2;
2. **加黑校验导致残余整块失败**:v0.2.3 稀疏化提示词后,模型自行增删 `**`(如 `2→4`、`14→12`)仍触发 `check_bold` 失败 → 重译不收敛 → 整块回退英文原文。校验加黑在「信任模型处理格式标记」的取舍下收益为负,用户决定**不再校验加黑标记**。

目标:①计数器语义正确(仅在有后续重译时打印 `重译(x/2)`,无越界);②加黑标记不再参与校验,校验管线由四重(加黑/链接/表格/占位符)收敛为三重(链接/表格/占位符)。

## 2. 需求清单

1. 耗尽路径的警告序列恰为 `重译(1/2)`、`重译(2/2)`、`重译耗尽`,**不出现** `重译(3/2)`;成功路径(第 1 次重译即通过)输出与现状一致;
2. `_check_block` 检查序列移除 `check_bold`;`checks.check_bold` 与其 4 项测试删除(不留死代码);`build_frontmatter_prompt` 约束列表中「`**` 加黑标记必须成对出现…」一行删除(该约束从未被执行,删除保证言行一致);
3. 链接/表格/占位符三重校验与修复循环、回退语义、退出码、流约定均不变;
4. 既有测试中依赖加黑触发修复的一项改写为链接触发;终态 127 项全绿。

## 3. 方案选型

- 计数器:方案 A(选定)——`_repair` 打印前加 `if attempt < REPAIR_RETRIES:` 守卫。方案 B(末次改印 `2/2`)会出现两行 2/2,语义混乱,否;方案 C(初译单独措辞)改动 v0.2.1 警告契约与测试面,否。
- 加黑校验:方案 A(选定)——从管线移除并删除函数/测试(死代码不保留)。方案 B(保留函数不调用)违背 YAGNI,否;方案 C(降级为仅警告)引入新失败语义分层,复杂度无收益,否。

## 4. 详细设计

### 4.1 计数器修复(translator.py `_repair`)

循环内警告行加守卫(语义:「重译(x/2)」= 第 x 次重译即将进行):

```python
        if attempt < REPAIR_RETRIES:
            sys.stderr.write(f"md2zh: 警告: {prefix}{label}校验失败,重译({attempt + 1}/{REPAIR_RETRIES}): {';'.join(problems)}\n")
```

末次失败不再打印重译行,直接落入循环后的「重译耗尽,保留原文」行(该行已携带完整问题列表,信息无损)。frontmatter 标签走同一 `_repair`,自动受益。

### 4.2 加黑校验移除

- `src/md2zh/translator.py` `_check_block`:检查序列 `(checks.check_bold, checks.check_links, checks.check_tables, checks.check_placeholders)` → `(checks.check_links, checks.check_tables, checks.check_placeholders)`,docstring「块级校验汇总:加黑/链接/表格/占位符。」→「块级校验汇总:链接/表格/占位符。」;
- `src/md2zh/checks.py`:删除 `_BOLD = "**"` 常量与 `check_bold` 函数(含 docstring);
- `src/md2zh/api.py` `build_frontmatter_prompt`:约束列表删除 `"** 加黑标记必须成对出现、包裹对应的译文词语。"` 行。

### 4.3 兼容性与风险(如实声明)

- 模型自行增删 `**` 的译文直接通过校验——加黑类重译/回退消失(opensre 类文件预期归零);
- 残余风险:译文可能含**不成对的 `**`**,渲染时破坏 markdown 结构(加粗吞并后续文本)。这是「信任模型处理格式标记」的取舍,与官方插件哲学一致;链接/表格/占位符三重硬校验保留;
- 警告格式契约(v0.2.1)除「不再出现 3/2」外不变;`_check_block` 仅内部调用,无外部兼容面。

### 4.4 范围界定

仅计数器显示与加黑校验。链接/表格/占位符校验、修复循环次数(REPAIR_RETRIES=2)、回退语义、frontmatter 校验(check_frontmatter)均不动。

## 5. 测试计划(严格 TDD)

| 测试 | 断言 |
|---|---|
| 新增:重译计数器不越界(translator) | 耗尽路径 stderr 含 `重译(1/2)`、`重译(2/2)`、`块重译耗尽`,**不含** `重译(3/2)`;RED:旧实现含 `重译(3/2)` |
| 新增:加黑漂移通过(translator) | `_translate_chunk("**bold** 内容", ...)` 译文为 `粗体内容`(丢失 `**`)→ 被接受、结果即译文;RED:旧实现 3 次失败后回退原文 ≠ 译文 |
| 改写:修复后成功(translator) | `test_chunk_repair_then_success` 触发机制由「加黑不成对」改为「链接丢失」:输出序列 `["没有链接的译文", "[译文](https://x)"]`,断言结果 `[译文](https://x)` |
| 删除:check_bold 4 项(checks) | `test_check_bold_ok` / `test_check_bold_count_mismatch` / `test_check_bold_unpaired` / `test_check_bold_odd_source_not_flagged` 连同函数一并删除 |
| 既有其余测试零改动 | 129 − 4(删) + 2(增) = **127** 项全绿;`build_frontmatter_prompt` 既有测试不引用被删约束行(已核实) |

真实 API 复验(发布前门槛,控制方执行):`md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md"`。验收:加黑类失败 = 0;链接类 ≤1(错位类,v0.2.3 已知残余)。不达则裁决。

## 6. 文档与发布

- 版本按语义化版本提升至 **0.2.4**(patch);
- CHANGELOG:`### 修复`(重译计数器越界)+`### 变更`(不再校验加黑标记,块级校验三重:链接/表格/占位符;加黑由模型与提示词约束自行保持);
- CLAUDE.md:Architecture 的 checks.py 描述删「加黑配对」;Overview 版本 0.2.4 与测试数 127;Recent Updates 顶部新条目(真实 API 复验结果回填);README 徽章与测试数、pyproject 版本按先例同步。

## 7. 非目标(YAGNI)

- 修复循环次数调整(REPAIR_RETRIES 仍为 2);
- 修复说明 fix_notes 措辞变更;
- 链接错位类失败的修复(占位符序列重排/fix_notes 具体化)——另行评估;
- 表格/占位符校验的任何调整。
