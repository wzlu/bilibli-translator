"""翻译编排:单文件全流程、修复循环、文件列表批量处理。"""

import os
import sys
import tempfile
from dataclasses import dataclass

from md2zh import api, checks, markdown

# 退出码契约(规格 §8),全 CLI 唯一出处
EX_OK = 0
EX_PARTIAL = 1       # 批量模式存在失败文件
EX_USAGE = 64        # 命令行用法错误
EX_DATAERR = 65      # 术语表文件格式错误
EX_NOINPUT = 66      # 输入文件不存在
EX_IOERR = 74        # 输出写入失败
EX_TEMPFAIL = 75     # 翻译 API 临时不可用
EX_SIGINT = 130

# 翻译策略常量(规格 §11)
SINGLE_CALL_LIMIT = 15000   # 可译文本超过该长度则分段
CHUNK_SIZE = 3000
CONTEXT_TAIL = 800          # 分段时附前段上下文参考的字符数
REPAIR_RETRIES = 2
MAX_TOKENS_SINGLE = 8192
MAX_TOKENS_CHUNK = 4096


@dataclass
class TranslateResult:
    status: str       # "ok" / "skipped" / "failed"
    detail: str = ""  # 状态说明(ok 时为译文路径)
    exit_code: int = 0  # failed 时的具体退出码


def _zh_path(src_path: str) -> str:
    """ABC.md → ABC_zh.md(同目录)。"""
    stem, ext = os.path.splitext(src_path)
    return f"{stem}_zh{ext}"


def _atomic_write(path: str, content: str) -> None:
    """同目录临时文件写入后原子替换,失败时清理临时文件。"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def translate_file(src_path: str, *, force: bool, glossary: list[str],
                   api_base: str, model: str) -> TranslateResult:
    """翻译单个文件;已存在译文且未 --force 时跳过。"""
    if not src_path.lower().endswith(".md"):
        return TranslateResult("failed", "不是 .md 文件", EX_NOINPUT)
    if not os.path.isfile(src_path):
        return TranslateResult("failed", "文件不存在", EX_NOINPUT)
    dst_path = _zh_path(src_path)
    if os.path.exists(dst_path) and not force:
        return TranslateResult("skipped", "译文已存在(使用 --force 覆盖)")
    try:
        with open(src_path, encoding="utf-8-sig") as f:
            text = f.read()
        translated = _translate_document(text, glossary, api_base, model)
        _atomic_write(dst_path, translated)
    except api.TranslateError as e:
        return TranslateResult("failed", f"翻译 API 错误: {e}", EX_TEMPFAIL)
    except UnicodeDecodeError as e:
        return TranslateResult("failed", f"源文件不是 UTF-8 编码: {e}", EX_DATAERR)
    except OSError as e:
        return TranslateResult("failed", f"读写文件失败: {e}", EX_IOERR)
    return TranslateResult("ok", dst_path)


def _translate_document(text: str, glossary: list[str], api_base: str, model: str) -> str:
    """文档级翻译:frontmatter 独立翻译,正文按单次/分段策略处理。"""
    fm, rest = markdown.split_frontmatter(text)
    protected, mapping = markdown.protect_code_blocks(rest)

    if fm is None:
        head = ""
    else:
        head = _translate_frontmatter(fm, glossary, api_base, model)

    if len(protected) <= SINGLE_CALL_LIMIT:
        body = _translate_chunk(protected, glossary, api_base, model, MAX_TOKENS_SINGLE)
    else:
        body = _translate_long(protected, glossary, api_base, model)

    body = markdown.restore_code_blocks(body, mapping)
    if head:
        return f"{head.rstrip()}\n\n{body.lstrip()}"
    return body


def _check_block(src: str, dst: str) -> list[str]:
    """块级校验汇总:加黑/链接/表格/占位符。"""
    problems: list[str] = []
    for fn in (checks.check_bold, checks.check_links, checks.check_tables, checks.check_placeholders):
        problems.extend(fn(src, dst))
    return problems


def _trailing_whitespace(text: str) -> str:
    """返回文本末尾的空白串(回挂译文以保持分段边界与文件末尾布局)。"""
    return text[len(text.rstrip()):]


def _repair(make_prompt, check, *, api_base: str, model: str,
            max_tokens: int, label: str) -> tuple[bool, str]:
    """通用修复循环:校验失败带错误说明重译,重译耗尽返回 (False, "")。

    make_prompt(fix_notes) 构建带修复说明的提示词;check(dst) 返回问题列表,空列表表示通过。
    """
    problems: list[str] = []
    for attempt in range(REPAIR_RETRIES + 1):
        dst = api.translate_text(api_base, model, make_prompt(";".join(problems)), max_tokens)
        problems = check(dst)
        if not problems:
            return True, dst
        sys.stderr.write(f"md2zh: 警告: {label}校验失败,重译({attempt + 1}/{REPAIR_RETRIES}): {';'.join(problems)}\n")
    sys.stderr.write(f"md2zh: 警告: {label}重译耗尽,保留原文: {';'.join(problems)}\n")
    return False, ""


def _translate_chunk(src: str, glossary: list[str], api_base: str, model: str,
                     max_tokens: int, context: str = "") -> str:
    """翻译一段文本:校验失败带错误说明重译,仍失败回退原文。"""
    ok, dst = _repair(
        make_prompt=lambda fix: api.build_prompt(src, glossary, fix_notes=fix, context=context),
        check=lambda d: _check_block(src, d),
        api_base=api_base, model=model, max_tokens=max_tokens, label="块",
    )
    if not ok:
        return src
    # 译文经 API strip,回挂源块尾随空白,保持分段边界与文件末尾布局
    return dst + _trailing_whitespace(src)


def _translate_long(text: str, glossary: list[str], api_base: str, model: str) -> str:
    """超长文本:分段翻译,每段附前段上下文参考保证术语延续。"""
    parts: list[str] = []
    prev_context = ""
    half = CONTEXT_TAIL // 2
    for chunk in markdown.chunk_text(text, CHUNK_SIZE):
        # 不可分割的超限块(如大表格)按块长放大输出预算,避免确定性截断
        budget = max(MAX_TOKENS_CHUNK, len(chunk) * 2 + 200)
        translated = _translate_chunk(chunk, glossary, api_base, model,
                                      budget, context=prev_context)
        parts.append(translated)
        # 前段上下文:上一段(原文+译文)尾部,供下一段术语保持一致
        prev_context = f"原文: {chunk[-half:]}\n译文: {translated[-half:]}"
    return "".join(parts)


def _translate_frontmatter(fm: str, glossary: list[str], api_base: str, model: str) -> str:
    """frontmatter 独立翻译:仅译 value;校验失败重译,仍失败保留原文。"""
    ok, dst = _repair(
        make_prompt=lambda fix: api.build_frontmatter_prompt(fm, glossary, fix_notes=fix),
        check=lambda d: checks.check_frontmatter(fm, d),
        api_base=api_base, model=model, max_tokens=MAX_TOKENS_SINGLE, label="frontmatter",
    )
    return dst if ok else fm
