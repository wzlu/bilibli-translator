"""翻译编排:单文件全流程、修复循环、文件列表批量处理。"""

import os
import sys
import tempfile
from dataclasses import dataclass

from md2zh import api, markdown

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
    except OSError as e:
        return TranslateResult("failed", f"读写文件失败: {e}", EX_IOERR)
    return TranslateResult("ok", dst_path)


def _translate_document(text: str, glossary: list[str], api_base: str, model: str) -> str:
    """文档级翻译(基础版:整文单次调用,Task 9 扩展修复循环/frontmatter/分段)。"""
    protected, mapping = markdown.protect_code_blocks(text)
    prompt = api.build_prompt(protected, glossary)
    translated = api.translate_text(api_base, model, prompt, MAX_TOKENS_SINGLE)
    return markdown.restore_code_blocks(translated, mapping)
