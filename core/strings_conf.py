# -*- coding: utf-8 -*-
"""strings.conf / lflist.conf 解析。"""
import re
from typing import Dict, List, Tuple
from pathlib import Path

YGOWORK = Path(__file__).resolve().parent.parent / "cdb" / "zh-CN"


def parse_strings_conf(path: Path = None):
    """返回 (setnames, system_strings)。
    setnames: {主系列码(12bit): 简中名}
    system_strings: {编号: 文本}
    """
    path = path or (YGOWORK / "strings.conf")
    setnames: Dict[int, str] = {}
    system: Dict[int, str] = {}
    pat_set = re.compile(r"^!setname\s+(0x[0-9a-fA-F]+|\d+)\s+(.*)$")
    pat_sys = re.compile(r"^!system\s+(0x[0-9a-fA-F]+|\d+)\s+(.*)$")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.rstrip("\n")
        m = pat_set.match(line)
        if m:
            code = int(m.group(1), 0)
            # 格式: 简中名 \t 日文名，取简中名
            zh_name = m.group(2).split("\t")[0].strip()
            setnames[code & 0xFFF] = zh_name
            continue
        m = pat_sys.match(line)
        if m:
            system[int(m.group(1), 0)] = m.group(2).strip()
    return setnames, system


def parse_lflist(path: Path = None) -> Dict[int, int]:
    """解析禁限卡表，取最新一段（首个数据段）。
    返回 {card_id: count}，0=禁止 1=限制 2=准备限制。
    """
    path = path or (YGOWORK / "lflist.conf")
    result: Dict[int, int] = {}
    seen_data = False
    pat = re.compile(r"^(\d+)\s+([0-3])\b")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        if s.startswith("#"):
            if seen_data:
                break  # 第二个数据段开始 = 旧表，停止
            continue
        if s.startswith("$"):
            continue
        m = pat.match(s)
        if m:
            result[int(m.group(1))] = int(m.group(2))
            seen_data = True
    return result


def parse_lflist_version(path: Path = None) -> str:
    """解析禁限卡表最新版本号（lflist.conf 首个 `!` 标记，如 2026.10）。"""
    path = path or (YGOWORK / "lflist.conf")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s.startswith("!"):
            return s[1:].strip()
    return "未知"


def load_vocabs():
    """供 vocab / 构建流程共用的词汇加载入口。"""
    setnames, system = parse_strings_conf()
    return setnames, system


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    setnames, system = load_vocabs()
    print(f"setname 数: {len(setnames)}, 示例: {list(setnames.items())[:3]}")
    lf = parse_lflist()
    print(f"lflist 条数: {len(lf)}, 禁0/限1/准限2 分布:",
          {k: sum(1 for v in lf.values() if v == k) for k in (0, 1, 2)})
