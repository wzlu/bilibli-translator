# md2zh:--ollama 本地翻译后端 设计文档

- 日期:2026-10-13
- 状态:已确认(用户批准设计)
- 相关规格:`2026-10-12-md2zh-translator-design.md`(总体设计)、`2026-10-13-filelist-multithreading-design.md`(v0.4.0 批量多线程)

## 1. 背景与目标

当前唯一翻译后端为 Bilibili Index-Translate 在线 API,请求携带其特有的 `chat_template_kwargs` 与网关 412 要求的特殊 `User-Agent`。用户已在本机安装 ollama 并拉取 `index-translate-9b:latest` 模型,希望支持离线本地翻译。

目标:新增 `--ollama` 选项,使用本地 ollama 的 OpenAI 兼容端点(`http://localhost:11434/v1`)翻译,模型固定 `index-translate-9b:latest`,强制单线程运行(本地 9B 模型多线程并发会排队/争抢显存,无收益)。

## 2. 需求清单

1. 新增 CLI 选项 `--ollama`:固定端点 `http://localhost:11434/v1` + 模型 `index-translate-9b:latest`,三种模式(单文件/stdin/filelist)均可用;
2. `--ollama` 与显式 `--api-base` / 显式 `--model` / 显式 `-c N(N≠1)` 冲突,经 `_Parser.error` 以 64 退出;`-c 1` 不冲突(与强制单线程一致);
3. `--ollama` 时 `--filelist` 模式线程数锁定为 1(单文件/stdin 天然串行,不受影响);
4. 请求差异仅两处:ollama 分支省略 `chat_template_kwargs`、不发送特殊 User-Agent(仅 B 站网关要求);`temperature=0.0`/`max_tokens`/`stream=True`/SSE 解析/`</think>` 剥离/重试×2/120s 超时两后端一致;
5. ollama 服务未启动:现有重试耗尽 → `TranslateError` → 退出 75(EX_TEMPFAIL),stderr 报连接根因;
6. 提示词构建、术语表、忽略列表、校验、修复循环、退出码契约全部不变;
7. 存量 148 项测试零改动(所有新参数默认值不改变现有行为);
8. 版本提升 **0.5.0**;README/CHANGELOG/CLAUDE.md 同步;实施完成后立即执行真实 ollama 手工验证(环境已就绪)。

## 3. 方案选型

- **方案 A(选定):布尔标志贯穿**。`api.translate_text` 增 `ollama: bool = False`,为真时调整 payload/headers;CLI 层用 `None` 哨兵默认值检测显式传参并解析冲突;标志沿调用链贯穿(默认值 False,存量调用点零迁移)。KISS、改动面最小。
- 方案 B:Backend 配置对象——`api_base`/`model` 两参数合并为 dataclass 贯穿,请求差异内聚一处,扩展性好;但全部现有函数签名与 148 项测试调用点需迁移,对「两个后端、一处调用点」的现状过度设计,违背 YAGNI。否。
- 方案 C:子进程调 `ollama run`——违背「运行期依赖仅 requests」原则,流式/超时/退出码语义难做,且依赖 ollama 在 PATH。否。

## 4. 详细设计

### 4.1 CLI 层(cli.py)

新增常量在 api.py:`OLLAMA_API_BASE = "http://localhost:11434/v1"`、`OLLAMA_MODEL = "index-translate-9b:latest"`。

`parse_args` 变更:

1. `--api-base`/`--model`/`-c` 的 `default` 改为 `None`(哨兵区分「未显式传参」),help 文本中的默认值说明改为文字描述;
2. 新增选项:

```python
parser.add_argument("--ollama", action="store_true",
                    help="使用本地 ollama 翻译(端点 http://localhost:11434/v1,"
                         "模型 index-translate-9b:latest,强制单线程)")
```

3. 解析与冲突检测(在既有互斥检查后):

```python
if args.ollama:
    if args.api_base is not None:
        parser.error("--ollama 与 --api-base 不能同时使用")
    if args.model is not None:
        parser.error("--ollama 与 --model 不能同时使用")
    if args.max_threads is not None and args.max_threads != 1:
        parser.error("--ollama 强制单线程,-c/--max-threads 仅接受 1")
    args.api_base = api.OLLAMA_API_BASE
    args.model = api.OLLAMA_MODEL
    args.max_threads = 1
else:
    if args.api_base is None:
        args.api_base = api.DEFAULT_API_BASE
    if args.model is None:
        args.model = api.DEFAULT_MODEL
    if args.max_threads is None:
        args.max_threads = 10
    if args.max_threads < 1:
        parser.error("-c/--max-threads 必须是正整数")
```

注:`args.max_threads < 1` 校验须在 `None` 回填之后(现行校验位置不变,语义不变)。

`main` 三个分支透传 `ollama=args.ollama`(解析后的 api_base/model/max_threads 照旧透传);epilog 增加示例 `md2zh ABC.md --ollama`。

### 4.2 API 层(api.py)

`translate_text` 签名与请求构造:

```python
def translate_text(api_base: str, model: str, prompt: str, max_tokens: int,
                   ollama: bool = False) -> str:
    """流式调用 chat/completions,失败自动重试,重试耗尽抛 TranslateError。

    ollama=True 走本地 OpenAI 兼容端点:省略 B 站特有的 chat_template_kwargs,
    且网关 412 的 User-Agent 要求不适用。
    """
    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if not ollama:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    headers = {} if ollama else {"User-Agent": "Index-Translate-Client/1.0"}
    ...
```

重试、SSE 解析、非 dict 分片防护、`</think>` 剥离、空结果检查、`TranslateError` 语义不变(ollama 本地模型同样可能输出 think 块,剥离逻辑保留;无 `</think>` 时为 no-op)。

### 4.3 编排层(translator.py)

以下签名在末尾追加 `ollama: bool = False` 并逐层透传(全部为关键字实参,带默认值,存量调用零迁移):

- `translate_file(..., model: str, repair: int = 0, ollama: bool = False)`
- `_translate_document(text, glossary, api_base, model, *, source="", repair=0, ollama=False)`
- `_repair(make_prompt, check, *, api_base, model, max_tokens, label, source="", retries=0, ollama=False)`
- `_translate_chunk(..., repair=0, ollama=False)`、`_translate_long(..., repair=0, ollama=False)`、`_translate_frontmatter(fm, glossary, api_base, model, ollama=False)`
- `run_single(..., repair=0, ollama=False)`、`run_batch(..., max_threads=10, ollama=False)`、`run_stdin(*, ..., repair=0, ollama=False)`

最终调用 `api.translate_text(api_base, model, prompt, max_tokens, ollama=ollama)`。

**`run_batch` 线程池逻辑不改**——单线程强制完全在 CLI 层完成(`--ollama` 时 max_threads=1);translator 层不感知 ollama 语义,仅透传标志。

### 4.4 错误处理与退出码

- 参数冲突 → `_Parser.error` → 64(现有机制,无新增退出码);
- ollama 服务未启动/连接拒绝 → 现有重试 2 次 → `TranslateError` → run_single 映射 75;批量模式计入该文件失败(汇总与 EX_PARTIAL 契约不变);
- 其余契约(65/66/74/75/130/141)不变。

## 5. 测试策略

严格 TDD,API 全 mock,不依赖真实网络;先写失败测试再实现。存量 148 项零改动。

- **test_cli.py**:
  - `--ollama` 缺省解析:api_base=OLLAMA_API_BASE、model=OLLAMA_MODEL、max_threads=1;
  - 三组冲突各自退出 64 且 stderr 含错误信息(`--ollama` + `--api-base` / + `--model` / + `-c N(N≠1)`,参数化覆盖 `-c 2`/`-c 0`/`-c -1`);`--ollama -c 1` 合法;
  - 不带 `--ollama` 的默认值回归(api_base=DEFAULT_API_BASE、model=DEFAULT_MODEL、max_threads=10),显式传参仍生效;
  - 帮助文本含 `--ollama` 与示例。
- **test_api.py**:
  - ollama=True:mock `requests.post`,断言 payload 无 `chat_template_kwargs`、headers 无特殊 User-Agent;其余字段(stream/temperature/max_tokens)保留;
  - ollama=False:断言 payload/headers 与现状完全一致(回归钉住);
  - ollama 分支沿用重试/空结果/`</think>` 剥离(与现有用例同构)。
- **test_translator.py**:
  - 透传链:mock `api.translate_text`,断言 `translate_file(ollama=True)` 最终以 ollama=True 调用,且非 ollama 调用以 ollama=False;
  - `run_batch` 收 ollama 参数但线程池行为不因标志改变(max_workers 仅由 max_threads 决定)。
- **test_version.py**:版本号 0.5.0。

## 6. 手工验证清单(真实 ollama,环境已就绪)

- `md2zh data/sample_en.md --ollama` 生成 `*_zh.md`,译文中文、无 `@@@` 残留、链接/表格完好;
- `cat data/sample_en.md | md2zh - --ollama` stdin 管道正常;
- `md2zh --filelist list.txt --ollama` 单线程批量(观察无并发,汇总正确);
- 冲突实测:`--ollama --api-base X` / `--ollama --model M` / `--ollama -c 5` 均退出 64;
- 停掉 ollama 服务后运行 → 重试后退出 75,stderr 报连接错误;
- 观察本地 9B 模型生成速度与 120s 超时的余量;若 `</think>` 输出与 B 站模型形态不同,确认剥离逻辑无副作用。

## 7. 文档与发布

- README:选项表新增 `--ollama`,补本地翻译示例;
- CHANGELOG:v0.5.0 条目(本地 ollama 后端 + 强制单线程);
- CLAUDE.md:CLI 接口、架构决策(布尔标志贯穿)、版本同步;
- 提交信息末尾附 Co-Authored-By;真实 API 复验结果回填。
