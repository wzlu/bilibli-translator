# md2zh

将英文 Markdown 文件翻译为中文的命令行工具,基于 Bilibili Index-Translate 免费翻译 API。
译文保存于原文件同目录,命名为 `*_zh.md`。

## 安装

```bash
python -m pip install -e ".[dev]"
```

## 用法

```bash
md2zh ABC.md                     # 翻译单个文件
md2zh --filelist list.txt        # 批量翻译(每行一个 md 文件,# 开头的行被忽略)
md2zh ABC.md --force             # 覆盖已存在的 ABC_zh.md
md2zh ABC.md --glossary g.json   # 指定术语表文件
```

术语表格式为 JSON:`{"英文术语": "中文译法"}`。未指定 `--glossary` 时自动加载
`~/.config/md2zh/glossary.json`(Windows 下为 `%USERPROFILE%\.config\md2zh\glossary.json`),
文件不存在则视为无术语表。

## 行为约定

- 代码块与行内代码不翻译(占位符保护,内容不会发送给 API);
- 译文格式与原文一致:frontmatter 的 key 与 `---` 标记不变、`**` 加黑成对、链接 url 不变、表格行列不变;
- 校验失败自动重译修复,重试耗尽后该块保留原文并输出警告;
- stdout 只输出成功生成的译文路径(每行一个);进度与警告输出到 stderr;
- 退出码:0 成功 / 1 存在失败(批量) / 64 用法错误 / 65 术语表格式错误 / 66 输入不存在 / 74 写失败 / 75 API 不可用 / 130 中断。

## 开发

```bash
python -m pytest -v            # 运行全部测试(API 已 mock,不依赖网络)
```
