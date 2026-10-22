# md2zh 批量模式前置判断顺序优化设计规格

日期:2026-10-22 版本:v0.7.0(候选)

## 1. 背景与目标

批量重跑(增量翻译)是主要使用场景:文件列表中绝大部分文件的译文(`*_zh.<ext>`)已存在,真正需要翻译的只是少数新增/修改文件。当前 `run_batch` 的前置判断顺序为「先忽略名单、后(worker 内)译文已存在」,导致已存在译文的文件白白承担:忽略通配正则匹配(O(m) 次 fullmatch)、线程池任务提交、worker 内 `isfile` 与 `exists` 两次 stat。

本版本调整批量模式前置判断顺序:**非 `--force` 下先判断「译文已存在」,命中即计跳过并短路**,不再做忽略匹配与线程池提交。目标:前置判断成本与实际命中率分布对齐(绝大多数文件命中「译文已存在」),跳过文件的处理路径最短。

## 2. 现状分析

`translator.py` 当前实现(v0.6.0):

- `run_batch` 主线程:`is_ignored(p)` 命中 → 计「忽略」;未命中 → 提交线程池。
- `IgnoreMatcher.is_ignored`:精确路径 set O(1);通配规则逐条预编译正则 `any(rx.fullmatch(norm) for ...)`,每文件 O(m) 次匹配 + 一次 `_norm`(abspath/normcase)。
- worker 内 `translate_file`:`isfile(src)` → `exists(_zh_path(src))` 命中且非 force → 计「跳过」。

已存在译文的文件在跳过前共付出:O(m) 正则匹配 + 1 次线程提交 + 2 次 stat。

## 3. 方案选型

| 方案 | 内容 | 评估 |
|---|---|---|
| **A:主线程前置「译文已存在」短路** | `run_batch` 循环改「exists(译文)→ is_ignored → 提交」;`translate_file` 不变 | **选定**:改动集中一个函数,收益与命中率分布对齐 |
| B:A + scandir 目录缓存 | 每目录一次列举建集,exists 变 set 查找 | 不选:仅网络盘/超大目录有感,YAGNI |
| C:仅合并忽略正则 | m 条正则合并单条 alternation | 不选:不解决线程池提交,m 通常很小 |

## 4. 详细设计

### 4.1 改动点(仅 `translator.py` 的 `run_batch`)

```python
# 前置判断顺序:译文已存在(非 force)→ 忽略名单 → 提交线程池
for p in paths:
    if not force and os.path.exists(_zh_path(p)):
        _warn(f"md2zh: 跳过 {p}: 译文已存在(使用 --force 覆盖)")
        skipped += 1
    elif ignore_matcher is not None and ignore_matcher.is_ignored(p):
        _warn(f"md2zh: 忽略 {p}: 命中忽略列表")
        ignored += 1
    else:
        todo.append(p)
```

- `translate_file` 保持不变:内部 `isfile`/`exists` 双查保留,供 `run_single` 复用,批量 worker 内作 TOCTOU 防线(多一次 stat,可忽略)。
- 跳过警告文本与现有一致;`_warn` 串行化路由不变;汇总「成功/跳过/忽略/失败」与退出码契约(0/1)不变。
- `run_batch` docstring 更新:「非 --force 下译文已存在优先于忽略;--force 下忽略优先(不受影响)」。

### 4.2 数据流

- 译文已存在 + 非 force:主线程 1 次 `exists` stat → 计跳过(不再做忽略匹配、isfile、线程提交)。
- 译文不存在 + 命中忽略:与现在一致(忽略优先于扩展名/存在性检查)。
- 译文不存在 + 未忽略:提交线程池,worker 内原流程不变。
- `--force`:exists 不短路,忽略优先语义与现在完全一致。

### 4.3 语义变更(三项,已与用户裁决确认)

1. **交叉情形计数倒转**:文件同时「译文已存在」且「命中忽略」时,由计「忽略」改为计「跳过」(非 force)。裁决:接受倒转——能被列入待译清单的文件本就极少命中忽略,且「跳过」对已有译文文件更直观。
2. **跳过警告输出时机**:由「随 as_completed 乱序」改为「主线程前置、按文件列表顺序输出」。翻译完成输出仍乱序(按设计)。
3. **边缘情形**:「源文件已删但译文存在」由「失败(66)」改为「跳过」(exists 先于 isfile 短路)。罕见情形,接受。

## 5. 错误处理

无新错误路径。`os.path.exists` 对权限类 OSError 返回 False(不抛),前置检查失败自然落入原流程。退出码契约不变(0/1/64/65/66/74/75/130/141)。

## 6. 测试计划(严格 TDD,先写失败测试)

新增于 `tests/test_translator.py`,沿用现有 monkeypatch/capsys 风格:

1. 译文已存在 + 非 force → 计「跳过」、`translate_file` 不被调用、退出 0;
2. 译文已存在 + 命中忽略 + 非 force → 计「跳过」不计「忽略」(交叉裁决锁定);
3. 译文已存在的文件不进入线程池(仅无译文文件被提交);
4. 源文件已删但译文存在 → 计「跳过」(行为变更 3 锁定);
5. 跳过警告前置按文件列表顺序输出。

现有 247 项测试预期全部保持通过:`force` 下忽略优先不变(`test_run_batch_ignore_wins_over_force` 仍成立);无译文文件路径不变。如有因语义反转失效的旧断言,按新裁决修正。

## 7. 文档同步

- CLAUDE.md:架构描述与「忽略优先于扩展名/存在性检查」语义口径更新;
- CHANGELOG.md:补录本版本条目;
- 版本号 `__init__.py`/`pyproject.toml` 双处同步(发布时)。

## 8. 不做的事(YAGNI)

- scandir 目录缓存(方案 B):无实测佐证收益;
- 忽略正则合并(方案 C):m 小,收益微;
- `translate_file` 增加「跳过 exists 检查」参数:双查代价一次 stat,不值得增加接口复杂度。
