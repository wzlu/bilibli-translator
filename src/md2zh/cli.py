"""命令行入口:参数解析、退出码映射。"""

import argparse
import errno
import os
import sys

from md2zh import __version__, api, ignore
from md2zh import translator


class _Parser(argparse.ArgumentParser):
    """用法错误按 unix-cli 规范以 EX_USAGE(64) 退出,附简短用法提示。"""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: 错误: {message}", file=sys.stderr)
        print(f"试用 '{self.prog} --help' 获取更多信息。", file=sys.stderr)
        sys.exit(translator.EX_USAGE)


def _prog() -> str:
    """程序名随入口名显示:txt2zh 别名时 usage/--version 显示 txt2zh。

    pytest 等环境下 sys.argv[0] 非本工具入口,回落 md2zh 保兼容。
    """
    name = os.path.basename(sys.argv[0])
    if name.endswith(".exe"):
        name = name[:-4]
    return name if name in ("md2zh", "txt2zh") else "md2zh"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _Parser(
        prog=_prog(),
        description="将英文 Markdown/HTML/TXT 文件翻译为中文,保存为 *_zh.<原扩展名>(同目录)。",
        formatter_class=argparse.RawDescriptionHelpFormatter,  # 保留 epilog 示例的换行
    )
    parser.add_argument("file", nargs="?", metavar="FILE",
                        help="要翻译的文件(格式按扩展名推断:.md/.html/.txt;可用 --format 覆盖)")
    parser.add_argument("--filelist", metavar="LIST",
                        help="文件列表(每行一个文件,# 开头的行被忽略)")
    parser.add_argument("--force", action="store_true",
                        help="覆盖已存在的 *_zh.<扩展名>(默认跳过)")
    parser.add_argument("--format", choices=("md", "html", "txt"), default=None,
                        metavar="FMT",
                        help="输入格式 md/html/txt(默认按扩展名推断;stdin 模式缺省 md)")
    parser.add_argument("--glossary", metavar="FILE",
                        help=f"术语表文件(JSON);缺省加载 {api.DEFAULT_GLOSSARY}")
    parser.add_argument("--api-base", default=None,
                        help=f"翻译 API 地址(默认 {api.DEFAULT_API_BASE})")
    parser.add_argument("--model", default=None,
                        help=f"模型(默认 {api.DEFAULT_MODEL})")
    parser.add_argument("--ollama", action="store_true",
                        help="使用本地 ollama 翻译(端点 http://localhost:11434/v1,"
                             "模型 index-translate-9b:latest,强制单线程)")
    parser.add_argument("--repair", type=int, choices=range(3), default=0,
                        help="校验失败后的重译次数 0-2(默认 0;失败一律采用译文,不回退原文)")
    parser.add_argument("-c", "--max-threads", type=int, default=None, metavar="N",
                        help="--filelist 模式最大并发线程数(默认 10;仅批量模式生效)")
    parser.add_argument("--version", action="version", version=f"{_prog()} {__version__}")
    parser.epilog = (
        "示例:\n"
        "  {prog} ABC.md                      翻译单个 Markdown 文件,生成 ABC_zh.md\n"
        "  {prog} page.html                  翻译 HTML 文件(格式按扩展名推断)\n"
        "  {prog} note.txt                   翻译纯文本文件(格式按扩展名推断)\n"
        "  txt2zh note.txt                  txt2zh 别名(等价 {prog} --format txt)\n"
        "  {prog} --filelist list.txt        批量翻译(每行一个文件,# 开头忽略)\n"
        "  {prog} --filelist list.txt -c 5    批量翻译,最多 5 个线程并行(默认 10)\n"
        "  {prog} ABC.md --force              覆盖已存在的译文\n"
        "  {prog} ABC.md --glossary g.json    指定术语表\n"
        "  {prog} ABC.md --ollama             使用本地 ollama 离线翻译(强制单线程)\n"
        "  cat ABC.md | {prog} -              管道过滤器(stdin → stdout)\n"
        "  cat page.html | {prog} - --format html  管道过滤器(HTML,stdin 无扩展名需显式 --format)\n"
        "  {prog} ABC.md --repair 2            校验失败后重译至多 2 次(默认不重译)"
    ).format(prog=_prog())
    args = parser.parse_args(argv)
    if args.file and args.filelist:
        parser.error("FILE 与 --filelist 不能同时使用")
    if not args.file and not args.filelist:
        parser.error("需要 FILE 或 --filelist 其中之一")
    if args.ollama:
        # --ollama 锁定本地端点与模型:显式后端参数冲突即用法错误
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
        # 哨兵回填:未显式传参时取默认值,显式传参(含 -c 0/-1)走既有校验
        if args.api_base is None:
            args.api_base = api.DEFAULT_API_BASE
        if args.model is None:
            args.model = api.DEFAULT_MODEL
        if args.max_threads is None:
            args.max_threads = 10
        if args.max_threads < 1:
            parser.error("-c/--max-threads 必须是正整数")
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

        if args.file == "-":
            return translator.run_stdin(glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        repair=args.repair, ollama=args.ollama,
                                        fmt=args.format or "md")

        if args.filelist:
            try:
                paths = translator.parse_filelist(args.filelist)
            except (OSError, UnicodeDecodeError) as e:
                # 非 UTF-8 文件列表按 EX_DATAERR 处理,与源文件非 UTF-8 契约一致
                if isinstance(e, UnicodeDecodeError):
                    print(f"md2zh: 错误: 文件列表不是 UTF-8 编码 {args.filelist}: {e}", file=sys.stderr)
                    return translator.EX_DATAERR
                print(f"md2zh: 错误: 无法读取文件列表 {args.filelist}: {e}", file=sys.stderr)
                return translator.EX_NOINPUT
            matcher = ignore.load_ignore()  # 自动读取当前目录 .translateignore
            return translator.run_batch(paths, force=args.force, glossary=glossary,
                                        api_base=args.api_base, model=args.model,
                                        ignore_matcher=matcher, repair=args.repair,
                                        max_threads=args.max_threads,
                                        ollama=args.ollama, fmt=args.format)
        return translator.run_single(args.file, force=args.force, glossary=glossary,
                                     api_base=args.api_base, model=args.model,
                                     repair=args.repair, ollama=args.ollama,
                                     fmt=args.format)
    except KeyboardInterrupt:
        print("\nmd2zh: 已中断", file=sys.stderr)
        return translator.EX_SIGINT
    except OSError as e:
        # 下游管道提前关闭(如 md2zh x | head):静默按 128+SIGPIPE 退出;
        # 按类型识别 BrokenPipeError,并按 errno 兜底 MSYS 文本层可能抛出的 EINVAL;
        # 其余 OSError 维持原有传播行为
        if isinstance(e, BrokenPipeError) or e.errno in (errno.EPIPE, errno.EINVAL):
            sys.stdout = open(os.devnull, "w")
            return translator.EX_SIGPIPE
        raise
