#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 ygopro / YGOPro2 / EDOPro 使用的 cards.cdb 导出为人类可读文件。

输出四种格式（每种语言一套）：
  1. cards_<lang>.csv           —— 原始字段（位掩码保持数值），给程序用
  2. cards_<lang>.readable.csv  —— 人类可读（类型/种族/属性/召唤法/系列译成文字）
  3. cards_<lang>.json          —— 结构化 JSON（含解码后的字段）
  4. cards_<lang>.md            —— 便于直接浏览的 Markdown（按主类型分组）

用法：
  python export_cards.py              # 导出全部语言
  python export_cards.py zh-CN        # 只导出指定语言
"""
import csv
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CDB_DIR = os.path.join(HERE, "cdb")
OUT_DIR = os.path.join(HERE, "export")

# ---------------------------------------------------------------- 位掩码定义
# 卡片类型（datas.type）——详见 ocgapi_constants.h 与 CardType.cs
TYPE_BITS = [
    (0x1, "怪兽", "Monster"),
    (0x2, "魔法", "Spell"),
    (0x4, "陷阱", "Trap"),
    (0x10, "通常", "Normal"),
    (0x20, "效果", "Effect"),
    (0x40, "融合", "Fusion"),
    (0x80, "仪式", "Ritual"),
    (0x100, "陷阱怪兽", "TrapMonster"),
    (0x200, "灵魂", "Spirit"),
    (0x400, "同盟", "Union"),
    (0x800, "二重", "Dual/Gemini"),
    (0x1000, "调整", "Tuner"),
    (0x2000, "同调", "Synchro"),
    (0x4000, "衍生物", "Token"),
    (0x10000, "速攻", "QuickPlay"),
    (0x20000, "永续", "Continuous"),
    (0x40000, "装备", "Equip"),
    (0x80000, "场地", "Field"),
    (0x100000, "反击", "Counter"),
    (0x200000, "反转", "Flip"),
    (0x400000, "卡通", "Toon"),
    (0x800000, "超量", "XYZ"),
    (0x1000000, "灵摆", "Pendulum"),
    (0x2000000, "特殊召唤", "SpSummon"),
    (0x4000000, "连接", "Link"),
]
TYPE_MAP = {b: (cn, en) for b, cn, en in TYPE_BITS}

# 属性（datas.attribute）
ATTR_BITS = [
    (0x01, "地", "EARTH"),
    (0x02, "水", "WATER"),
    (0x04, "炎", "FIRE"),
    (0x08, "风", "WIND"),
    (0x10, "光", "LIGHT"),
    (0x20, "暗", "DARK"),
    (0x40, "神", "DIVINE"),
]
ATTR_MAP = {b: (cn, en) for b, cn, en in ATTR_BITS}

# 种族（datas.race）——注意 race 是 64 位
RACE_BITS = [
    (0x1, "战士", "Warrior"),
    (0x2, "魔法师", "Spellcaster"),
    (0x4, "天使", "Fairy"),
    (0x8, "恶魔", "Fiend"),
    (0x10, "不死", "Zombie"),
    (0x20, "机械", "Machine"),
    (0x40, "水族", "Aqua"),
    (0x80, "炎族", "Pyro"),
    (0x100, "岩石", "Rock"),
    (0x200, "鸟兽", "WingedBeast"),
    (0x400, "植物", "Plant"),
    (0x800, "昆虫", "Insect"),
    (0x1000, "雷", "Thunder"),
    (0x2000, "龙", "Dragon"),
    (0x4000, "兽", "Beast"),
    (0x8000, "兽战士", "BeastWarrior"),
    (0x10000, "恐龙", "Dinosaur"),
    (0x20000, "鱼", "Fish"),
    (0x40000, "海龙", "SeaSerpent"),
    (0x80000, "爬虫类", "Reptile"),
    (0x100000, "念动力", "Psychic"),
    (0x200000, "幻神兽", "Divine"),
    (0x400000, "创造神", "CreatorGod"),
    (0x800000, "幻龙", "Wyrm"),
    (0x1000000, "电子界", "Cyberse"),
    (0x2000000, "幻想魔族", "Illusion"),
    (0x4000000, "机械族(赛博)", "Cyborg"),
    (0x8000000, "魔导骑士", "MagicalKnight"),
    (0x10000000, "高等龙", "HighDragon"),
    (0x20000000, "究极念动力", "OmegaPsychic"),
    (0x40000000, "天体战士", "CelestialWarrior"),
    (0x80000000, "银河", "Galaxy"),
    (0x4000000000000000, "妖怪", "Yokai"),
]
RACE_MAP = {b: (cn, en) for b, cn, en in RACE_BITS}

# 卡池归属（datas.ot）
OT_MAP = {
    1: "OCG",
    2: "TCG",
    3: "OCG/TCG",
    4: "TCG(独有)",
    8: "简中(独有)",
    9: "简中/OCG",
    11: "简中/OCG/TCG",
    16: "自定义",
}

# 连接标记（存在 def 字段，仅连接怪兽）
LINK_MARKER_BITS = [
    (0x01, "左下", "BottomLeft"),
    (0x02, "下", "Bottom"),
    (0x04, "右下", "BottomRight"),
    (0x08, "左", "Left"),
    (0x20, "右", "Right"),
    (0x40, "左上", "TopLeft"),
    (0x80, "上", "Top"),
    (0x100, "右上", "TopRight"),
]


# ---------------------------------------------------------------- 工具函数
def decode_bits(value, table):
    """按位掩码表解码，返回中文名列表。"""
    out = []
    for bit, cn, en in table:
        if value & bit:
            out.append(cn)
    return out


def decode_bits_en(value, table):
    out = []
    for bit, cn, en in table:
        if value & bit:
            out.append(en)
    return out


def decode_one(value, table):
    """单值位掩码（如属性只应有一个）。"""
    names = decode_bits(value, table)
    return "/".join(names) if names else ""


def load_setnames(path):
    """读取 strings.conf 的 !setname 段，返回 {setcode: 中文名}。"""
    result = {}
    if not os.path.exists(path):
        return result
    for line in open(path, encoding="utf-8", errors="replace"):
        if not line.startswith("!setname "):
            continue
        body = line[len("!setname "):].rstrip("\r\n")
        parts = body.split("\t")
        if len(parts) < 1:
            continue
        head = parts[0].split(" ", 1)
        if len(head) < 2:
            continue
        try:
            code = int(head[0], 16)
        except ValueError:
            continue
        result[code] = head[1].strip()
    return result


def decompose_setcodes(setcode):
    """把 setcode 拆成若干 16 位子系列码（一个卡可能属于多个系列）。"""
    codes = []
    sc = setcode
    while sc and sc != -1 and sc != 0:
        codes.append(sc & 0xFFFF)
        sc >>= 16
    return codes


def setname_of(setcode, setname_map):
    """返回该卡所属系列的中文名列表。"""
    names = []
    for sc in decompose_setcodes(setcode):
        # 低 12 位是主系列号，高 4 位是子系列
        main = sc & 0xFFF
        for key in (sc, main):
            if key in setname_map:
                nm = setname_map[key]
                if nm not in names:
                    names.append(nm)
                break
    return names


def decode_level(level):
    """level 字段是多义打包的，返回 (等级, 左刻度, 右刻度)。"""
    lv = level & 0xFF
    rscale = (level >> 16) & 0xFF
    lscale = (level >> 24) & 0xFF
    return lv, lscale, rscale


def card_kind(card_type):
    """返回主类型（低 3 位）。"""
    if card_type & 0x1:
        return "怪兽"
    if card_type & 0x2:
        return "魔法"
    if card_type & 0x4:
        return "陷阱"
    return "未知"


# ---------------------------------------------------------------- 导出
COLUMNS = [
    ("id", "卡片ID"),
    ("name", "卡名"),
    ("type", "类型掩码"),
    ("type_text", "类型"),
    ("card_kind", "主类型"),
    ("attribute", "属性掩码"),
    ("attribute_text", "属性"),
    ("race", "种族掩码"),
    ("race_text", "种族"),
    ("level", "等级原始值"),
    ("level_decoded", "等级"),
    ("lscale", "灵摆左刻度"),
    ("rscale", "灵摆右刻度"),
    ("link_marker_text", "连接标记"),
    ("atk", "攻击力"),
    ("def", "守备力"),
    ("ot", "卡池"),
    ("ot_text", "卡池说明"),
    ("alias", "别名"),
    ("setcode", "系列码"),
    ("setname", "所属系列"),
    ("category", "效果类别掩码"),
    ("desc", "效果文本"),
]


def export_lang(lang):
    cdb_path = os.path.join(CDB_DIR, lang, "cards.cdb")
    conf_path = os.path.join(CDB_DIR, lang, "strings.conf")
    if not os.path.exists(cdb_path):
        print(f"  跳过 {lang}：找不到 {cdb_path}")
        return None

    setname_map = load_setnames(conf_path)
    con = sqlite3.connect(f"file:{cdb_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT d.id, t.name, d.type, d.attribute, d.race, d.level, d.atk, d.def,"
        " d.ot, d.alias, d.setcode, d.category, t.desc"
        " FROM datas d JOIN texts t ON d.id = t.id ORDER BY d.id"
    ).fetchall()
    con.close()

    records = []
    for (cid, name, ctype, attr, race, level, atk, df, ot, alias,
         setcode, category, desc) in rows:
        lv, lscale, rscale = decode_level(level)
        is_link = bool(ctype & 0x4000000)
        # 连接怪兽：def 字段存的是链接箭头位图，不是守备力
        if is_link:
            link_marker = df
            defense = None
        else:
            link_marker = 0
            defense = df
        rec = {
            "id": cid,
            "name": name or "",
            "type": ctype,
            "type_text": "/".join(decode_bits(ctype, TYPE_BITS)),
            "type_text_en": "/".join(decode_bits_en(ctype, TYPE_BITS)),
            "card_kind": card_kind(ctype),
            "attribute": attr,
            "attribute_text": decode_one(attr, ATTR_BITS),
            "race": race,
            "race_text": "/".join(decode_bits(race, RACE_BITS)),
            "level": level,
            "level_decoded": lv,
            "lscale": lscale,
            "rscale": rscale,
            "link_marker": link_marker,
            "link_marker_text": "/".join(decode_bits(link_marker, LINK_MARKER_BITS)),
            "atk": atk,
            "def": defense,
            "ot": ot,
            "ot_text": OT_MAP.get(ot, str(ot)),
            "alias": alias,
            "setcode": setcode,
            "setname": "/".join(setname_of(setcode, setname_map)),
            "category": category,
            "desc": desc or "",
        }
        records.append(rec)

    # ---- 1. 原始 CSV
    raw_path = os.path.join(OUT_DIR, f"cards_{lang}.csv")
    with open(raw_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "ot", "alias", "setcode", "type", "atk", "def",
                    "level", "race", "attribute", "category", "name", "desc"])
        for r in records:
            w.writerow([r["id"], r["ot"], r["alias"], r["setcode"], r["type"],
                        r["atk"], r["def"] if r["def"] is not None else r["link_marker"],
                        r["level"], r["race"], r["attribute"], r["category"],
                        r["name"], r["desc"]])

    # ---- 2. 人类可读 CSV
    read_path = os.path.join(OUT_DIR, f"cards_{lang}.readable.csv")
    with open(read_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([c[1] for c in COLUMNS])
        for r in records:
            w.writerow([
                r["id"], r["name"], r["type"], r["type_text"], r["card_kind"],
                r["attribute"], r["attribute_text"], r["race"], r["race_text"],
                r["level"], r["level_decoded"], r["lscale"], r["rscale"],
                r["link_marker_text"], r["atk"],
                r["def"] if r["def"] is not None else "",
                r["ot"], r["ot_text"], r["alias"], r["setcode"], r["setname"],
                r["category"], r["desc"],
            ])

    # ---- 3. JSON
    json_path = os.path.join(OUT_DIR, f"cards_{lang}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1)

    # ---- 4. Markdown（按主类型分组）
    md_path = os.path.join(OUT_DIR, f"cards_{lang}.md")
    groups = {"怪兽": [], "魔法": [], "陷阱": [], "未知": []}
    for r in records:
        groups.setdefault(r["card_kind"], []).append(r)
    lines = [
        f"# 卡片数据库（{lang}）",
        "",
        f"> 共 **{len(records)}** 张卡",
        "> 数据来源：`cdb/{lang}/cards.cdb`",
        "",
        "| 主类型 | 数量 |",
        "|---|---|",
    ]
    for k in ("怪兽", "魔法", "陷阱", "未知"):
        if groups.get(k):
            lines.append(f"| {k} | {len(groups[k])} |")
    lines.append("")

    for k in ("怪兽", "魔法", "陷阱"):
        if not groups.get(k):
            continue
        lines.append(f"## {k}（{len(groups[k])} 张）")
        lines.append("")
        for r in groups[k]:
            # 卡片标题行
            meta = []
            if r["attribute_text"]:
                meta.append(r["attribute_text"])
            if r["race_text"]:
                meta.append(r["race_text"])
            is_link_card = "连接" in r["type_text"]
            is_xyz = "超量" in r["type_text"]
            if r["level_decoded"]:
                if is_link_card:
                    meta.append(f"LINK{r['level_decoded']}")
                elif is_xyz:
                    meta.append(f"阶级{r['level_decoded']}")
                else:
                    meta.append(f"{r['level_decoded']}星")
            if r["lscale"] or r["rscale"]:
                meta.append(f"刻度{r['lscale']}/{r['rscale']}")
            if r["atk"] is not None:
                atk = "?" if r["atk"] == -2 else r["atk"]
                dfv = r["def"]
                dfs = "?" if dfv == -2 else ("" if dfv is None else dfv)
                meta.append(f"攻{atk}/守{dfs}" if dfs != "" else f"攻{atk}")
            if r["link_marker_text"]:
                meta.append(f"链接[{r['link_marker_text']}]")
            suffix = ("　" + "　".join(meta)) if meta else ""
            lines.append(f"### {r['name']}　`{r['id']}`")
            lines.append("")
            lines.append(f"- 类型：{r['type_text'] or '—'}{suffix}")
            if r["setname"]:
                lines.append(f"- 系列：{r['setname']}")
            lines.append(f"- 卡池：{r['ot_text']}")
            if r["desc"]:
                lines.append("")
                lines.append("> " + r["desc"].replace("\n", "  \n> "))
            lines.append("")
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {
        "lang": lang,
        "count": len(records),
        "raw": os.path.getsize(raw_path),
        "readable": os.path.getsize(read_path),
        "json": os.path.getsize(json_path),
        "md": os.path.getsize(md_path),
        "setnames": len(setname_map),
    }


def main():
    langs = sys.argv[1:] or ["zh-CN", "en-US", "ja-JP"]
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 68)
    results = []
    for lang in langs:
        print(f"导出 {lang} ...")
        info = export_lang(lang)
        if info:
            results.append(info)
    print("=" * 68)
    print(f"{'语言':<8}{'卡片数':>8}{'原始CSV':>12}{'可读CSV':>12}{'JSON':>12}{'Markdown':>12}")
    for r in results:
        print(f"{r['lang']:<8}{r['count']:>8}{r['raw']:>12,}{r['readable']:>12,}"
              f"{r['json']:>12,}{r['md']:>12,}")
    print("=" * 68)
    print(f"输出目录：{OUT_DIR}")


if __name__ == "__main__":
    main()
