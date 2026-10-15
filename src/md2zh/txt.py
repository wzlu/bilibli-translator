"""TXT 适配器:纯文本直通,空行分段。"""

from md2zh import markdown

CONSTRAINTS = (
    "只输出纯文本译文,不得添加任何格式标记。",
    "不得翻译或修改 @@@...@@@ 占位符。",
)


def split_frontmatter(text: str) -> tuple[None, str]:
    """TXT 无 frontmatter:恒返回 (None, 原文)。"""
    return None, text


def protect(text: str) -> tuple[str, dict[str, str]]:
    """纯文本零保护:直通返回,空映射。"""
    return text, {}


def restore(text: str, mapping: dict[str, str]) -> str:
    """空映射下恒等还原(委托通用替换)。"""
    return markdown.restore_code_blocks(text, mapping)


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """空行切分后贪心装包(不合并表格/列表段)。"""
    return markdown.pack_blocks(markdown.split_blank_lines(text), max_chars)
