# -*- coding: utf-8 -*-
"""检索执行器：跑 SQL、alias 展开、排序、命中理由标注。"""
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import constants as C
import dsl as D

ROOT = Path(__file__).resolve().parent.parent
BUILD_DB = ROOT / "cdb" / "card_effects.db"
ZH_DB = ROOT / "cdb" / "zh-CN" / "cards.cdb"


class Engine:
    def __init__(self):
        self.db = sqlite3.connect(str(BUILD_DB), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("ATTACH DATABASE ? AS cards", (str(ZH_DB),))
        from strings_conf import parse_strings_conf, parse_lflist
        self.setnames, self.system_strings = parse_strings_conf()
        self.lflist = parse_lflist()
        self._alias_cache: Dict[int, int] = {}
        for aid, target in self.db.execute(
                "SELECT id, alias FROM cards.datas WHERE alias != 0"):
            self._alias_cache[aid] = target

    # ---------- 基础查询 ----------
    def card(self, card_id: int) -> Optional[Dict]:
        r = self.db.execute(
            "SELECT d.id, d.ot, d.alias, d.setcode, d.type, d.atk, d.def, "
            "d.level, d.race, d.attribute, d.category, t.name, t.desc "
            "FROM cards.datas d JOIN cards.texts t ON d.id = t.id "
            "WHERE d.id = ?", (card_id,)).fetchone()
        return dict(r) if r else None

    def _decode_card(self, c: Dict) -> Dict:
        lv, lscale, rscale = C.unpack_level(c["level"])
        races = [name for bit, name in C.RACE_BITS.items() if c["race"] & bit]
        attrs = [name for bit, name in C.ATTRIBUTE_BITS.items() if c["attribute"] & bit]
        sets = []
        for code in C.unpack_setcodes(c["setcode"]):
            nm = self.setnames.get(code)
            if nm and nm not in sets:
                sets.append(nm)
        main_type, kinds, abilities = self._type_info(c["type"])
        return {
            "id": c["id"], "name": c["name"],
            "type": c["type"], "ot": c["ot"],
            "ot_label": C.OT_LABELS.get(c["ot"], str(c["ot"])),
            "level": lv, "lscale": lscale, "rscale": rscale,
            "atk": c["atk"], "def": c["def"],
            "atk_str": "?" if c["atk"] == -2 else str(c["atk"]),
            "def_str": ("—" if c["type"] & C.TYPE_LINK else
                        "?" if c["def"] == -2 else str(c["def"])),
            "race": "、".join(races) if races else "—",
            "attribute": "、".join(attrs) if attrs else "—",
            "setnames": sets,
            "desc": (c["desc"] or "").replace("\r\n", "\n"),
            "is_pendulum": bool(c["type"] & C.TYPE_PENDULUM),
            "is_link": bool(c["type"] & C.TYPE_LINK),
            "main_type": main_type,
            "kinds": kinds,
            "abilities": abilities,
            "forbidden": self.lflist.get(c["id"], None),
        }

    @staticmethod
    def _type_info(t: int):
        """从 type 位解析卡面/种类/能力。返回 (main, kinds, abilities)。"""
        if t & C.TYPE_MONSTER:
            main = "怪兽"
            kinds = []
            for bit, name in ((C.TYPE_LINK, "连接"), (C.TYPE_PENDULUM, "灵摆"),
                              (C.TYPE_XYZ, "超量"), (C.TYPE_SYNCHRO, "同调"),
                              (C.TYPE_FUSION, "融合"), (C.TYPE_RITUAL, "仪式")):
                if t & bit:
                    kinds.append(name)
            if not kinds:
                kinds.append("效果" if t & C.TYPE_EFFECT else "通常")
            abilities = [name for bit, name in
                         ((C.TYPE_TUNER, "调整"), (C.TYPE_FLIP, "反转"),
                          (C.TYPE_SPIRIT, "灵魂"), (C.TYPE_UNION, "联合"),
                          (C.TYPE_DUAL, "二重"), (C.TYPE_TOON, "卡通"),
                          (C.TYPE_SPSUMMON, "特殊召唤")) if t & bit]
        elif t & C.TYPE_SPELL:
            main = "魔法"
            kinds = [name for bit, name in
                     ((C.TYPE_RITUAL, "仪式"), (C.TYPE_QUICKPLAY, "速攻"),
                      (C.TYPE_CONTINUOUS, "永续"), (C.TYPE_EQUIP, "装备"),
                      (C.TYPE_FIELD, "场地")) if t & bit]
            if not kinds:
                kinds.append("通常")
            abilities = []
        else:
            main = "陷阱"
            kinds = [name for bit, name in
                     ((C.TYPE_COUNTER, "反击"), (C.TYPE_CONTINUOUS, "永续"))
                     if t & bit]
            if not kinds:
                kinds.append("通常")
            abilities = []
        return main, kinds, abilities

    def effects_of(self, card_id: int) -> List[Dict]:
        rows = self.db.execute(
            "SELECT effect_no, seg_type, text, text_ja, targets, activation, "
            "location, timing, negate_type, seg_category, confidence "
            "FROM card_effects WHERE card_id = ? ORDER BY effect_no",
            (card_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["seg_category_names"] = [
                name for bit, name in C.CATEGORY_BITS if d["seg_category"] & bit]
            for category, (name, _terms) in D.TEXT_EFFECT_CATEGORIES.items():
                if D.is_text_effect(category, d["seg_type"], d["text"]):
                    d["seg_category_names"].append(name)
            out.append(d)
        return out

    # ---------- 主检索 ----------
    def search(self, dsl_json: Dict, expand_alias: Optional[bool] = None,
               limit: int = 100, offset: int = 0, sort: Optional[str] = None) -> Dict:
        """执行 DSL。返回 {total, cards: [...], described}。

        cards 内每张卡带 hits: 命中理由列表。
        expand_alias：默认不展开同名再版；显式传 True 时可展开。
        sort：可选排序 atk_asc/atk_desc/def_asc/def_desc/level_asc/level_desc。
        """
        norm = D.normalize(dsl_json, self.setnames)
        described = D.describe(dsl_json, self.setnames)
        q = D.compile(norm, self.setnames)
        try:
            rows = self.db.execute(q.sql, q.params).fetchall()
        except sqlite3.OperationalError as e:
            raise D.DSLError(f"查询执行失败：{e}")

        ids = [r["id"] for r in rows]
        id_set = set(ids)
        # P1: alias 链展开（同名再版一并命中）
        if expand_alias is None:
            expand_alias = False
        alias_source = {}
        if expand_alias:
            neighbors = {}
            for aid, target in self._alias_cache.items():
                neighbors.setdefault(aid, set()).add(target)
                neighbors.setdefault(target, set()).add(aid)
            seen = set(id_set)
            queue = list(ids)
            for current in queue:
                for related in neighbors.get(current, ()):
                    if related not in seen:
                        seen.add(related)
                        alias_source[related] = alias_source.get(current, current)
                        queue.append(related)
            # An alias may have a different card pool, type or effect text.
            # Only the name condition may be inherited from the matched card.
            other_conds = [c for c in norm["must"] if c["field"] != "name"]
            alias_query = D.compile({"must": other_conds}, self.setnames)
            valid_aliases = set()
            candidates = list(alias_source)
            for start in range(0, len(candidates), 500):
                batch = candidates[start:start + 500]
                sql = alias_query.sql + " AND d.id IN (" + ",".join("?" for _ in batch) + ")"
                valid_aliases.update(r["id"] for r in self.db.execute(
                    sql, alias_query.params + batch))
            alias_source = {cid: source for cid, source in alias_source.items()
                            if cid in valid_aliases}
            ids.extend(sorted(alias_source))

        # Sort and collapse alternate artworks before paging. Otherwise
        # duplicates consume result slots and inflate the reported total.
        sort_fields = {}
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            if not batch:
                continue
            sql = ("SELECT d.id, d.alias, d.type, d.level, d.atk, d.def, "
                   "t.name FROM cards.datas d JOIN cards.texts t ON t.id = d.id "
                   "WHERE d.id IN (" + ",".join("?" for _ in batch) + ")")
            sort_fields.update((r["id"], r) for r in self.db.execute(sql, batch))
        if sort:
            ids = sorted((cid for cid in ids if cid in sort_fields),
                         key=lambda cid: self._sort_key_by(sort_fields[cid], sort))
        else:
            ids = sorted((cid for cid in ids if cid in sort_fields),
                         key=lambda cid: self._sort_key_fields(sort_fields[cid]))
        chosen_by_name = {}
        for cid in ids:
            row = sort_fields[cid]
            previous = chosen_by_name.get(row["name"])
            if previous is None or (row["alias"] == 0
                                    and sort_fields[previous]["alias"] != 0):
                chosen_by_name[row["name"]] = cid
        ids = [cid for cid in ids
               if chosen_by_name[sort_fields[cid]["name"]] == cid]
        if q.forbidden_values is not None:
            ids = [cid for cid in ids
                   if self._forbidden_match(self.lflist.get(cid),
                                            q.forbidden_values)]
        total = len(ids)
        cards = []
        for cid in ids[offset:offset + limit]:
            c = self.card(cid)
            if not c:
                continue
            dec = self._decode_card(c)
            if cid in alias_source:
                dec["hit_reasons"] = [f"关联卡（原命中卡 ID {alias_source[cid]}）"]
                if other_conds:
                    dec["hit_reasons"].extend(self._hit_reasons(cid, other_conds, q))
            else:
                dec["hit_reasons"] = self._hit_reasons(cid, norm["must"], q)
            cards.append(dec)

        return {"total": total, "described": described, "cards": cards,
                "sql": q.sql, "params": q.params}

    # ---------- 命中理由 ----------
    def _hit_reasons(self, card_id: int, conds: List[Dict],
                     q: "D.CompiledQuery") -> List[str]:
        reasons = []
        effects_matched = []   # 命中的 (cond, segments)
        for cond in conds:
            f, op = cond["field"], cond["op"]
            if f == "type":
                labels = []
                for b in cond["bits"]:
                    labels += [lab for lab, bit in D.TYPE_LABEL_TO_BIT.items()
                               if b & bit]
                reasons.append("类型含 " + "、".join(dict.fromkeys(labels)))
            elif f == "attribute":
                labels = []
                for b in cond["bits"]:
                    labels += [lab for lab, bit in D.ATTRIBUTE_LABEL_TO_BIT.items()
                               if b & bit]
                reasons.append("属性 " + "、".join(dict.fromkeys(labels)))
            elif f == "race":
                labels = []
                for b in cond["bits"]:
                    labels += [lab for lab, bit in D.RACE_LABEL_TO_BIT.items()
                               if b & bit]
                reasons.append("种族 " + "、".join(dict.fromkeys(labels)))
            elif f == "setname":
                reasons.append(f"系列「{cond['label']}」")
            elif f in ("level", "link", "atk", "def", "lscale"):
                zh = {"level": "等级", "atk": "攻击力", "def": "守备力",
                      "lscale": "灵摆刻度", "link": "LINK值"}[f]
                reasons.append(f"{zh}满足区间条件")
            elif f == "ot":
                reasons.append("卡池 " + "、".join(
                    C.OT_LABELS.get(v, str(v)) for v in cond["values"]))
            elif f == "name":
                reasons.append(f"卡名含「{cond['keyword']}」")
            elif f == "desc":
                reasons.append(D.desc_condition_label(cond))
            elif f == "category":
                names = [name for bit, name in C.CATEGORY_BITS
                         if bit in cond["bits"]]
                reasons.append("官方动作位：" + "、".join(names))
            elif f == "effects":
                segs = self._matching_segments(card_id, cond["where"])
                if segs:
                    effects_matched.append((cond, segs))
        # 效果段命中理由：引用具体段
        for cond, segs in effects_matched:
            for s in segs[:3]:   # 每条件最多列 3 段，防刷屏
                seg_label = _seg_label(s)
                dims = D._dims_zh(cond["where"])
                excerpt = (s["text"] or s["text_ja"]).replace("\n", " ")[:52]
                reasons.append(f"{seg_label}命中（{'；'.join(dims)}）：{excerpt}…")
        if not reasons:
            reasons.append("无条件匹配")
        return reasons

    def _matching_segments(self, card_id: int, where: Dict) -> List[Dict]:
        """重放 effects.where 找到该卡命中的具体段（用于命中理由）。"""
        params: List[Any] = []
        sub = D._effects_subsql(where, params)
        rows = self.db.execute(
            "SELECT e.effect_no, e.seg_type, e.text, e.text_ja, e.targets, "
            "e.activation, e.location, e.timing, e.negate_type, e.seg_category "
            "FROM card_effects e "
            f"WHERE e.card_id = ? AND ({sub})",
            [card_id] + params).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _forbidden_match(fb, values) -> bool:
        """禁限筛选：fb 为该卡禁限值（None/0/1/2），values 为 DSL 取值集合。
        'none' 匹配未在禁限表中的卡。"""
        if fb is None:
            return "none" in values
        return fb in values

    # ---------- 排序（YGOPro2 风格） ----------
    @staticmethod
    def _sort_key(dec: Dict):
        return Engine._sort_key_fields(dec)

    @staticmethod
    def _sort_key_fields(fields):
        t = fields["type"]
        # 主类型：怪兽(0) → 魔法(1) → 陷阱(2)
        if t & C.TYPE_MONSTER:
            main = 0
        elif t & C.TYPE_SPELL:
            main = 1
        else:
            main = 2
        # 副类型：连接>灵摆>超量>同调>融合>仪式>效果>通常（特殊度降序）
        sub_order = 0
        for bit in (C.TYPE_LINK, C.TYPE_PENDULUM, C.TYPE_XYZ, C.TYPE_SYNCHRO,
                    C.TYPE_FUSION, C.TYPE_RITUAL, C.TYPE_EFFECT):
            if t & bit:
                break
            sub_order += 1
        return (main, sub_order, -(fields["level"] & 0xFF),
                -fields["atk"], fields["id"])

    @staticmethod
    def _sort_key_by(fields, sort):
        f = fields
        if sort == "atk_asc":
            return (f["atk"], f["id"])
        if sort == "atk_desc":
            return (-f["atk"], f["id"])
        if sort == "def_asc":
            return (f["def"], f["id"])
        if sort == "def_desc":
            return (-f["def"], f["id"])
        if sort == "level_asc":
            return (f["level"] & 0xFF, f["id"])
        if sort == "level_desc":
            return (-(f["level"] & 0xFF), f["id"])
        if sort == "id_asc":
            return (f["id"],)
        if sort == "id_desc":
            return (-f["id"],)
        return Engine._sort_key_fields(f)


def _seg_label(s: Dict) -> str:
    if s["seg_type"] == "pendulum":
        return f"灵摆效果{abs(s['effect_no'])}"
    if s["seg_type"] == "rule":
        return "规则文本"
    if s["effect_no"] >= 1:
        return f"第{'①②③④⑤⑥⑦⑧⑨⑩'[s['effect_no']-1]}段"
    return s["seg_type"]


if __name__ == "__main__":
    import sys, io, json
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    eng = Engine()
    dsl_json = {"must": [
        {"field": "type", "op": "bit_has", "value": ["怪兽", "仪式"]},
        {"field": "effects", "op": "exists", "where": {
            "targets": 0, "seg_category_any": [1, 2], "exclude_negate": True}},
    ]}
    r = eng.search(dsl_json)
    print("描述:", r["described"])
    print(f"命中 {r['total']} 张")
    for c in r["cards"][:8]:
        print(f"  {c['name']} [{c['id']}]")
        for h in c["hit_reasons"]:
            print(f"     - {h}")
