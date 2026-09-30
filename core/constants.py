# -*- coding: utf-8 -*-
"""常量定义：位掩码、枚举、种族/属性名表。

来源：docs/card_effects规则.md §1.2 / §6，以及实测位布局验证（速攻 0x10000、
永续 0x20000、装备 0x40000、场地 0x80000、反击 0x100000 与 YGOPro 标准一致）。
"""

# ---------- datas.type 大类 ----------
TYPE_MONSTER = 0x1
TYPE_SPELL = 0x2
TYPE_TRAP = 0x4
TYPE_NORMAL = 0x10
TYPE_EFFECT = 0x20
TYPE_FUSION = 0x40
TYPE_RITUAL = 0x80
TYPE_TRAPMONSTER = 0x100
TYPE_SPIRIT = 0x200
TYPE_UNION = 0x400
TYPE_DUAL = 0x800
TYPE_TUNER = 0x1000
TYPE_SYNCHRO = 0x2000
TYPE_TOKEN = 0x4000
TYPE_QUICKPLAY = 0x10000
TYPE_CONTINUOUS = 0x20000
TYPE_EQUIP = 0x40000
TYPE_FIELD = 0x80000
TYPE_COUNTER = 0x100000
TYPE_FLIP = 0x200000
TYPE_TOON = 0x400000
TYPE_XYZ = 0x800000
TYPE_PENDULUM = 0x1000000
TYPE_SPSUMMON = 0x2000000   # 特殊召唤专属（不能通常召唤），实测：熔岩魔神等
TYPE_LINK = 0x4000000

# ---------- 属性（位掩码） ----------
ATTRIBUTE_BITS = {
    0x01: "地",
    0x02: "水",
    0x04: "炎",
    0x08: "风",
    0x10: "光",
    0x20: "暗",
    0x40: "神",
}

# ---------- 种族（位掩码，64 位） ----------
RACE_BITS = {
    0x1: "战士",
    0x2: "魔法师",
    0x4: "天使",
    0x8: "恶魔",
    0x10: "不死",
    0x20: "机械",
    0x40: "水族",
    0x80: "炎",
    0x100: "岩石",
    0x200: "鸟兽",
    0x400: "植物",
    0x800: "昆虫",
    0x1000: "雷",
    0x2000: "龙",
    0x4000: "兽",
    0x8000: "兽战士",
    0x10000: "恐龙",
    0x20000: "鱼",
    0x40000: "海龙",
    0x80000: "爬虫类",
    0x100000: "念动力",
    0x200000: "幻神兽",
    0x400000: "创造神",
    0x800000: "幻龙",
    0x1000000: "电子界",
    0x2000000: "幻想魔",
}

# ---------- type 细分标签（UI + DSL 白名单） ----------
# label -> (位, 适用的主类型); main: m=怪兽 s=魔法 t=陷阱 ms=魔陷 all
TYPE_LABELS = [
    ("通常", TYPE_NORMAL, "all"),
    ("效果", TYPE_EFFECT, "m"),
    ("仪式", TYPE_RITUAL, "ms"),
    ("融合", TYPE_FUSION, "m"),
    ("同调", TYPE_SYNCHRO, "m"),
    ("超量", TYPE_XYZ, "m"),
    ("灵摆", TYPE_PENDULUM, "m"),
    ("连接", TYPE_LINK, "m"),
    ("调整", TYPE_TUNER, "m"),
    ("反转", TYPE_FLIP, "m"),
    ("灵魂", TYPE_SPIRIT, "m"),
    ("联合", TYPE_UNION, "m"),
    ("二重", TYPE_DUAL, "m"),
    ("卡通", TYPE_TOON, "m"),
    ("特殊召唤", TYPE_SPSUMMON, "m"),
    ("陷阱怪兽", TYPE_TRAPMONSTER, "m"),
    ("速攻", TYPE_QUICKPLAY, "s"),
    ("永续", TYPE_CONTINUOUS, "ms"),
    ("装备", TYPE_EQUIP, "s"),
    ("场地", TYPE_FIELD, "s"),
    ("反击", TYPE_COUNTER, "t"),
]

# ---------- ot 卡池 ----------
OT_LABELS = {
    1: "OCG",
    2: "TCG",
    3: "OCG/TCG",
    4: "简中/OCG",
    8: "简中独有",
    9: "简中/OCG",
    11: "简中/OCG/TCG",
}

# ---------- category 32 位（§6） ----------
CATEGORY_BITS = [
    (0x1, "魔陷破坏"),
    (0x2, "怪兽破坏"),
    (0x4, "卡片除外"),
    (0x8, "送去墓地"),
    (0x10, "返回手卡"),
    (0x20, "返回卡组"),
    (0x40, "手卡破坏"),
    (0x80, "卡组破坏"),
    (0x100, "抽卡辅助"),
    (0x200, "卡组检索"),
    (0x400, "卡片回收"),
    (0x800, "表示形式"),
    (0x1000, "控制权"),
    (0x2000, "攻守变化"),
    (0x4000, "穿刺伤害"),
    (0x8000, "多次攻击"),
    (0x10000, "攻击限制"),
    (0x20000, "直接攻击"),
    (0x40000, "特殊召唤"),
    (0x80000, "衍生物"),
    (0x100000, "种族相关"),
    (0x200000, "属性相关"),
    (0x400000, "LP伤害"),
    (0x800000, "LP回复"),
    (0x1000000, "破坏耐性"),
    (0x2000000, "效果耐性"),
    (0x4000000, "指示物"),
    (0x8000000, "幸运"),
    (0x10000000, "融合相关"),
    (0x20000000, "同调相关"),
    (0x40000000, "超量相关"),
    (0x80000000, "效果无效"),
]

# ---------- 五维枚举 ----------
TARGETS_VALUES = {1, 0}  # NULL(-1) 不适用
ACTIVATION_VALUES = ["ignition", "trigger", "quick", "continuous", "none"]
ACTIVATION_ZH = {
    "ignition": "起动效果",
    "trigger": "诱发效果",
    "quick": "诱发即时效果",
    "continuous": "永续效果",
    "none": "规则文本",
}
LOCATION_VALUES = ["hand", "field", "grave", "banished", "deck"]
LOCATION_ZH = {
    "hand": "手卡",
    "field": "场上",
    "grave": "墓地",
    "banished": "除外",
    "deck": "卡组",
}
TIMING_VALUES = ["when_optional", "if_optional", "if_mandatory"]
TIMING_ZH = {
    "when_optional": "「时」选发（会错过时点）",
    "if_optional": "「场合」选发（不会错过时点）",
    "if_mandatory": "「场合」必发",
}
NEGATE_VALUES = ["activation", "effect"]
NEGATE_ZH = {
    "activation": "发动无效",
    "effect": "效果无效",
}
SEG_TYPES = ["monster", "pendulum", "spell_trap", "rule", "flavor"]

# ---------- level 打包字段 ----------
def unpack_level(level: int):
    """返回 (等级/阶级/LINK, 左刻度, 右刻度)。"""
    lv = level & 0xFF
    lscale = (level >> 24) & 0xFF
    rscale = (level >> 16) & 0xFF
    return lv, lscale, rscale


def unpack_setcodes(setcode: int):
    """setcode 每 16 位打包一个系列，低 12 位是主系列号。"""
    out = []
    for i in range(4):
        v = (setcode >> (i * 16)) & 0xFFFF
        if v:
            out.append(v & 0xFFF)
    return out
