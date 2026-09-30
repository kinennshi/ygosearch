# -*- coding: utf-8 -*-
"""效果切分器（规则文档 §3）。

设计要点（依据 §1.1 / §9.3，zh 翻译有损）：
- 以 ja-JP 文本为切分主轴（结构标记最全），zh 按同一算法独立切分后对齐；
- 对齐成功 → 逐段配对；失败 → 该卡记入异常清单，zh text 回退为整卡原文；
- 段结构由卡片 type 位决定（三语言共享），文本标记词双语各配一套。
"""
import re
from typing import Dict, List, Optional

MARKER_RE = re.compile("[①②③④⑤⑥⑦⑧⑨⑩]")
# 切分点：编号后接全角/半角冒号（规则 §3.2 正则的宽松版，兼容个别半角）
SPLIT_RE = re.compile(r"(?=[①②③④⑤⑥⑦⑧⑨⑩][：:])")
MARKER_VALUE = {ch: i + 1 for i, ch in enumerate("①②③④⑤⑥⑦⑧⑨⑩")}

# 分节标记
PEND_MONSTER_MARKERS = ("【怪兽效果】", "【モンスター効果】", "【怪兽描述】")
SCALE_HEADER_PAT = re.compile(r"^\s*(←.*→|【[ＰP]スケール[：:].*?】)\s*$", re.S)

# 降临/规则行（段前元信息，规则 §3.2）
RULE_LINE_PAT = re.compile(
    r"(降临|により降臨|^このカード名の|^这个卡名的|の効果はそれぞれ|的效果.{0,4}各能使用|"
    r"としても扱|这个卡名在规则上|このカード名はルール上)"
)


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_by_markers(text: str) -> List[str]:
    """按编号切分，返回 [前置部分, ①段, ②段, ...]。前置部分可能为空。"""
    parts = SPLIT_RE.split(text)
    return [p.strip() for p in parts if p is not None]


def _split_rule_and_effects(section: str, allow_numbered: bool):
    """把一段文本拆成 (rule_text, [(marker_no|None, text), ...])。

    §3.2：首个编号段之前的元信息行（召唤条件/限制行等）不是效果，整块归 rule。
    """
    rule_lines: List[str] = []
    effects: List = []
    if allow_numbered and MARKER_RE.search(section):
        parts = _split_by_markers(section)
        head = parts[0]
        for ln in head.split("\n"):
            if ln.strip():
                rule_lines.append(ln.strip())
        for p in parts[1:]:
            m = MARKER_RE.search(p)
            no = MARKER_VALUE.get(m.group(0)) if m else None
            effects.append((no, p))
    else:
        if section.strip():
            effects.append((None, section.strip()))
    return "\n".join(rule_lines), effects


def split_language(desc: str, is_pendulum: bool, is_effect_monster: bool,
                   is_monster: bool) -> List[Dict]:
    """对单一语言的 desc 执行切分（规则 §3.1–§3.5）。

    返回有序段列表 [{"no": int, "seg_type": str, "text": str}, ...]
    顺序：rule(0) → pendulum(-1,-2…) → monster(1,2…) → spell_trap(1,2…) → flavor(1)
    """
    desc = normalize(desc)
    segs: List[Dict] = []
    rule_parts: List[str] = []

    if not is_monster:
        # 魔法 / 陷阱（§3.4）
        rule_text, effects = _split_rule_and_effects(desc, allow_numbered=True)
        if rule_text:
            rule_parts.append(rule_text)
        for no, text in effects:
            segs.append({"no": no if no is not None else 1,
                         "seg_type": "spell_trap", "text": text})
        if rule_parts:
            segs.insert(0, {"no": 0, "seg_type": "rule",
                            "text": "\n".join(rule_parts)})
        return segs

    if is_pendulum:
        # 灵摆（§3.1）
        lines = desc.split("\n")
        body_lines = [ln for ln in lines if not SCALE_HEADER_PAT.match(ln.strip())]
        body = "\n".join(body_lines)
        # 以【怪兽效果】为界切两半
        idx = -1
        for mk in PEND_MONSTER_MARKERS:
            i = body.find(mk)
            if i >= 0:
                idx = i
                break
        if idx >= 0:
            matched_marker = next(mk for mk in PEND_MONSTER_MARKERS
                                  if body.find(mk) == idx)
            p_part = body[:idx]
            m_part = body[idx:].replace(matched_marker, "\n", 1)
            p_rule, p_effects = _split_rule_and_effects(p_part, allow_numbered=True)
            if p_rule:
                rule_parts.append(p_rule)
            # P 效果段编号转负：第 n 个编号效果 → -n
            for k, (_no, text) in enumerate(p_effects, start=1):
                segs.append({"no": -k, "seg_type": "pendulum", "text": text})
            rest = m_part
        else:
            rest = body
        # 怪兽部分：EFFECT 怪兽按编号/整段，否则 flavor
        if is_effect_monster:
            m_rule, m_effects = _split_rule_and_effects(rest, allow_numbered=True)
            if m_rule:
                rule_parts.append(m_rule)
            for no, text in m_effects:
                segs.append({"no": no if no is not None else 1,
                             "seg_type": "monster", "text": text})
        elif rest.strip():
            segs.append({"no": 1, "seg_type": "flavor", "text": rest.strip()})
        if rule_parts:
            segs.insert(0, {"no": 0, "seg_type": "rule",
                            "text": "\n".join(rule_parts)})
        return segs

    # 非灵摆怪兽
    if is_effect_monster:
        # §3.2 编号 / §3.3 无编号
        rule_text, effects = _split_rule_and_effects(desc, allow_numbered=True)
        if rule_text:
            rule_parts.append(rule_text)
        for no, text in effects:
            segs.append({"no": no if no is not None else 1,
                         "seg_type": "monster", "text": text})
    else:
        # §3.5 通常怪兽
        segs.append({"no": 1, "seg_type": "flavor", "text": desc})
    if rule_parts:
        segs.insert(0, {"no": 0, "seg_type": "rule",
                        "text": "\n".join(rule_parts)})
    return segs


def split_card(desc_zh: str, desc_ja: str, card_type: int):
    """切分一张卡，返回 (segments, anomaly)。

    segments: [ {no, seg_type, text_zh, text_ja} ]（已配对）
    anomaly: None 或字符串（切分/对齐异常说明）
    """
    from constants import TYPE_MONSTER, TYPE_EFFECT, TYPE_PENDULUM, TYPE_TOKEN

    desc_zh = normalize(desc_zh)
    desc_ja = normalize(desc_ja)
    is_monster = bool(card_type & TYPE_MONSTER)
    is_pend = bool(card_type & TYPE_PENDULUM)
    is_eff = bool(card_type & TYPE_EFFECT)
    if card_type & TYPE_TOKEN:
        # §3.5 衍生物按通常怪兽处理
        is_eff = False

    ja_segs = split_language(desc_ja, is_pend, is_eff, is_monster)
    zh_segs = split_language(desc_zh, is_pend, is_eff, is_monster)

    # 对齐键：只比较效果段（rule 段是附随元信息，zh 翻译常缺失，不参与配对）
    key_ja = [(s["seg_type"], s["no"]) for s in ja_segs if s["seg_type"] != "rule"]
    key_zh = [(s["seg_type"], s["no"]) for s in zh_segs if s["seg_type"] != "rule"]
    ja_rule = next((s["text"] for s in ja_segs if s["seg_type"] == "rule"), "")
    zh_rule = next((s["text"] for s in zh_segs if s["seg_type"] == "rule"), "")

    if key_ja == key_zh:
        zh_eff = [s for s in zh_segs if s["seg_type"] != "rule"]
        segments = []
        if ja_rule or zh_rule:
            segments.append({"no": 0, "seg_type": "rule",
                             "text_zh": zh_rule, "text_ja": ja_rule})
        for j, z in zip([s for s in ja_segs if s["seg_type"] != "rule"], zh_eff):
            segments.append({"no": j["no"], "seg_type": j["seg_type"],
                             "text_zh": z["text"], "text_ja": j["text"]})
        return segments, None

    # 对齐失败：ja 为主轴，zh 回退整卡原文（§3.6 异常清单）
    anomaly = f"zh/ja 段结构不一致: zh={len(key_zh)}段 ja={len(key_ja)}段"
    segments = [{"no": j["no"], "seg_type": j["seg_type"],
                 "text_zh": desc_zh, "text_ja": j["text"]}
                for j in ja_segs]
    return segments, anomaly


if __name__ == "__main__":
    import sys, io, sqlite3
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    zh = sqlite3.connect(r"C:/Users/Administrator/WorkBuddy/ygosearch/cdb/zh-CN/cards.cdb")
    ja = sqlite3.connect(r"C:/Users/Administrator/WorkBuddy/ygosearch/cdb/ja-JP/cards.cdb")
    # 覆盖：灵摆带编号 / 手坑 / 仪式多效果 / 通常陷阱带① / 通常怪兽
    for cid in (41546, 14558127, 44665365, 50755, 32864):
        zt = zh.execute("SELECT t.desc, d.type FROM datas d JOIN texts t ON d.id=t.id WHERE d.id=?",
                        (cid,)).fetchone()
        jt = ja.execute("SELECT t.desc FROM texts t WHERE t.id=?", (cid,)).fetchone()
        segs, anom = split_card(zt[0], jt[0], zt[1])
        print(f"=== id={cid} type=0x{zt[1]:x} anomaly={anom}")
        for s in segs:
            print(f"  [{s['seg_type']} no={s['no']}] zh={s['text_zh'][:48]!r}")
            print(f"      ja={s['text_ja'][:48]!r}")
