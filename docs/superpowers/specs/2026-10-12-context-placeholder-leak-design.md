# md2zh:分段上下文占位符泄漏修复 设计文档

- 日期:2026-10-12
- 状态:已确认(用户批准设计;根因经 systematic-debugging 证据链锁定)
- 相关规格:`2026-10-12-md2zh-translator-design.md`(分段与修复循环)、`2026-10-12-warning-file-context-design.md`(警告前缀)

## 1. 背景与目标

批量翻译实测(opensre_system_prompt.md / skills/AGENTS.md)出现:

```
md2zh: 警告: D:\ops\...\opensre_system_prompt.md: 块重译耗尽,保留原文: 加黑标记 ** 数量不一致(原文 0 个,译文 34 个);出现未知占位符: ['@@@INLINE_16@@@', ...]
```

根因(证据链已闭合):长文分段时每块提示词携带上一块**原文+译文尾部各 400 字符**作「上下文参考」,而占位符在整篇译完后才还原——上下文中的 `@@@INLINE_n@@@` 令牌被模型带入/转写进输出,校验时因不属于本块集合被判「未知占位符」,重译(每次携带同一上下文)必然失败,最终整块回退英文原文。

目标:消除上下文中的占位符泄漏源——**上下文在发送前还原为真实代码内容**,并以提示词硬约束阻止模型输出上下文内容。

## 2. 需求清单

1. 分段上下文(原文尾部与译文尾部)在进入 API 请求前,占位符全部还原为原始内容;
2. 携带上下文的提示词追加一条硬约束:输出不得包含上下文参考的任何内容;
3. 现有 120 项测试全部保持通过(受影响断言在 TDD 内同步更新);
4. 校验层、回退语义、退出码、流约定均不变。

## 3. 方案选型

- **方案 A(选定):上下文发送前还原 + 提示词加固**。`_translate_document` 把 `mapping` 下传 `_translate_long`,上下文拼接前还原;`build_prompt` 在 context 非空时追加硬约束。直接消除泄漏源,改 2 个文件,与官方 Chrome 插件「占位符不出翻译单元」原则同构。
- 方案 B(删除上下文段):术语一致性损伤,官方基准已证分块翻译一致性本就弱,再删上下文雪上加霜,不采用。
- 方案 C(校验放宽,容忍上下文占位符集合):治标——泄漏照旧发生,只是警告消失,不采用。
- 方案 D(占位符按块局部编号+译后立即还原,即官方插件做法):效果同 A,但动编号/映射/还原全链,影响面大,不采用(YAGNI)。

## 4. 详细设计

### 4.1 数据流

```
_translate_document: mapping = markdown.protect_code_blocks(rest) 的返回值
  └─ _translate_long(protected, glossary, api_base, model, mapping=mapping, source=source)
       ├─ 每块翻译(与现状一致)
       └─ prev_context = 还原后的上一块原文/译文尾部(见 4.2)
            └─ _translate_chunk(..., context=prev_context)  → api.build_prompt(..., context=...)
```

占位符令牌自此不再进入任何 API 请求;模型可见的上下文与文件原文同形(真实代码、真实格式标记)。

### 4.2 签名与实现改动

| 函数 | 改动 |
|---|---|
| `_translate_document` | 调 `_translate_long` 时传 `mapping=mapping`(已有变量) |
| `_translate_long` | 增 keyword-only **必填** `mapping: dict[str, str]`;上下文构建改为**先整块还原、后切尾部**,避免切在占位符令牌中间产生碎片;实现如下: |
| `_translate_chunk` | 不动 |
| `_repair` | 不动 |
| `build_prompt` | `context` 非空时,约束列表追加一条编号硬约束(见 4.3) |

`_translate_long` 上下文构建代码:

```python
src_tail = markdown.restore_code_blocks(chunk, mapping)[-half:]
dst_tail = markdown.restore_code_blocks(translated, mapping)[-half:]
prev_context = f"原文: {src_tail}\n译文: {dst_tail}"
```

说明:先还原整块再切尾部,还原后文本长度与受保护文本不同(代码内容比占位符长),尾部窗口自然滑到「真实文本的最后 400 字符」——语义更正确,且不可能切出半截占位符。

### 4.3 提示词变更(api.py)

`build_prompt` 在 `_append_requirements` 之后、编号生成之前,`context` 非空时追加:

```python
if context:
    constraints.append("【硬性要求】输出仅包含【源文】的译文,不得翻译或输出【上下文参考】中的任何内容。")
```

该行为最后一条编号约束,与术语表/修复说明的【硬性要求】格式一致(对齐 instTrans 训练格式)。头部「(仅供术语一致参考,不要翻译本段)」保留不动。

### 4.4 兼容性

- 无上下文路径(单次调用、frontmatter):提示词与现状**逐字节一致**,零回归面;
- 分段路径:上下文文本还原(无代码文档还原为 no-op,内容不变)+ 约束列表多一行硬约束;
- 直接调用 `_translate_long` 的既有测试需补 `mapping=` 实参(传 `{}` 或真实映射),TDD 内完成;
- 还原为幂等操作:全文 mapping 对尾部/整块做 replace,不存在的令牌不命中;文档级还原(translator.py:105)仍保留,行为不变。

### 4.5 范围界定

仅长文分段路径(>15000 字符)。frontmatter、单次调用、stdin 模式无上下文,不受影响。占位符编号方案、校验规则、回退语义、警告格式(含 v0.2.1 路径前缀)全部不变。

## 5. 测试计划(严格 TDD)

新增测试(先写、确认 RED,再实现至 GREEN):

| 测试 | 断言 |
|---|---|
| `_translate_long` 上下文占位符已还原(translator) | 构造 >15000 字符长文(≥2 块),首块尾部含行内代码;mock `api.translate_text` 捕获各次 prompt。第二块请求的 prompt:①【上下文参考】与【源文】之间的上下文段含还原后的代码文本;②上下文段内 `@@@[A-Z]+_\d+@@@` 正则零命中;③【源文】段仍含本块占位符 |
| `build_prompt` 带上下文追加隔离约束(api) | 带 context:编号约束最后一条为「输出仅包含【源文】的译文…」;不带 context:约束行数与现状一致且不含该行 |
| 既有 120 项全绿(回归) | 受影响断言同步更新:`_translate_long` 调用点补 `mapping=`;`build_prompt` 带 context 的提示词文本断言按新输出更新 |

覆盖边界:无代码长文(还原 no-op、约束行仍追加)、上下文段无占位符残留、最终文件级还原不受影响(既有 restore 测试保障)。

## 6. 文档与发布

- CHANGELOG 新增「修复」小节(分段上下文占位符泄漏);
- 版本号按语义化版本提升至 0.2.2(patch);
- CLAUDE.md:Overview 版本与测试数、Recent Updates 补条目;README 徽章与测试数、pyproject 版本同步(按 v0.2.1 先例)。

## 7. 非目标(YAGNI)与残余风险

- 非目标:块内段落级抢救(截断时保留完整段落);上下文照抄检测;占位符局部编号;上下文瘦身(只留译文);分段大小调整(15000/3000 维持,研判结论已另行给出);
- 残余风险(如实声明):模型若仍照抄上下文中的**还原后真实代码**,会以「代码混入译文且通过校验」的形式静默污染。由提示词硬约束压制;不做内容级检测(检测成本与误报高于收益)。此风险在既有「回退原文」失败模式之上,不改变损害有界性(最坏仍为该块内容有瑕疵,可人工复查)。
