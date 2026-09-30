# -*- coding: utf-8 -*-
"""金标集回归测试（规则文档 §8.4）。

断言来源：文档 §8 金标清单（含答案）+ 本实现过程中逐张阅读原文后人工标注的卡。
要求 100% 通过；失败即修规则，不许放过。

直接运行：python tests/test_golden.py
"""
import io
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import effect_splitter as sp
import effect_classifier as cl

ZH_DB = str(ROOT / "cdb" / "zh-CN" / "cards.cdb")
JA_DB = str(ROOT / "cdb" / "ja-JP" / "cards.cdb")
BUILD_DB = str(ROOT / "build" / "card_effects.db")

zh_conn = sqlite3.connect(ZH_DB)
ja_conn = sqlite3.connect(JA_DB)

_PASS = 0
_FAIL = 0
_FAILURES = []


def get_segments(card_id: int):
    """直接从构建产物读段（与全库构建一致），None 表示卡不存在。"""
    rows = sqlite3.connect(BUILD_DB).execute(
        "SELECT effect_no, seg_type, targets, activation, location, timing, "
        "negate_type, seg_category FROM card_effects WHERE card_id=?",
        (card_id,)).fetchall()
    return {(r[0], r[1]): dict(no=r[0], seg_type=r[1], targets=r[2],
                               activation=r[3], location=r[4], timing=r[5],
                               negate_type=r[6], seg_category=r[7])
            for r in rows}


def check(label: str, cond: bool, detail: str = ""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
    else:
        _FAIL += 1
        _FAILURES.append(f"{label} {detail}")
        print(f"  FAIL: {label} {detail}")


def seg(card_id, no, seg_type="monster"):
    s = get_segments(card_id).get((no, seg_type))
    if s is None:
        raise KeyError(f"card {card_id} has no segment ({no},{seg_type})")
    return s


# ============================================================
# 1. 文档 §8 金标清单（含答案）
# ============================================================
print("== 文档金标清单 ==")

# 破灭与终焉之支配者 ③：targets=0, ignition, field, 主动破坏
s = seg(3739500, 3)
check("破灭③ targets=0", s["targets"] == 0, f"got {s['targets']}")
check("破灭③ ignition", s["activation"] == "ignition", f"got {s['activation']}")
check("破灭③ field", s["location"] == "field", f"got {s['location']}")
check("破灭③ 主动破坏(双位)", s["seg_category"] & 0x3 == 0x3,
      f"cat=0x{s['seg_category']:x}")

# 装弹枪管暴动龙 ① targets=0 quick；② targets=1 grave
s = seg(7987191, 1)
check("装弹① targets=0", s["targets"] == 0, f"got {s['targets']}")
check("装弹① quick", s["activation"] == "quick", f"got {s['activation']}")
s = seg(7987191, 2)
check("装弹② targets=1", s["targets"] == 1, f"got {s['targets']}")
check("装弹② grave", s["location"] == "grave", f"got {s['location']}")

# 灰流丽：hand, trigger/quick, targets=0
for cid in (14558127, 14558128):  # 本体 + alias 再版
    s = seg(cid, 1)
    check(f"灰流丽({cid}) hand", s["location"] == "hand", f"got {s['location']}")
    check(f"灰流丽({cid}) trigger/quick",
          s["activation"] in ("trigger", "quick"), f"got {s['activation']}")
    check(f"灰流丽({cid}) targets=0", s["targets"] == 0, f"got {s['targets']}")

# 神光之宣告者：field（cost 从手卡≠手卡发动）, negate_type=activation, targets=0
s = seg(44665365, 1)
check("神光 field", s["location"] == "field", f"got {s['location']}")
check("神光 negate=activation", s["negate_type"] == "activation",
      f"got {s['negate_type']}")
check("神光 targets=0", s["targets"] == 0, f"got {s['targets']}")

# 技能抽取：continuous, negate_type=effect
s = seg(82732705, 1, "spell_trap")
check("技能抽取 continuous", s["activation"] == "continuous",
      f"got {s['activation']}")
check("技能抽取 negate=effect", s["negate_type"] == "effect",
      f"got {s['negate_type']}")

# 魔术师的法阵 ①：when_optional（攻撃宣言時に発動できる）
s = seg(50755, 1, "spell_trap")
check("法阵 when_optional", s["timing"] == "when_optional",
      f"got {s['timing']}")

# 奈芙提斯之苍凰神 ①：targets=0（「选」≠取对象）, 主动破坏
s = seg(24175232, 1)
check("奈芙提斯① targets=0", s["targets"] == 0, f"got {s['targets']}")
check("奈芙提斯① 主动破坏", s["seg_category"] & 0x2 != 0,
      f"cat=0x{s['seg_category']:x}")

# 青眼混沌极龙：continuous, seg_category=耐性位
s = seg(55410871, 1)
check("青眼混沌极龙 continuous", s["activation"] == "continuous",
      f"got {s['activation']}")
check("青眼混沌极龙 耐性位", s["seg_category"] & 0x3000000 == 0x3000000,
      f"cat=0x{s['seg_category']:x}")

# 终焉之王 迪米斯 ①：targets=0, ignition, 全场破坏（双破坏位）
s = seg(72426662, 1)
check("迪米斯 targets=0", s["targets"] == 0, f"got {s['targets']}")
check("迪米斯 ignition", s["activation"] == "ignition",
      f"got {s['activation']}")
check("迪米斯 双破坏位", s["seg_category"] & 0x3 == 0x3,
      f"cat=0x{s['seg_category']:x}")

# ============================================================
# 2. 切分结构金标（阅读原文后标注）
# ============================================================
print("== 切分结构 ==")

# DD 魔导贤者 托马斯：P 段 no=-1 + 怪兽段 no=1 + rule 段
allseg = get_segments(41546)
check("DD P段存在(-1,pendulum)", (-1, "pendulum") in allseg)
check("DD 怪兽段存在(1,monster)", (1, "monster") in allseg)
check("DD rule段存在(0,rule)", (0, "rule") in allseg)
p = allseg[(-1, "pendulum")]
check("DD P段 ignition", p["activation"] == "ignition", f"got {p['activation']}")
check("DD P段 location=field(P区,§9.6)", p["location"] == "field",
      f"got {p['location']}")
m = allseg[(1, "monster")]
check("DD 怪兽① targets=1", m["targets"] == 1, f"got {m['targets']}")

# 雾动机龙·腕龙 P段：無効にできる（无発動できる）→ continuous, targets NULL
p = seg(368382, -1, "pendulum")
check("雾动机龙P continuous", p["activation"] == "continuous",
      f"got {p['activation']}")
check("雾动机龙P targets=NULL", p["targets"] is None, f"got {p['targets']}")
check("雾动机龙P 自毁不加破坏位", p["seg_category"] & 0x3 == 0,
      f"cat=0x{p['seg_category']:x}")

# 白银之城的狂时钟 ①：quick + hand；②：grave + trigger + targets=0
s = seg(2511, 1)
check("狂时钟① quick", s["activation"] == "quick", f"got {s['activation']}")
check("狂时钟① hand", s["location"] == "hand", f"got {s['location']}")
s = seg(2511, 2)
check("狂时钟② grave", s["location"] == "grave", f"got {s['location']}")
check("狂时钟② trigger", s["activation"] == "trigger",
      f"got {s['activation']}")
check("狂时钟② targets=0", s["targets"] == 0, f"got {s['targets']}")

# 暗晦之城 ①：反转必发（場合に発動する）→ trigger + if_mandatory
s = seg(62121, 1)
check("暗晦之城① trigger", s["activation"] == "trigger",
      f"got {s['activation']}")
check("暗晦之城① if_mandatory", s["timing"] == "if_mandatory",
      f"got {s['timing']}")

# 熔岩枪杖手 ③：被破坏时（時+できる）→ trigger + when_optional + targets=1
s = seg(123709, 3)
check("熔岩枪杖手③ trigger", s["activation"] == "trigger",
      f"got {s['activation']}")
check("熔岩枪杖手③ when_optional", s["timing"] == "when_optional",
      f"got {s['timing']}")
check("熔岩枪杖手③ targets=1", s["targets"] == 1, f"got {s['targets']}")

# 板块轰击者 ①：cost-only 起动 → ignition，timing NULL
s = seg(114932, 1)
check("板块轰击者 ignition", s["activation"] == "ignition",
      f"got {s['activation']}")
check("板块轰击者 timing=NULL", s["timing"] is None, f"got {s['timing']}")

# 通常怪兽 / 衍生物 → flavor，不参与检索
s = seg(32864, 1, "flavor")
check("埋葬者 flavor", s["seg_type"] == "flavor")
s = seg(176393, 1, "flavor")
check("核成衍生物 flavor", s["seg_type"] == "flavor")

# 魔法：圣魔 裁决之雷 ①（含●分支不拆段）单段继承官方 category
zcat = zh_conn.execute("SELECT category FROM datas WHERE id=59080").fetchone()[0]
s = seg(59080, 1, "spell_trap")
check("圣魔① 单段继承category", s["seg_category"] == zcat,
      f"got 0x{s['seg_category']:x} want 0x{zcat:x}")
check("圣魔① targets=0", s["targets"] == 0, f"got {s['targets']}")

# 英雄一闪（zh 无编号 / ja ①）：spell_trap 单段 ignition
s = seg(191749, 1, "spell_trap")
check("英雄一闪 ignition", s["activation"] == "ignition",
      f"got {s['activation']}")

# 陷阱：编号系之壁 ①：永续
s = seg(847915, 1, "spell_trap")
check("编号系之壁 continuous", s["activation"] == "continuous",
      f"got {s['activation']}")

# 黑魔导强化：实测 type=0x10002（速攻魔法位）→ 主段 quick；●分支不拆段
s = seg(111280, 1, "spell_trap")
check("黑魔导强化 quick(速攻)", s["activation"] == "quick",
      f"got {s['activation']}")

# 电子界代码魔术师 ②：墓地·手卡送去墓地的场合 → trigger + if_optional, targets=0
s = seg(64865, 2)
check("代码魔术师② trigger", s["activation"] == "trigger",
      f"got {s['activation']}")
check("代码魔术师② if_optional", s["timing"] == "if_optional",
      f"got {s['timing']}")
check("代码魔术师② targets=0", s["targets"] == 0, f"got {s['targets']}")

# ============================================================
# 3. 基准查询数据完整性
# ============================================================
print("== 基准查询 ==")

prod = sqlite3.connect(BUILD_DB)
prod.execute("ATTACH DATABASE ? AS cards", (ZH_DB,))
# 「不取对象破坏的仪式怪兽」与文档手写版对照：
# category 粗筛 160 → 36（官方破坏位）→ 效果段精修 22 张。
# 口径：破坏须为效果自身的动作，「那个发动无效并破坏」属无效的附带破坏，不计
# （negate_type 非空的段排除）。§7 示例 SQL 无此排除，按参考答案反推得出。
n = prod.execute(
    "SELECT COUNT(DISTINCT e.card_id) FROM card_effects e "
    "JOIN cards.datas d ON e.card_id=d.id "
    "WHERE d.type & 0x81 = 0x81 AND e.targets=0 "
    "AND (e.seg_category & 0x3)!=0 AND e.negate_type IS NULL").fetchone()[0]
check("基准查询 = 22（160→36→22 与文档实测一致）", n == 22, f"got {n}")
# 不含 negate 排除的宽口径（§7 示例 SQL 原样）= 29，报告中说明
n2 = prod.execute(
    "SELECT COUNT(DISTINCT e.card_id) FROM card_effects e "
    "JOIN cards.datas d ON e.card_id=d.id "
    "WHERE d.type & 0x81 = 0x81 AND e.targets=0 "
    "AND (e.seg_category & 0x3)!=0").fetchone()[0]
check("宽口径 = 29（含无效附带破坏）", n2 == 29, f"got {n2}")

# 「会错过时点」= timing=when_optional 非空
n = sqlite3.connect(BUILD_DB).execute(
    "SELECT COUNT(DISTINCT card_id) FROM card_effects "
    "WHERE timing='when_optional'").fetchone()[0]
check("when_optional 结果集非空", n > 100, f"got {n}")

print(f"\n===== 金标回归: {_PASS} 通过 / {_FAIL} 失败 =====")
if _FAILURES:
    print("失败清单:")
    for f in _FAILURES:
        print(f"  - {f}")
    sys.exit(1)
