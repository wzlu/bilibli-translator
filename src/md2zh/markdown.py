"""文本分段与占位符通用工具 + Markdown 适配实现。"""

import re

# 每次请求携带的 markdown 格式约束(自 api.py 迁移,文案逐字不变)
CONSTRAINTS = (
    "严格保留 markdown 语法结构,全部格式标记与链接结构原样保留,仅翻译文字内容。",
    "不得翻译或修改 @@@...@@@ 占位符。",
    "表格保持行数与列数,分隔行保持。",
)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """拆分开头的 frontmatter 块(含首尾 --- 行);无则返回 (None, 原文)。

    识别规则:首行是 ---,且在其与某个闭合 --- 行之间存在含 ":" 的键值行;
    否则视为水平分隔线,不拆分。
    """
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            # 闭合行之前至少一行含 ":",才认定为 frontmatter
            if any(":" in ln for ln in lines[1:i]):
                cut = sum(len(ln) for ln in lines[: i + 1])
                return text[:cut], text[cut:]
            return None, text
    return None, text


_INLINE_RE = re.compile(r"`[^`\n]+`")


def _fence_len(line: str) -> int:
    """统计行首连续反引号个数(围栏开启/闭合判定依据)。"""
    stripped = line.lstrip()
    n = 0
    while n < len(stripped) and stripped[n] == "`":
        n += 1
    return n


def protect_code_blocks(text: str) -> tuple[str, dict[str, str]]:
    """围栏代码块、行内代码与链接 URL 替换为占位符,返回 (保护后文本, 占位符→原文 映射)。

    先处理围栏(其内部的行内代码不重复保护),再处理行内代码,
    最后处理链接 URL(此时反引号内的假链接已被行内占位符隔离);
    未闭合的围栏视为普通文本。
    """
    text, fenced = _protect_fenced(text)
    text, inline = _protect_inline(text)
    text, links = _protect_links(text)
    return text, {**fenced, **inline, **links}


def _protect_fenced(text: str) -> tuple[str, dict[str, str]]:
    parts: list[str] = []
    mapping: dict[str, str] = {}
    lines = text.splitlines(keepends=True)
    i, n = 0, 0
    while i < len(lines):
        open_len = _fence_len(lines[i])
        if open_len >= 3:
            start = i
            i += 1
            # 闭合围栏必须不少于开启围栏的反引号个数
            while i < len(lines) and _fence_len(lines[i]) < open_len:
                i += 1
            if i >= len(lines):  # 未闭合:整段视为普通文本
                parts.append("".join(lines[start:]))
                break
            i += 1  # 包含闭合行
            block = "".join(lines[start:i])
            ph = f"@@@CODEBLOCK_{n}@@@"
            mapping[ph] = block
            parts.append(ph)
            n += 1
        else:
            parts.append(lines[i])
            i += 1
    return "".join(parts), mapping


def _protect_inline(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        ph = f"@@@INLINE_{n}@@@"
        mapping[ph] = m.group(0)
        n += 1
        return ph

    return _INLINE_RE.sub(repl, text), mapping


_LINK_URL_RE = re.compile(r"(\[[^\]\n]*\]\()([^)\n]*)(\))")


def _protect_links(text: str) -> tuple[str, dict[str, str]]:
    """链接 URL 替换为占位符,显示文本保留照常翻译。"""
    mapping: dict[str, str] = {}
    n = 0

    def repl(m: re.Match) -> str:
        nonlocal n
        if "@@@" in m.group(2):
            return m.group(0)  # 目标已含占位符(如行内代码):跳过保护,保证还原往返
        ph = f"@@@URL_{n}@@@"
        mapping[ph] = m.group(2)
        n += 1
        return f"{m.group(1)}{ph}{m.group(3)}"

    return _LINK_URL_RE.sub(repl, text), mapping


def restore_code_blocks(text: str, mapping: dict[str, str]) -> str:
    """将占位符还原为原始代码内容。"""
    for ph, original in mapping.items():
        text = text.replace(ph, original)
    return text


_TABLE_LIST_RE = re.compile(r"^\s*(\||[-*+]|\d+\.)\s+")

# 块长硬上限:网关按「prompt + max_tokens」总量限制(实证 ≈24576 tokens),
# 输出预算封顶 16384(见 translator.MAX_TOKENS_CEILING),英文 markdown 实测
# 约 2.6~3.9 字符/token,故 6000 字符块的总量约 1.8 万 tokens,留 ≥25% 余量。
# shortcut: 6000 是从公共网关实证反推的经验值,非网关文档规格;
# 网关调整总量上限或换后端(如 ollama)时需重新标定
FORCE_SPLIT_LIMIT = 6000


def split_blank_lines(text: str) -> list[str]:
    """按空行切分并保留分隔符(分隔符并入前段)。"""
    parts = re.split(r"(\n[ \t]*\n)", text)
    blocks: list[str] = []
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        blocks.append(para + sep)
    return blocks


def _split_oversized(block: str) -> list[str]:
    """超过 FORCE_SPLIT_LIMIT 的块按空白边界强制切分,否则原样返回单元素列表。

    优先在换行处切(表格/列表按行自然断开),换行切点缺失或过早时退到空格
    (爬取页面的超长单行)。占位符令牌不含空白,故切点永不落在令牌内部;
    两者都无可用切点时保持完整,由输出预算封顶兜底。
    """
    if len(block) <= FORCE_SPLIT_LIMIT:
        return [block]
    pieces: list[str] = []
    while len(block) > FORCE_SPLIT_LIMIT:
        cut = block.rfind("\n", 0, FORCE_SPLIT_LIMIT)
        if cut + 1 < FORCE_SPLIT_LIMIT // 2:
            # shortcut: 切点只认 \n 与空格、不认 \t,故纯 tab 分隔的超长块(如 TSV)
            # 无切点、退化为整块送译;出现 TSV 类输入时把 \t 加进切点集合
            # 换行切点缺失或过早(如块首只有一个令牌后的换行)→ 退到空格切点
            cut = block.rfind(" ", 0, FORCE_SPLIT_LIMIT)
        if cut + 1 < FORCE_SPLIT_LIMIT // 2:
            # shortcut: 无可用切点、或切点过早(切完仍留一个超限尾巴)的超长块不切分,
            # 整块送译靠 MAX_TOKENS_CEILING 兜底,译文可能被截断且无 finish_reason 检测。
            # 过早切分毫无收益还有害:产出的微小首片(如表格行的 "| ")会独占一次 API
            # 调用,模型对其返回空白即触发「API 返回空结果」→ 整文件退出 75。
            # 观测到此类块被截断或遭网关拒绝时,再引入令牌感知的硬切
            break
        pieces.append(block[:cut + 1])  # 分隔符随前段,与 split_blank_lines 归属一致
        block = block[cut + 1:]
    pieces.append(block)
    return pieces


def pack_blocks(blocks: list[str], max_chars: int) -> list[str]:
    """贪心装包:按序装入不超过 max_chars 的块;超限块保持完整。

    超过 FORCE_SPLIT_LIMIT 的块先按空白强制切分再装包:否则单次请求的
    prompt 与输出预算之和会超出网关总量上限,导致 invalid_request 整块失败,
    或退到可接受的预算后译文被静默截断。
    """
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        for piece in _split_oversized(block):
            if current and size + len(piece) > max_chars:
                chunks.append("".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece)
    if current:
        chunks.append("".join(current))
    return chunks


def _logical_blocks(text: str) -> list[str]:
    """空行切分后,连续的表格行/列表项合并为一块。"""
    merged: list[str] = []
    for block in split_blank_lines(text):
        if block and _is_table_or_list(block) and merged and _is_table_or_list(merged[-1]):
            merged[-1] += block
            continue
        merged.append(block)
    return merged


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """按逻辑边界切分文本;所有段按序拼接与原文完全一致。

    超出 max_chars 但不足 FORCE_SPLIT_LIMIT 的不可分割块(如大表格)保持完整;
    超过 FORCE_SPLIT_LIMIT 的块按空白边界强制切分(见 pack_blocks)。
    """
    return pack_blocks(_logical_blocks(text), max_chars)


def _is_table_or_list(para: str) -> bool:
    """段落首行是否为表格行或列表项。"""
    return bool(_TABLE_LIST_RE.match(para))
