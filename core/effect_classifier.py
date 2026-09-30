# -*- coding: utf-8 -*-
"""五维分类器 + 段级 category（规则文档 §4、§5）。

统一技巧（§4 开篇）：只在"发动条件子句"里找取对象/位置/时点证据，
条件子句 = 段首到「発動できる/発動する」（ja）或「才能发动」（zh）之间的部分。
ja 为主判定语言（§1.1 / §9.3），zh 仅对照。
"""
import re
from typing import Dict, Optional, Tuple

import constants as C

# ---------- 条件子句定位 ----------
JA_VERB_RE = re.compile(r"発動できる|発動する")
ZH_VERB_RE = re.compile(r"才能发动")

# ---------- §4.1 取对象 ----------
JA_TARGET_POS_RE = re.compile(r"を対象と(して|する)|対象として発動|選択して発動")
JA_TARGET_NEG_RE = re.compile(r"対象と(せず|できない|られない)|対象にできない|対象を選ばず")
ZH_TARGET_POS_RE = re.compile(r"以.{1,16}为对象|选择.{0,12}(发动|才能)")

# ---------- §4.2 发动类型 ----------
JA_OPP_TURN_RE = re.compile(r"相手ターン")
ZH_OPP_TURN_RE = re.compile(r"对方回合")
# 怪兽效果的条件子句以「相手が」（对方为动作主体）开头的事件 → 实际二速（金标：装弹枪管暴动龙①）
JA_OPP_ACTOR_RE = re.compile(r"相手が")
ZH_OPP_ACTOR_RE = re.compile(r"对方(把|将)")
JA_EVENT_RE = re.compile(r"場合|時|際|たとき|したとき")
ZH_EVENT_RE = re.compile(r"场合|时|之际")
JA_MAIN_PHASE_RE = re.compile(r"メインフェイズ")
JA_ACTIVATE_RE = re.compile(r"発動できる|発動する")
ZH_ACTIVATE_RE = re.compile(r"发动")

# ---------- §4.3 发动位置（在条件子句中找） ----------
LOCATION_PATTERNS = [
    # (value, ja, zh)
    ("banished",
     re.compile(r"除外されているこのカード|このカードが除外された|除外されたこのカード"),
     re.compile(r"除外的这张卡|这张卡被除外")),
    ("grave",
     re.compile(r"このカードが墓地に|墓地のこのカード|墓地存在する状態で?このカード"),
     re.compile(r"这张卡在墓地|墓地的这张卡|墓地存在的状态")),
    ("hand",
     re.compile(r"このカードを手札から|手札のこのカード|手札から(捨てて|見せて)|手札から発動"),
     re.compile(r"手卡的这张卡|从手卡(把这张卡|丢弃|给对方观看)|这张卡从手卡")),
    ("deck",
     re.compile(r"デッキのこのカード|このカードをデッキから|デッキから発動"),
     re.compile(r"卡组的这张卡|这张卡从卡组|从卡组发动")),
]

# ---------- §4.4 时点 ----------
JA_WHEN_RE = re.compile(r"時|とき")
JA_IF_RE = re.compile(r"場合")
# 注意：「際/之际」规则文档 §4.4 未覆盖（不會錯過時点，近似場合），按纪律不擅自扩规则 → NULL
ZH_WHEN_RE = re.compile(r"时(，|,|才能|$)")
ZH_IF_RE = re.compile(r"场合")

# ---------- §4.5 无效类型 ----------
JA_NEGATE_ACT_RE = re.compile(r"発動を無効|発動は無効|発動無効|の発動にできない|発動できないようにする")
JA_NEGATE_EFF_RE = re.compile(r"効果を無効|効果は無効|効果無効|効果の無効化|無効化され|無効にする")
ZH_NEGATE_ACT_RE = re.compile(r"发动无效|发动的无效|不能发动")
ZH_NEGATE_EFF_RE = re.compile(r"效果无效|的效果无效化|无效化")
# 召唤无效不算本维度（§4.5）：判定前从文本剥离
JA_SUMMON_NEGATE_RE = re.compile(r"(特殊召喚|召喚)を無効|その特殊召喚")
ZH_SUMMON_NEGATE_RE = re.compile(r"特殊召唤无效|召唤无效|那次特殊召唤")

# ---------- §5.1 破坏主动/被动 ----------
JA_DESTROY_PASSIVE_RE = re.compile(
    r"破壊されない|破壊され(?:た場合|た時|る時|る場合|た際|ない)|破壊を(?:代替|免れる)|"
    r"身代わり|代わりに.{0,20}破壊|破壊されず")
ZH_DESTROY_PASSIVE_RE = re.compile(
    r"不会被.{0,10}破坏|破坏的场合|破坏的时|作为代替.{0,16}破坏|代替.{0,8}破坏|不会被破坏")
# 自毁（这张卡自身的破坏）不是对对方的主动破坏动作，剥离后再判（审计对齐官方语义）
# 负向断言：『Aとこのカードを破壊』这种联合宾语不算纯自毁（と/和为并列连词）；
# 而句读「、/，」前的仍按自毁剥离
JA_SELF_DESTROY_RE = re.compile(r"(?<!と)このカードを破壊(?:する|し|して)?")
ZH_SELF_DESTROY_RE = re.compile(r"(?<![和与・跟])这张卡破坏")
JA_DESTROY_ACTIVE_RE = re.compile(r"破壊する|破壊し|破壊。|破壊させる")
ZH_DESTROY_ACTIVE_RE = re.compile(r"破坏。|破坏，|破坏;")
JA_DESTROY_MON_RE = re.compile(r"モンスターを破壊|モンスターを(選んで|選択して)?破壊")
ZH_DESTROY_MON_RE = re.compile(r"怪兽破坏|怪兽.*破坏|破坏.*怪兽")
JA_DESTROY_ST_RE = re.compile(r"魔法・罠|魔法＆罠|魔法・トラップ")
ZH_DESTROY_ST_RE = re.compile(r"魔法·陷阱|魔法与陷阱|魔陷")
JA_DESTROY_ALL_RE = re.compile(r"(フィールド|フィールド上)の(他の)?カードを?(全部|すべて|全て)?破壊")
ZH_DESTROY_ALL_RE = re.compile(r"场上.{0,4}卡.{0,4}破坏|场上的卡全部破坏")


def find_clause(seg_ja: str, seg_zh: str) -> Tuple[str, str]:
    """返回 (clause_ja, clause_zh)：段首到第一个发动动词之前。无动词则整段。"""
    m = JA_VERB_RE.search(seg_ja)
    clause_ja = seg_ja[:m.start()] if m else seg_ja
    m2 = ZH_VERB_RE.search(seg_zh)
    clause_zh = seg_zh[:m2.start()] if m2 else seg_zh
    return clause_ja, clause_zh


# 选分支不是取对象（金标：圣魔 裁决之雷「以下の効果から１つを選択して発動」）
JA_BRANCH_SELECT_RE = re.compile(r"以下の効果から[１1]つを?選択して")
ZH_BRANCH_SELECT_RE = re.compile(r"从以下效果选择[1１１]个")


def classify_targets(seg: Dict) -> Optional[int]:
    """§4.1。返回 1/0/None。"""
    if seg["activation"] in ("continuous", "none"):
        return None
    cj, cz = seg["_clause_ja"], seg["_clause_zh"]
    cj = JA_BRANCH_SELECT_RE.sub("", cj)
    cz = ZH_BRANCH_SELECT_RE.sub("", cz)
    if JA_TARGET_NEG_RE.search(cj):
        return 0
    if JA_TARGET_POS_RE.search(cj):
        return 1
    # zh 对照（ja 判不出时以 zh 兜底，仅当 zh 也很明确）
    if ZH_TARGET_POS_RE.search(cz):
        return 1
    return 0


def classify_activation(seg: Dict, card_type: int) -> str:
    """§4.2。优先级 quick > trigger > ignition > continuous；rule 段 = none。"""
    if seg["seg_type"] == "rule":
        return "none"
    ja, zh = seg["text_ja"], seg["text_zh"]
    cj, cz = seg["_clause_ja"], seg["_clause_zh"]

    has_verb = bool(JA_ACTIVATE_RE.search(ja))
    # ① 反击陷阱 / 速攻魔法主段：天然咒文速度 2
    if (card_type & C.TYPE_TRAP and card_type & C.TYPE_COUNTER
            and seg["seg_type"] == "spell_trap"):
        return "quick"
    if (card_type & C.TYPE_SPELL and card_type & C.TYPE_QUICKPLAY
            and seg["seg_type"] == "spell_trap"):
        return "quick"
    # ② 对方回合可发动 → quick
    if (JA_OPP_TURN_RE.search(cj) or ZH_OPP_TURN_RE.search(cz)) and (
            has_verb or ZH_ACTIVATE_RE.search(zh)):
        return "quick"
    # ②' 怪兽效果、条件子句以「相手が/对方把」引出对方动作事件 → 实际二速（金标装弹①）
    if seg["seg_type"] == "monster" and (
            JA_OPP_ACTOR_RE.search(cj) or ZH_OPP_ACTOR_RE.search(cz)) and has_verb:
        return "quick"
    # ③ 事件词 → trigger
    if JA_EVENT_RE.search(cj) and has_verb:
        return "trigger"
    # ④ 含动词 → ignition（§4.2 默认）
    if has_verb:
        return "ignition"
    # ⑤ 无发动语义 → continuous
    return "continuous"


def classify_location(seg: Dict) -> Optional[str]:
    """§4.3。锚点「このカード/这张卡」的位置表述；默认 field。"""
    if seg["activation"] in ("continuous", "none"):
        return None
    cj, cz = seg["_clause_ja"], seg["_clause_zh"]
    for value, jre, zre in LOCATION_PATTERNS:
        if jre.search(cj) or zre.search(cz):
            return value
    return "field"


def classify_timing(seg: Dict) -> Optional[str]:
    """§4.4。仅 trigger/quick；只存原子标签。"""
    if seg["activation"] not in ("trigger", "quick"):
        return None
    cj, cz = seg["_clause_ja"], seg["_clause_zh"]
    mandatory_ja = JA_VERB_RE.search(seg["text_ja"])
    verb_ja = mandatory_ja.group(0) if mandatory_ja else ""
    optional = verb_ja == "発動できる" or ZH_VERB_RE.search(seg["text_zh"])
    # ja 判定：条件子句中 時/場合
    has_when_ja = bool(JA_WHEN_RE.search(cj))
    has_if_ja = bool(JA_IF_RE.search(cj))
    if has_when_ja and not has_if_ja:
        return "when_optional" if optional else None      # 時に発動する → 待 LLM
    if has_if_ja and not has_when_ja:
        return "if_optional" if optional else "if_mandatory"
    if has_if_ja and has_when_ja:
        # 子句同时含两者：看靠后的（靠近动词的是真正模板词）
        if cj.rfind("場合") > cj.rfind("時"):
            return "if_optional" if optional else "if_mandatory"
        return "when_optional"
    # ja 判不出，zh 对照
    if ZH_IF_RE.search(cz):
        return "if_optional" if optional else "if_mandatory"
    if ZH_WHEN_RE.search(cz):
        return "when_optional" if optional else None
    return None


def classify_negate(seg: Dict) -> Optional[str]:
    """§4.5。発動を無効 优先于 効果を無効；召唤无效不算本维度。"""
    ja, zh = seg["text_ja"], seg["text_zh"]
    # 剥离召唤无效语义（其后的無効にする等词不应计入效果无效）
    ja = JA_SUMMON_NEGATE_RE.sub("", ja)
    zh = ZH_SUMMON_NEGATE_RE.sub("", zh)
    if JA_NEGATE_ACT_RE.search(ja) or ZH_NEGATE_ACT_RE.search(zh):
        return "activation"
    if JA_NEGATE_EFF_RE.search(ja) or ZH_NEGATE_EFF_RE.search(zh):
        return "effect"
    return None


def _strip_passive(text: str) -> str:
    """去掉被动破坏句式，剩余文本用于主动破坏判定（§5.1）。"""
    out = JA_DESTROY_PASSIVE_RE.sub("", text)
    out = ZH_DESTROY_PASSIVE_RE.sub("", out)
    return out


def _processing_part(seg: Dict):
    """§5.1：破坏方向只在效果处理部分判，不在条件子句。返回 (ja_proc, zh_proc)。"""
    ja, zh = seg["text_ja"], seg["text_zh"]
    m = JA_VERB_RE.search(ja)
    ja_proc = ja[m.end():] if m else ja
    m2 = ZH_VERB_RE.search(zh)
    zh_proc = zh[m2.end():] if m2 else zh
    return ja_proc, zh_proc


def refine_destroy_category(cat: int, seg: Dict) -> int:
    """§5 段级 category 精化（破坏位方向判定）。返回精化后的位值。

    - 段内无任何破坏语义 → 非破坏段，清掉粗继承来的破坏位；
    - 全为被动/自毁/代替句式 → 非主动破坏，清破坏位；
    - 主动破坏 → 按对象挂 0x1/0x2。
    """
    ja, zh = seg["text_ja"], seg["text_zh"]
    if not re.search(r"破壊|破坏", ja + zh):
        return cat & ~(0x1 | 0x2)
    ja_proc, zh_proc = _processing_part(seg)
    # 剥离被动句式 + 自毁/代替破坏，剩余才用于主动判定
    ja_core = JA_SELF_DESTROY_RE.sub("", ja_proc)
    zh_core = ZH_SELF_DESTROY_RE.sub("", zh_proc)
    ja_core = JA_DESTROY_PASSIVE_RE.sub("", ja_core)
    zh_core = ZH_DESTROY_PASSIVE_RE.sub("", zh_core)
    active = bool(JA_DESTROY_ACTIVE_RE.search(ja_core)) or \
        bool(ZH_DESTROY_ACTIVE_RE.search(zh_core))
    if active:
        mon = bool(JA_DESTROY_MON_RE.search(ja_core)) or \
            bool(ZH_DESTROY_MON_RE.search(zh_core))
        st = bool(JA_DESTROY_ST_RE.search(ja_core)) or \
            bool(ZH_DESTROY_ST_RE.search(zh_core))
        generic_card = bool(re.search(r"(カード|卡)を?(全部|すべて|全て)?破壊", ja_core)) or \
            bool(ZH_DESTROY_ALL_RE.search(zh_core))
        if generic_card and not (mon or st):
            # 泛指"那张卡/场上的卡"破坏 → 双位
            return cat | 0x1 | 0x2
        if mon and st:
            return cat | 0x1 | 0x2
        if mon:
            return cat | 0x2
        if st:
            return cat | 0x1
        return cat | 0x1 | 0x2
    # 全部为被动/自毁/代替句式 → 非主动破坏，清破坏位（§5.1）
    return cat & ~(0x1 | 0x2)


def classify_segment(seg: Dict, card_type: int, card_category: int,
                     multi_effect: bool) -> Dict:
    """对单个效果段（rule/flavor 之外）执行五维分类 + 段级 category。

    §5：段级 category 以卡片 category 为起点（粗），段内破坏语义可模板判定时
    做方向精化（§5.1）；单效果卡同样适用（官方多标如『被破坏时特召』会被清掉）。
    """
    seg["_clause_ja"], seg["_clause_zh"] = find_clause(seg["text_ja"], seg["text_zh"])
    seg["activation"] = classify_activation(seg, card_type)
    seg["targets"] = classify_targets(seg)
    seg["location"] = classify_location(seg)
    seg["timing"] = classify_timing(seg)
    seg["negate_type"] = classify_negate(seg)
    seg["seg_category"] = refine_destroy_category(card_category, seg)
    return seg


def annotate(segments: list, card_type: int, card_category: int) -> list:
    """整卡打标入口：segments 来自 effect_splitter.split_card()。"""
    eff_segs = [s for s in segments
                if s["seg_type"] in ("monster", "pendulum", "spell_trap")]
    multi = len(eff_segs) > 1
    out = []
    for s in segments:
        if s["seg_type"] in ("rule", "flavor"):
            s.update({"targets": None, "activation": "none" if s["seg_type"] == "rule" else None,
                      "location": None, "timing": None, "negate_type": None,
                      "seg_category": 0})
        else:
            classify_segment(s, card_type, card_category, multi)
            # rule 文档 §4.2：rule 段 none；flavor 不参与
        out.append(s)
    return out


if __name__ == "__main__":
    import sys, io, sqlite3
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    import effect_splitter as sp
    zh = sqlite3.connect(r"C:/Users/Administrator/WorkBuddy/ygosearch/cdb/zh-CN/cards.cdb")
    ja = sqlite3.connect(r"C:/Users/Administrator/WorkBuddy/ygosearch/cdb/ja-JP/cards.cdb")
    cases = [
        (3739500, "破灭与终焉之支配者 ③ 期望 targets=0 ignition field 主动破坏"),
        (7987191, "装弹枪管暴动龙 ① targets=0 quick / ② targets=1 grave"),
        (14558127, "灰流丽 hand trigger/quick targets=0"),
        (44665365, "神光之宣告者 field negate=activation"),
        (82732705, "技能抽取 continuous negate=effect"),
        (50755, "魔术师的法阵 when_optional"),
        (24175232, "奈芙提斯之苍凰神 ① targets=0 主动破坏"),
        (55410871, "青眼混沌极龙 continuous 耐性位"),
        (72426662, "终焉之王迪米斯 ① targets=0 ignition 双破坏位"),
    ]
    for cid, note in cases:
        zt = zh.execute("SELECT t.desc, d.type, d.category FROM datas d JOIN texts t ON d.id=t.id WHERE d.id=?",
                        (cid,)).fetchone()
        jt = ja.execute("SELECT t.desc FROM texts t WHERE t.id=?", (cid,)).fetchone()
        segs, _ = sp.split_card(zt[0], jt[0], zt[1])
        segs = sp.__dict__ and segs  # noop
        import effect_classifier as cl
        cl.annotate(segs, zt[1], zt[2])
        print(f"\n=== id={cid} {note}")
        for s in segs:
            if s["seg_type"] in ("rule", "flavor"):
                print(f"  [{s['seg_type']} no={s['no']}] (不检索)")
                continue
            print(f"  [no={s['no']}] tg={s['targets']} act={s['activation']} "
                  f"loc={s['location']} tm={s['timing']} neg={s['negate_type']} "
                  f"cat=0x{s['seg_category']:08x}")
            print(f"      zh: {s['text_zh'][:60]!r}")
