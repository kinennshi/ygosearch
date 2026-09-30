#!/usr/bin/env python3
"""把 ocg-rulebook 的 reStructuredText 源码转换为干净的中文 Markdown。"""
import re
import os
import glob
from collections import OrderedDict

SRC = "src_rst"
OUT = "md"

# 章节文件 -> 输出文件名 & 章标题
CHAPTERS = [
    ("c01_规则变动.rst.txt", "01-规则变动", "第一章 变更的规则 & 决斗的基本概念"),
    ("c01_特选规则.rst.txt", "02-特选规则", "第一章 变更的规则 & 决斗的基本概念"),
    ("c01_决斗的基本概念.rst.txt", "03-决斗的基本概念", "第一章 变更的规则 & 决斗的基本概念"),
    ("c02_OCG的概要.rst.txt", "04-OCG的概要", "第二章 大师规则"),
    ("c02_决斗进行的场所.rst.txt", "05-决斗进行的场所", "第二章 大师规则"),
    ("c02_卡片.rst.txt", "06-卡片", "第二章 大师规则"),
    ("c02_卡片的效果.rst.txt", "07-卡片的效果", "第二章 大师规则"),
    ("c02_效果以外的文本.rst.txt", "08-效果以外的文本", "第二章 大师规则"),
    ("c02_游戏的进行.rst.txt", "09-游戏的进行", "第二章 大师规则"),
    ("c02_大会规则.rst.txt", "10-大会规则", "第二章 大师规则"),
    ("c03_游戏王OCG检定测试模拟试验.rst.txt", "11-游戏王OCG检定测试模拟试验", "第三章 游戏王OCG检定测试"),
]

ADMONITIONS = {
    "note": "说明",
    "attention": "注意",
    "warning": "警告",
    "tip": "提示",
    "important": "重要",
    "caution": "注意",
    "danger": "危险",
    "hint": "提示",
    "error": "错误",
}

# RST 标题装饰符 -> Markdown 层级（按出现顺序降级）
DECOR_LEVEL = {"=": 2, "-": 3, "~": 4, "^": 5, '"': 6, "+": 6, "*": 6, "#": 6, "`": 4}
DECOR_CHARS = "=\\-~^\"+*#`"


def strip_directives(text):
    """移除 .. role:: 等角色定义块。"""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)\.\.\s+role::", line)
        if m:
            indent = len(m.group(1))
            i += 1
            # 跳过其缩进内容
            while i < len(lines):
                cur = lines[i]
                if cur.strip() == "":
                    i += 1
                    continue
                cur_indent = len(cur) - len(cur.lstrip())
                if cur_indent > indent:
                    i += 1
                else:
                    break
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def convert_admonitions(text):
    """把 .. note:: / .. attention:: / .. sidebar:: 转成 Markdown 引用块。"""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)\.\.\s+([a-zA-Z-]+)::\s*(.*)$", line)
        if m and m.group(2) in ADMONITIONS:
            indent = len(m.group(1))
            kind = m.group(2)
            first = m.group(3).strip()
            body = []
            if first:
                body.append(first)
            i += 1
            # 收集缩进内容
            while i < len(lines):
                cur = lines[i]
                if cur.strip() == "":
                    # 空行后面若仍是缩进内容则继续
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines):
                        cur_indent = len(lines[j]) - len(lines[j].lstrip())
                        if cur_indent > indent:
                            body.append("")
                            i += 1
                            continue
                    break
                cur_indent = len(cur) - len(cur.lstrip())
                if cur_indent > indent:
                    body.append(cur[(indent + 3):] if len(cur) > indent + 3 else cur.strip())
                    i += 1
                else:
                    break
            label = ADMONITIONS[kind]
            out.append(f"> **【{label}】**")
            for b in body:
                out.append(f"> {b}" if b else ">")
            out.append("")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def convert_sidebars(text):
    """把 .. sidebar:: 标题 + 缩进内容 转成 Markdown 引用块（卡片文本等）。"""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)\.\.\s+sidebar::\s*(.*)$", line)
        if m:
            indent = len(m.group(1))
            title = m.group(2).strip()
            body = []
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.strip() == "":
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines):
                        nxt_indent = len(lines[j]) - len(lines[j].lstrip())
                        if nxt_indent > indent:
                            body.append("")
                            i += 1
                            continue
                    break
                cur_indent = len(cur) - len(cur.lstrip())
                if cur_indent > indent:
                    s = cur.strip()
                    # 去掉 RST 的行首 | 续行符
                    s = re.sub(r"^\|\s?", "", s)
                    body.append(s)
                    i += 1
                else:
                    break
            if title:
                out.append(f"> **{title}**")
            for b in body:
                if b == "":
                    out.append(">")
                else:
                    # 正文行合并为引用（保持换行）
                    out.append(f"> {b}")
            out.append("")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def convert_figures(text):
    """把 .. figure:: / .. image:: 转成占位说明（图片不下载，保留原路径）。"""
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)\.\.\s+(figure|image)::\s*(.*)$", line)
        if m:
            indent = len(m.group(1))
            path = m.group(3).strip()
            caption = []
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.strip() == "":
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines):
                        cur_indent = len(lines[j]) - len(lines[j].lstrip())
                        if cur_indent > indent:
                            i += 1
                            continue
                    break
                cur_indent = len(cur) - len(cur.lstrip())
                if cur_indent > indent:
                    s = cur.strip()
                    if s.startswith(":align:") or s.startswith(":target:") or s.startswith(":width:"):
                        i += 1
                        continue
                    caption.append(s)
                    i += 1
                else:
                    break
            cap = " ".join(caption) if caption else "插图"
            out.append(f"> 【配图：{cap}】")
            out.append(f"> 图片地址：`{path}`")
            out.append("")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def inline(text):
    """处理行内标记。"""
    # :strike:`xxx` -> ~~xxx~~
    text = re.sub(r":strike:`([^`]*)`", r"~~\1~~", text)
    # :角色:`xxx` (其他自定义角色) -> 保留内容
    text = re.sub(r":[a-zA-Z_-]+:`([^`]*)`", r"\1", text)
    # 引用链接 `text <url>`__ / `text <url>`_
    text = re.sub(r"`([^`<]+?)\s*<([^>]+)>`__?", r"[\1](\2)", text)
    # 简单引用 `text`_ -> text
    text = re.sub(r"`([^`]+?)`_+", r"\1", text)
    # 内联字面量 ``xxx`` -> `xxx`
    text = re.sub(r"``([^`]+)``", r"`\1`", text)
    return text


def fix_leading_artifact(text, page_title):
    """移除页面开头的遗留装饰线（原 RST 顶部标题的下划线）。"""
    lines = text.split("\n")
    out = []
    for idx, line in enumerate(lines):
        # 只处理开头几行内的孤立装饰线
        if idx < 8 and re.match(r"^[=\-~^\"+*#]{3,}\s*$", line):
            continue
        out.append(line)
    text = "\n".join(out)
    # 若去掉装饰线后，正文第一个标题与页面标题重复，则去掉该重复标题
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        if line.strip() == "":
            continue
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m and m.group(1).strip() == page_title:
            # 从这一行起到下一段内容之前一起删除（含紧随的空行）
            del lines[idx]
            while idx < len(lines) and lines[idx].strip() == "":
                del lines[idx]
            break
        break
    return "\n".join(lines)


def convert(text, page_title):
    text = strip_directives(text)
    # 先处理 figure/image/sidebar/admonition（需要基于原始缩进）
    text = convert_figures(text)
    text = convert_sidebars(text)
    text = convert_admonitions(text)

    lines = text.split("\n")
    out = []
    i = 0
    used_levels = {}
    while i < len(lines):
        line = lines[i]
        # 检测标题：当前行有内容，下一行是装饰符
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if line.strip() and re.match(r"^([" + DECOR_CHARS + r"])\1{2,}\s*$", nxt):
                decor = nxt.strip()[0]
                title = inline(line.strip())
                base = DECOR_LEVEL.get(decor, 6)
                # 页内按装饰符首次出现顺序确定层级
                if decor not in used_levels:
                    used_levels[decor] = base
                lvl = used_levels[decor]
                out.append("")
                out.append("#" * lvl + " " + title)
                out.append("")
                i += 2
                continue
        out.append(line)
        i += 1

    text = "\n".join(out)

    # 列表符号归一
    text = re.sub(r"^(\s*)[*+]\s+", r"\1- ", text, flags=re.M)
    # 行内标记
    text = inline(text)
    # RST 行块（line block）：行首 "| " 是折行符，去掉后合并
    text = re.sub(r"^\|\s?", "", text, flags=re.M)
    # 转义符 \ 后面跟空格或标点的情况
    text = re.sub(r"\\(?=[\s，。、；：！？）】》])", "", text)
    # 脚注定义 .. [#name] xxx -> [^name]: xxx
    text = re.sub(r"^\.\.\s+\[(#?)([^]]*)\]\s*", lambda m: f"[^{m.group(2) or 'auto'}]: ", text, flags=re.M)
    # 脚注引用 [#]_ / [#name]_ / [1]_ -> [^...]
    text = re.sub(r"\[#([^\]]*)\]_*", lambda m: f"[^{m.group(1) or 'auto'}]", text)
    text = re.sub(r"\[(\d+)\]_+", lambda m: f"[^{m.group(1)}]", text)
    # 匿名脚注/无名数字脚注在同一页内可能重名，统一改名保证唯一
    text = uniquify_footnotes(text)
    # 连续 3 个以上空行压缩
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = fix_leading_artifact(text, page_title)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def uniquify_footnotes(text):
    """同一页内把匿名的 [^auto] / 纯数字脚注重命名为稳定唯一标签。"""
    lines = text.split("\n")
    counter = [0]
    mapping = {}

    def alloc(key):
        if key not in mapping:
            mapping[key] = f"fn{counter[0] + 1}"
            counter[0] += 1
        return mapping[key]

    def repl_ref(m):
        key = m.group(1) or "auto"
        return f"[^{alloc(key)}]"

    def repl_def(m):
        key = m.group(1) or "auto"
        return f"[^{alloc(key)}]:"

    # 先扫定义，保证定义与引用用同一映射
    new_lines = []
    for line in lines:
        md = re.match(r"^\[\^([^\]]*)\]:", line)
        if md:
            key = md.group(1) or "auto"
            label = alloc(key)
            line = re.sub(r"^\[\^[^\]]*\]:", f"[^{label}]:", line)
        new_lines.append(line)
    text = "\n".join(new_lines)
    # 再替换剩余引用（跳过已重命名的定义行）
    def repl_line(line):
        if re.match(r"^\[\^[^\]]*\]:", line):
            return line
        return re.sub(r"\[\^([^\]]*)\]", repl_ref, line)
    text = "\n".join(repl_line(l) for l in text.split("\n"))
    return text


def main():
    os.makedirs(OUT, exist_ok=True)
    index = []
    for src, name, chapter in CHAPTERS:
        path = os.path.join(SRC, src)
        if not os.path.exists(path):
            print(f"跳过（不存在）: {src}")
            continue
        raw = open(path, encoding="utf-8").read()
        # 页面标题 = 第一个 RST 标题
        m = re.match(r"^[=\-~^\"+*#]{3,}\s*\n(.+?)\n[=\-~^\"+*#]{3,}", raw)
        page_title = m.group(1).strip() if m else name
        body = convert(raw, page_title)
        md = f"# {page_title}\n\n> 所属：{chapter}\n> 来源：[OCG 完全规则书 2020 中文翻译](https://ocg-rulebook.readthedocs.io/zh-cn/latest/)\n\n{body}\n"
        outpath = os.path.join(OUT, f"{name}.md")
        open(outpath, "w", encoding="utf-8").write(md)
        size = len(md)
        index.append((name, page_title, chapter, size))
        print(f"OK {name}.md  {size} 字符  <- {src}")
    return index


if __name__ == "__main__":
    main()
