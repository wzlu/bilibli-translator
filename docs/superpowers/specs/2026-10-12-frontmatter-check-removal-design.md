# md2zh:frontmatter 校验移除 设计文档

- 日期:2026-10-12
- 状态:已确认(用户批准设计;SKILL.md 实测反馈驱动)
- 相关规格:`2026-10-12-repair-counter-and-bold-check-removal-design.md`(v0.2.4,加黑校验移除先例)、`2026-10-12-md2zh-translator-design.md`(保护管线与校验层)

## 1. 背景与目标

v0.2.4 发布后,用户实测 `skills/analyzing-local-repositories/SKILL.md`:frontmatter 校验失败 → 重译 2 次不收敛 → 整块回退英文原文。根因:`description` 为 YAML 折叠标量(`>-`),续行 `machine with no GitHub token or network: ...` 含冒号,被 `_keys` 启发式(每行按第一个冒号切分)解析为伪 key;译文把折叠标量合并为单行,key 集合 10→9 不一致。该回退使译文文件的 frontmatter 保留英文,与「全流程自动化」目标冲突。

用户裁决:frontmatter 按现有提示词规则翻译后**不再校验**(v0.2.4 加黑校验移除的同一理念)。

目标:①frontmatter 路径不校验、不重译、不回退,译文直接采用;②正文三重校验与修复循环、回退语义、退出码、流约定均不变。

## 2. 需求清单

1. `_translate_frontmatter` 不再走 `_repair`:单次调用直接返回译文,不校验、不重译、不回退;`source` 参数随警告消失而删除,调用点同步;
2. `checks.check_frontmatter` 与 `_keys` 删除(唯一消费者即 frontmatter 路径,不留死代码);`build_frontmatter_prompt` 提示词与 `markdown.split_frontmatter` 识别均不动;
3. 链接/表格/占位符三重校验、修复循环(REPAIR_RETRIES=2)、正文回退语义、退出码、流约定、换行保真均不变;
4. 删除 check_frontmatter 的 3 项测试;改写 2 项依赖回退行为的 translator 测试;终态 124 项全绿;
5. 真实 API 复验:SKILL.md frontmatter 不再回退(frontmatter 警告 0);opensre_system_prompt.md 回归(加黑 0、链接 ≤1 不变)。

## 3. 方案选型

- **方案 A(选定):完全移除 frontmatter 校验**。`_translate_frontmatter` 单次调用直接返回;删除 `check_frontmatter`/`_keys` 与其测试。与 v0.2.4 加黑移除同一理念,用户指令的字面执行。
- 方案 B:仅删 key 集合检查、保留 `---` 标记检查——保留半校验语义更复杂,且与「不再检查」指令不符,否。
- 方案 C:修复解析器(识别 YAML 块标量续行)保留校验——方向与用户决定相反,否。

## 4. 详细设计

### 4.1 frontmatter 翻译路径(translator.py)

`_translate_frontmatter` 整体替换为:

```python
def _translate_frontmatter(fm: str, glossary: list[str], api_base: str, model: str) -> str:
    """frontmatter 独立翻译:仅译 value,不校验、不重译、不回退。

    key 与 --- 标记由提示词约束保持;模型偏差直接采用(信任模型取舍,同 v0.2.4 加黑)。
    """
    return api.translate_text(api_base, model,
                              api.build_frontmatter_prompt(fm, glossary), MAX_TOKENS_SINGLE)
```

`_translate_document` 调用点改 `_translate_frontmatter(fm, glossary, api_base, model)`(`source` 参数删除:frontmatter 路径不再产生警告)。

API 网络失败仍经 `translate_text` 抛 `TranslateError` → `translate_file` 既有 75 路径,与现状一致。

### 4.2 校验层(checks.py)

删除 `check_frontmatter` 与 `_keys`。模块 docstring「块级格式校验」保持准确(剩余三项均为块级)。删除后 checks.py 恰为链接/表格/占位符,与 CHANGELOG 0.2.4「三重」措辞自然对齐(消除此前「三重/四项」表述歧义)。

### 4.3 兼容性与风险(如实声明)

- frontmatter 一律采用译文,不再回退英文——SKILL.md 类失败消失;
- 残余风险:模型若改 key 或丢 `---` 标记,无兜底直接写出,可能破坏 frontmatter 结构。由 `build_frontmatter_prompt` 既有约束「key 保持不变」「保持首尾 --- 标记、行数与整体结构不变」压制;属「信任模型」取舍,与官方插件哲学一致;
- 警告格式契约(v0.2.1):「frontmatter重译耗尽」警告不再存在(该警告本就仅 frontmatter 路径产生);
- `markdown.split_frontmatter` 识别启发式(首块须含冒号行)不动,仍存在识别边界,但不再引发任何失败。

### 4.4 范围界定

仅 frontmatter 校验移除。正文三重校验、修复循环、回退语义、提示词、占位符管线、退出码、流约定均不动。

## 5. 测试计划(严格 TDD)

| 测试 | 断言 |
|---|---|
| 删除:check_frontmatter 3 项 | `test_check_frontmatter_ok` / `test_check_frontmatter_key_changed` / `test_check_frontmatter_missing_markers` 连同函数一并删除 |
| 改写:frontmatter 改 key 直接接受(translator) | 原 `test_frontmatter_fallback_to_original` 改为:fake 返回改 key 的 frontmatter → 译文文件含改后 key、API 恰 2 次调用(frontmatter + 正文各 1 次,无重译) |
| 改写:frontmatter 无修复警告(translator) | 原 `test_document_frontmatter_warning_names_source` 改为:经 `_translate_document` 的 frontmatter 路径无重译、结果含译文 frontmatter、stderr 不含「frontmatter」 |
| 既有其余测试零改动 | 127 − 3(删) + 0(改写 1:1)= **124** 项全绿;`test_frontmatter_translated` 断言与 fake 序列不变(2 次调用) |

真实 API 复验(发布前门槛,控制方执行):

1. `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\skills\analyzing-local-repositories\SKILL.md" --force`:frontmatter 警告 0、`SKILL_zh.md` 的 frontmatter 为中文(不再回退);
2. `md2zh.exe "D:\ops\opensre\core\agent_harness\prompts\opensre_system_prompt.md" --force`(用户常设验证指令):加黑 0、链接 ≤1(回归确认正文路径不受影响)。

不达则裁决(回退对应改动或接受并如实记录)。

## 6. 文档与发布

- 版本按语义化版本提升至 **0.2.5**(patch,与 v0.2.4 加黑移除同口径);
- CHANGELOG `[0.2.5]` `### 变更`:不再校验 frontmatter,译文直接采用(残余风险如实声明);
- CLAUDE.md:checks.py 行 →「纯函数块级校验:链接、表格、占位符」;「frontmatter 独立翻译」条目 →「仅译 value,key 与 `---` 标记由提示词约束保持,不校验不回退」;Important Notes 已知限制删除 frontmatter 冒号启发式引发回退的失效表述;
- README:30/77「key 与 `---` 标记不变」→「由提示词约束保持」;README:167「frontmatter…由校验+回退原文兜底」改写(frontmatter 不校验;正文表格等仍校验兜底);徽章与测试数 124;
- Recent Updates 顶部新条目(真实 API 复验结果回填);台账记录。

## 7. 非目标(YAGNI)

- YAML 解析器改进(块标量/嵌套识别)——校验移除后无必要;
- frontmatter 提示词改动(「现有规则」不动);
- 正文三重校验、修复循环、fix_notes 的任何调整;
- `split_frontmatter` 识别启发式调整。
