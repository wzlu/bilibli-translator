"""命令行入口:参数解析、退出码映射。"""

import argparse
import sys

from md2zh import __version__, api
from md2zh import translator


class _Parser(argparse.ArgumentParser):
    """用法错误按 unix-cli 规范以 EX_USAGE(64) 退出,附简短用法提示。"""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: 错误: {message}", file=sys.stderr)
        print(f"试用 '{self.prog} --help' 获取更多信息。", file=sys.stderr)
        sys.exit(translator.EX_USAGE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _Parser(
        prog="md2zh",
        description="将英文 Markdown 文件翻译为中文,保存为 *_zh.md(同目录)。",
    )
    parser.add_argument("file", nargs="?", metavar="FILE", help="要翻译的 Markdown 文件")
    parser.add_argument("--filelist", metavar="LIST",
                        help="文件列表(每行一个 md 文件,# 开头的行被忽略)")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的 *_zh.md(默认跳过)")
    parser.add_argument("--glossary", metavar="FILE",
                        help=f"术语表文件(JSON);缺省加载 {api.DEFAULT_GLOSSARY}")
    parser.add_argument("--api-base", default=api.DEFAULT_API_BASE,
                        help=f"翻译 API 地址(默认 {api.DEFAULT_API_BASE})")
    parser.add_argument("--model", default=api.DEFAULT_MODEL,
                        help=f"模型(默认 {api.DEFAULT_MODEL})")
    parser.add_argument("--version", action="version", version=f"md2zh {__version__}")
    args = parser.parse_args(argv)
    if args.file and args.filelist:
        parser.error("FILE 与 --filelist 不能同时使用")
    if not args.file and not args.filelist:
        parser.error("需要 FILE 或 --filelist 其中之一")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        try:
            glossary = api.load_glossary(args.glossary)
        except FileNotFoundError as e:
            print(f"md2zh: 错误: {e}", file=sys.stderr)
            return translator.EX_NOINPUT
        except ValueError as e:
            print(f"md2zh: 错误: {e}", file=sys.stderr)
            return translator.EX_DATAERR

        if args.filelist:
            try:
                paths = translator.parse_filelist(args.filelist)
            except OSError as e:
                print(f"md2zh: 错误: 无法读取文件列表 {args.filelist}: {e}", file=sys.stderr)
                return translator.EX_NOINPUT
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model)
        return translator.run_single(args.file, force=args.force, glossary=glossary,
                                     api_base=args.api_base, model=args.model)
    except KeyboardInterrupt:
        print("\nmd2zh: 已中断", file=sys.stderr)
        return translator.EX_SIGINT
