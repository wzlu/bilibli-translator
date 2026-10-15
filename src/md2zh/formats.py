"""格式注册表:各文本格式适配器的统一入口,翻译管线按此分派。"""

from dataclasses import dataclass
from typing import Callable

from md2zh import checks, html, markdown, txt

Validator = Callable[[str, str], list[str]]


@dataclass(frozen=True)
class Format:
    """一种文本格式的适配面:保护/还原/分段/校验/提示词约束。"""

    name: str
    extensions: tuple[str, ...]
    split_frontmatter: Callable[[str], tuple[str | None, str]]
    protect: Callable[[str], tuple[str, dict[str, str]]]
    restore: Callable[[str, dict[str, str]], str]
    chunk_text: Callable[[str, int], list[str]]
    validators: tuple[Validator, ...]
    constraints: tuple[str, ...]


FORMATS: dict[str, Format] = {
    "md": Format(
        name="md",
        extensions=(".md", ".markdown"),
        split_frontmatter=markdown.split_frontmatter,
        protect=markdown.protect_code_blocks,
        restore=markdown.restore_code_blocks,
        chunk_text=markdown.chunk_text,
        validators=(checks.check_links, checks.check_tables, checks.check_placeholders),
        constraints=markdown.CONSTRAINTS,
    ),
    "html": Format(
        name="html",
        extensions=(".html", ".htm"),
        split_frontmatter=html.split_frontmatter,
        protect=html.protect,
        restore=html.restore,
        chunk_text=html.chunk_text,
        validators=(checks.check_placeholders, checks.check_html_text),
        constraints=html.CONSTRAINTS,
    ),
    "txt": Format(
        name="txt",
        extensions=(".txt",),
        split_frontmatter=txt.split_frontmatter,
        protect=txt.protect,
        restore=txt.restore,
        chunk_text=txt.chunk_text,
        validators=(checks.check_placeholders,),
        constraints=txt.CONSTRAINTS,
    ),
}


def get_format(name: str) -> Format:
    """按名称取格式;未知名抛 KeyError(CLI choices 已拦截,仅库级可达)。"""
    return FORMATS[name]


def infer_format(path: str) -> str:
    """按扩展名(小写)推断格式;未知扩展名回落 md(向后兼容)。"""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    for key, fmt in FORMATS.items():
        if "." + ext in fmt.extensions:
            return key
    return "md"
