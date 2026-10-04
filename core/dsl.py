# -*- coding: utf-8 -*-
"""检索 DSL：定义、校验、SQL 编译、人类可读描述。

DSL 是手动模式与 AI 模式共用执行引擎的唯一契约。
所有 SQL 一律参数化（? 占位符），禁止把用户值拼进 SQL 字符串。
"""
import re
import math
from typing import Any, Dict, List, Optional, Tuple

import constants as C

# ---------------- 词汇白名单 ----------------
TYPE_LABEL_TO_BIT = {}
for _label, _bit, _scope in C.TYPE_LABELS:
    if _label != "陷阱怪兽":
        TYPE_LABEL_TO_BIT[_label] = _bit
TYPE_LABEL_TO_BIT.update({"怪兽": C.TYPE_MONSTER, "魔法": C.TYPE_SPELL,
                          "陷阱": C.TYPE_TRAP})
ATTRIBUTE_LABEL_TO_BIT = {v: k for k, v in C.ATTRIBUTE_BITS.items()}
RACE_LABEL_TO_BIT = {v: k for k, v in C.RACE_BITS.items()}

CATEGORY_BIT_VALUES = {bit for bit, _name in C.CATEGORY_BITS}
RITUAL_CATEGORY = "ritual"
RITUAL_TERMS = ("仪式召唤", "仪式魔法", "仪式怪兽", "仪式卡")


TEXT_EFFECT_CATEGORIES = {
    RITUAL_CATEGORY: ("仪式相关", RITUAL_TERMS),
    "face_down": ("里侧相关", ("里侧表示除外", "里侧守备表示特殊召唤")),
    "damage_immunity": ("伤害免疫", ("伤害变成0", "伤害变成０")),
}


def is_text_effect(category: str, seg_type: str, text: str) -> bool:
    return (seg_type in ("monster", "pendulum", "spell_trap")
            and any(term in (text or "") for term in TEXT_EFFECT_CATEGORIES[category][1]))


def is_ritual_effect(seg_type: str, text: str) -> bool:
    return is_text_effect(RITUAL_CATEGORY, seg_type, text)


ACTIVATION_ENUMS = set(C.ACTIVATION_VALUES)
LOCATION_ENUMS = set(C.LOCATION_VALUES)
TIMING_ENUMS = set(C.TIMING_VALUES)
NEGATE_ENUMS = set(C.NEGATE_VALUES)

OT_VALUES = set(C.OT_LABELS.keys())

FORBIDDEN_VALUES = {0, 1, 2, "none"}  # 禁止/限制/准限制/无限制

# 字段 -> 允许的 op
FIELD_OPS = {
    "type": {"bit_has"},
    "attribute": {"bit_has"},
    "race": {"bit_has"},
    "level": {"between", "eq"},
    "link": {"between", "eq"},
    "lscale": {"between"},
    "atk": {"between", "eq"},
    "def": {"between", "eq"},
    "setname": {"eq"},
    "ot": {"in", "includes"},
    "name": {"contains"},
    "desc": {"contains", "contains_any"},
    "category": {"bit_has_any", "bit_has_all", "bit_has_none"},
    "effects": {"exists"},
    "forbidden": {"in"},
}

LIKE_ESCAPE_RE = re.compile(r"[%_\\]")


def _escape_like(s: str) -> str:
    return LIKE_ESCAPE_RE.sub(lambda m: "\\" + m.group(0), s)


class DSLError(ValueError):
    """DSL 非法，message 面向用户可读。"""


# ---------------- 归一化 ----------------
def _to_bitmask(value: Any, label_map: Dict[str, int], what: str) -> List[int]:
    """把 标签字符串/列表/整数 归一为位列表（每个元素要求单独满足，AND 语义）。

    - 传标签列表 ["怪兽","仪式"] → 要求同时具备两个位；
    - 传整数掩码 0x81 → 按整体掩码判任一（LLM 用位值时保持 §7 语义）。
    """
    if isinstance(value, bool):
        raise DSLError(f"{what} 的值不能是布尔值")
    if isinstance(value, int):
        allowed = 0
        for bit in label_map.values():
            allowed |= bit
        if value <= 0 or value & ~allowed:
            raise DSLError(f"{what} 含非法位掩码：{value!r}")
        return [value]
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list):
        if not value:
            raise DSLError(f"{what} 至少需要一个取值")
        bits = []
        for v in value:
            if not isinstance(v, str) or v.strip() not in label_map:
                raise DSLError(
                    f"{what} 含未知取值：{v!r}。可用值：{', '.join(label_map)}")
            bits.append(label_map[v.strip()])
        return bits
    raise DSLError(f"{what} 的值类型不合法：{value!r}")


def _integer(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DSLError(f"{what} 应为整数，收到 {value!r}")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise DSLError(f"{what} 应为有限整数，收到 {value!r}")
    result = int(value)
    if not -(1 << 63) <= result < (1 << 63):
        raise DSLError(f"{what} 超出整数范围")
    return result


def _norm_num_range(value: Any, what: str) -> Tuple[Optional[int], Optional[int]]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = _integer(value, what)
        return v, v
    if isinstance(value, list) and len(value) == 2:
        lo = None if value[0] is None else _integer(value[0], what)
        hi = None if value[1] is None else _integer(value[1], what)
        if lo is not None and hi is not None and lo > hi:
            raise DSLError(f"{what} 区间下限大于上限：{value}")
        return lo, hi
    raise DSLError(f"{what} 区间格式应为 [最小, 最大] 或单个数字，收到 {value!r}")


def _norm_enum_list(value: Any, enums: set, what: str) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise DSLError(f"{what} 应为枚举值或枚举值列表，收到 {value!r}")
    out = []
    for v in value:
        if not isinstance(v, str) or v not in enums:
            raise DSLError(f"{what} 含非法取值 {v!r}。可用值：{', '.join(sorted(enums))}")
        out.append(v)
    return out


def _norm_bit_list(value: Any, what: str) -> List[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list) or not value:
        raise DSLError(f"{what} 应为 category 位或位列表，收到 {value!r}")
    out = []
    for v in value:
        if not isinstance(v, int) or isinstance(v, bool) or v not in CATEGORY_BIT_VALUES:
            raise DSLError(f"{what} 含非法 category 位 {v!r}，合法范围为 2^0~2^31")
        out.append(v)
    return out


def _norm_text_list(value: Any, what: str) -> List[str]:
    if (not isinstance(value, list) or not 1 <= len(value) <= 16
            or any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in value)):
        raise DSLError(f"{what} 应为 1~16 个非空文本片段，每项最多 160 字")
    return list(dict.fromkeys(v.strip() for v in value))


def _text_sql(col: str, words: List[str], join: str, params: List[Any]) -> str:
    params.extend("%" + _escape_like(word) + "%" for word in words)
    return "(" + join.join(f"{col} LIKE ? ESCAPE '\\'" for _ in words) + ")"


def desc_condition_label(cond: Dict) -> str:
    if cond["op"] == "contains_any":
        return "文本含任一：" + "、".join(f"「{word}」" for word in cond["keywords"])
    return f"文本含「{cond['keyword']}」"


def _norm_effect_category_list(value: Any) -> List[Any]:
    """效果段类型允许官方 category 位，以及派生的文本标签。"""
    if isinstance(value, (int, str)) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list) or not value:
        raise DSLError("seg_category_any 应为效果类型列表")
    for item in value:
        if not (isinstance(item, str) and item in TEXT_EFFECT_CATEGORIES) and (not isinstance(item, int)
                                        or isinstance(item, bool)
                                        or item not in CATEGORY_BIT_VALUES):
            raise DSLError(f"seg_category_any 含非法效果类型 {item!r}")
    return value


def normalize(dsl: Any, setnames: Dict[int, str]) -> Dict:
    """校验并归一化 DSL。非法抛 DSLError（信息可读）。返回规范化 DSL。"""
    if not isinstance(dsl, dict):
        raise DSLError("DSL 应为 JSON 对象 {\"must\": [...]}")
    must = dsl.get("must")
    if must is None:
        raise DSLError("DSL 缺少 \"must\" 条件列表")
    if not isinstance(must, list):
        raise DSLError("\"must\" 应为条件数组")
    norm_conds = []
    for i, cond in enumerate(must):
        norm_conds.append(_norm_cond(i, cond, setnames))
    return {"must": norm_conds}


def _norm_cond(i: int, cond: Any, setnames: Dict[int, str]) -> Dict:
    if not isinstance(cond, dict):
        raise DSLError(f"第 {i+1} 个条件应为对象，收到 {type(cond).__name__}")
    field = cond.get("field")
    op = cond.get("op")
    if not isinstance(field, str) or field not in FIELD_OPS:
        raise DSLError(f"第 {i+1} 个条件 field 非法：{field!r}。"
                       f"可用字段：{', '.join(FIELD_OPS)}")
    if not isinstance(op, str) or op not in FIELD_OPS[field]:
        raise DSLError(f"字段 {field} 不支持 op={op!r}。"
                       f"可用 op：{', '.join(sorted(FIELD_OPS[field]))}")
    if field == "effects":
        if "where" in cond:
            v = cond["where"]
        elif "value" in cond:
            v = cond["value"]
        else:
            raise DSLError("条件 effects.exists 缺少 where 对象")
    elif "value" in cond:
        v = cond["value"]
    else:
        raise DSLError(f"条件 {field}.{op} 缺少 value")

    out = {"field": field, "op": op}
    if field == "type":
        out["bits"] = _to_bitmask(v, TYPE_LABEL_TO_BIT, "type")
    elif field == "attribute":
        out["bits"] = _to_bitmask(v, ATTRIBUTE_LABEL_TO_BIT, "attribute")
    elif field == "race":
        out["bits"] = _to_bitmask(v, RACE_LABEL_TO_BIT, "race")
    elif field in ("level", "link", "atk", "def", "lscale"):
        if op == "eq":
            out["value"] = _integer(v, f"{field}.eq")
        else:
            out["range"] = _norm_num_range(v, field)
    elif field == "setname":
        if not isinstance(v, str) or not v.strip():
            raise DSLError("setname 应为系列名字符串")
        name = v.strip().strip("「」『』\"'")
        # 精确匹配系列名（或唯一前缀匹配）
        code = None
        for c, n in setnames.items():
            if n == name:
                code = c
                break
        if code is None:
            hits = [n for n in setnames.values() if name in n]
            if len(hits) == 1:
                name = hits[0]
                code = next(c for c, n in setnames.items() if n == name)
        if code is None:
            raise DSLError(f"未知系列名：{name!r}。请从系列列表中选择")
        out["code"] = code
        out["label"] = name
    elif field == "ot":
        if not isinstance(v, list):
            v = [v]
        if not v:
            raise DSLError("ot 至少需要一个卡池值")
        for x in v:
            if not isinstance(x, int) or isinstance(x, bool) or x not in OT_VALUES:
                raise DSLError(f"ot 含非法卡池值 {x!r}。可用：{sorted(OT_VALUES)}")
        out["values"] = [int(x) for x in v]
        if op == "includes" and any(x not in (1, 2, 3, 8, 9, 10, 11) for x in v):
            raise DSLError("卡池归属仅接受 OCG=1、TCG=2、简中=8 及其组合")
    elif field in ("name", "desc"):
        if field == "desc" and op == "contains_any":
            out["keywords"] = _norm_text_list(v, "desc.contains_any")
        else:
            if not isinstance(v, str) or not v.strip():
                raise DSLError(f"{field} 关键词应为非空字符串")
            out["keyword"] = v.strip()
    elif field == "category":
        out["bits"] = _norm_bit_list(v, "category")
    elif field == "effects":
        out["where"] = _norm_effects_where(v)
    elif field == "forbidden":
        if not isinstance(v, list):
            v = [v]
        if not v:
            raise DSLError("forbidden 至少需要一个取值")
        out_values = []
        for x in v:
            if x not in FORBIDDEN_VALUES:
                raise DSLError(
                    f"forbidden 含非法取值 {x!r}。"
                    "可用：0(禁止)/1(限制)/2(准限制)/\"none\"(无限制)")
            out_values.append(x)
        out["values"] = out_values
    return out


def _norm_effects_where(where: Any) -> Dict:
    if not isinstance(where, dict) or not where:
        raise DSLError("effects.exists 的 where 应为非空对象")
    ALLOWED = {"targets", "activation", "location", "timing", "negate_type",
               "seg_category_any", "exclude_negate"}
    ALLOWED |= {"text_any", "text_all"}
    unknown = set(where) - ALLOWED
    if unknown:
        raise DSLError(f"effects.where 含未知键：{sorted(unknown)}。"
                       f"可用键：{sorted(ALLOWED)}")
    out = {}
    for key in ("text_any", "text_all"):
        if key in where:
            out[key] = _norm_text_list(where[key], key)
    if "targets" in where:
        if (not isinstance(where["targets"], int)
                or isinstance(where["targets"], bool)
                or where["targets"] not in (0, 1)):
            raise DSLError("effects.where.targets 只能是 0（不取对象）或 1（取对象）")
        out["targets"] = where["targets"]
    if "activation" in where:
        out["activation"] = _norm_enum_list(where["activation"],
                                            ACTIVATION_ENUMS, "activation")
    if "location" in where:
        out["location"] = _norm_enum_list(where["location"],
                                          LOCATION_ENUMS, "location")
    if "timing" in where:
        out["timing"] = _norm_enum_list(where["timing"],
                                        TIMING_ENUMS, "timing")
    if "negate_type" in where:
        if where["negate_type"] is None:
            out["negate_null"] = True
        else:
            out["negate_type"] = _norm_enum_list(where["negate_type"],
                                                 NEGATE_ENUMS, "negate_type")
    if "seg_category_any" in where:
        out["seg_category_any"] = _norm_effect_category_list(
            where["seg_category_any"])
    if "exclude_negate" in where:
        if not isinstance(where["exclude_negate"], bool):
            raise DSLError("exclude_negate 应为布尔值")
        out["exclude_negate"] = where["exclude_negate"]
    if not out:
        raise DSLError("effects.where 至少需要一个条件")
    return out


# ---------------- SQL 编译 ----------------
class CompiledQuery:
    def __init__(self):
        self.sql = ""
        self.params: List[Any] = []
        self.effects_conds: List[Dict] = []   # 供命中理由标注复用
        self.forbidden_values = None          # 禁限筛选（后过滤）


def _num_cond(col: str, cond: Dict, sql: List[str], params: List[Any]):
    if cond["op"] == "eq":
        sql.append(f"{col} = ?")
        params.append(cond["value"])
    else:
        lo, hi = cond["range"]
        if lo is not None:
            sql.append(f"{col} >= ?")
            params.append(lo)
        if hi is not None:
            sql.append(f"{col} <= ?")
            params.append(hi)


def _effects_subsql(where: Dict, params: List[Any]) -> str:
    subs = []
    for key, join in (("text_any", " OR "), ("text_all", " AND ")):
        if key in where:
            subs.append(_text_sql("e.text", where[key], join, params))
    if "targets" in where:
        subs.append("e.targets = ?")
        params.append(where["targets"])
    for key, col in (("activation", "e.activation"), ("location", "e.location"),
                     ("timing", "e.timing"), ("negate_type", "e.negate_type")):
        if key in where:
            vals = where[key]
            subs.append(f"{col} IN ({','.join('?' * len(vals))})")
            params.extend(vals)
    if where.get("negate_null"):
        subs.append("e.negate_type IS NULL")
    if where.get("exclude_negate"):
        subs.append("e.negate_type IS NULL")
    if "seg_category_any" in where:
        mask = 0
        for b in where["seg_category_any"]:
            if isinstance(b, int):
                mask |= b
        category_clauses = []
        if mask:
            category_clauses.append("(e.seg_category & ?) != 0")
            params.append(mask)
        for category, (_name, terms) in TEXT_EFFECT_CATEGORIES.items():
            if category in where["seg_category_any"]:
                category_clauses.append("(" + " OR ".join(
                    "e.text LIKE ?" for _ in terms) + ")")
                params.extend("%" + term + "%" for term in terms)
        subs.append("(" + " OR ".join(category_clauses) + ")")
    # Rule and flavor rows are stored for display, but are not card effects.
    subs.insert(0, "e.seg_type IN ('monster','pendulum','spell_trap')")
    return " AND ".join(subs)


def compile(dsl: Dict, setnames: Dict[int, str]) -> CompiledQuery:
    """规范化 DSL → 参数化 SQL（单条）。"""
    q = CompiledQuery()
    sql: List[str] = []
    params: List[Any] = []
    for cond in dsl["must"]:
        f, op = cond["field"], cond["op"]
        if f == "type":
            for b in cond["bits"]:
                sql.append("(d.type & ?) != 0")
                params.append(b)
        elif f == "attribute":
            for b in cond["bits"]:
                sql.append("(d.attribute & ?) != 0")
                params.append(b)
        elif f == "race":
            for b in cond["bits"]:
                sql.append("(d.race & ?) != 0")
                params.append(b)
        elif f in ("level", "link", "atk", "def"):
            col = {"level": "(d.level & 0xFF)", "link": "(d.level & 0xFF)",
                   "atk": "d.atk", "def": "d.def"}[f]
            if f == "level":
                sql.append("(d.type & ?) != 0")
                params.append(C.TYPE_MONSTER)
                sql.append("(d.type & ?) = 0")
                params.append(C.TYPE_LINK)
            elif f == "link":
                sql.append("(d.type & ?) != 0")
                params.append(C.TYPE_LINK)
            _num_cond(col, cond, sql, params)
        elif f == "lscale":
            sql.append("(d.type & ?) != 0")
            params.append(C.TYPE_PENDULUM)
            lo, hi = cond["range"]
            if lo is not None:
                sql.append("((d.level >> 24) & 0xFF) >= ?")
                params.append(lo)
            if hi is not None:
                sql.append("((d.level >> 24) & 0xFF) <= ?")
                params.append(hi)
        elif f == "setname":
            code = cond["code"]
            parts = []
            for shift in (0, 16, 32, 48):
                parts.append(f"((d.setcode >> {shift}) & 0xFFF) = ?")
                params.append(code)
            sql.append("(" + " OR ".join(parts) + ")")
        elif f == "ot":
            if op == "in":
                sql.append(f"d.ot IN ({','.join('?' * len(cond['values']))})")
                params.extend(cond["values"])
            else:
                # Each mask requires all its regions; multiple selections are ORed.
                sql.append("(" + " OR ".join("(d.ot & ?) = ?" for _ in cond["values"]) + ")")
                for value in cond["values"]:
                    params.extend((value, value))
        elif f in ("name", "desc"):
            col = "t.name" if f == "name" else "t.desc"
            words = cond["keywords"] if op == "contains_any" else [cond["keyword"]]
            sql.append(_text_sql(col, words, " OR ", params))
        elif f == "category":
            bits = cond["bits"]
            if op == "bit_has_any":
                mask = 0
                for b in bits:
                    mask |= b
                sql.append("(d.category & ?) != 0")
                params.append(mask)
            elif op == "bit_has_all":
                for b in bits:
                    sql.append("(d.category & ?) = ?")
                    params.extend([b, b])
            else:  # bit_has_none
                mask = 0
                for b in bits:
                    mask |= b
                sql.append("(d.category & ?) = 0")
                params.append(mask)
        elif f == "effects":
            sub = _effects_subsql(cond["where"], params)
            sql.append(
                "d.id IN (SELECT e.card_id FROM card_effects e "
                "WHERE " + sub + ")")
            q.effects_conds.append(cond)
        elif f == "forbidden":
            q.forbidden_values = set(cond["values"])
    sql.append("(d.type & ?) = 0")
    params.append(C.TYPE_TOKEN | C.TYPE_TRAPMONSTER)
    q.sql = ("SELECT d.id FROM datas d JOIN texts t ON d.id = t.id WHERE "
             + (" AND ".join(sql) if sql else "1=1"))
    q.params = params
    return q


# ---------------- 人类可读描述 ----------------
def _dims_zh(where: Dict) -> List[str]:
    parts = []
    for key, label in (("text_any", "效果文本含任一"), ("text_all", "效果文本同时含")):
        if key in where:
            parts.append(label + "：" + "、".join(f"「{word}」" for word in where[key]))
    if "targets" in where:
        parts.append("取对象" if where["targets"] == 1 else "不取对象")
    if "activation" in where:
        parts.append("、" .join(C.ACTIVATION_ZH[a] for a in where["activation"]))
    if "location" in where:
        parts.append("在" + "、".join(C.LOCATION_ZH[l] for l in where["location"]) + "发动")
    if "timing" in where:
        parts.append("、".join(C.TIMING_ZH[t] for t in where["timing"]))
    if "negate_type" in where:
        parts.append("、".join(C.NEGATE_ZH[n] for n in where["negate_type"]))
    if where.get("negate_null") or where.get("exclude_negate"):
        parts.append("破坏为效果自身动作（排除『无效并破坏』的段）")
    if "seg_category_any" in where:
        names = []
        for b in where["seg_category_any"]:
            if isinstance(b, str) and b in TEXT_EFFECT_CATEGORIES:
                names.append(TEXT_EFFECT_CATEGORIES[b][0])
                continue
            for bit, name in C.CATEGORY_BITS:
                if bit == b:
                    names.append(name)
        parts.append("效果类型：" + "、".join(names))
    return parts


def describe(dsl: Dict, setnames: Dict[int, str]) -> str:
    """DSL → 人类可读中文描述（用于 AI 模式回显）。"""
    norm = normalize(dsl, setnames)
    parts: List[str] = []
    for cond in norm["must"]:
        f, op = cond["field"], cond["op"]
        if f == "type":
            labels = []
            for b in cond["bits"]:
                labels += [lab for lab, bit in TYPE_LABEL_TO_BIT.items()
                           if b & bit]
            parts.append("类型含 " + "、".join(dict.fromkeys(labels)))
        elif f == "attribute":
            labels = []
            for b in cond["bits"]:
                labels += [lab for lab, bit in ATTRIBUTE_LABEL_TO_BIT.items()
                           if b & bit]
            parts.append("属性为 " + "、".join(dict.fromkeys(labels)))
        elif f == "race":
            labels = []
            for b in cond["bits"]:
                labels += [lab for lab, bit in RACE_LABEL_TO_BIT.items()
                           if b & bit]
            parts.append("种族为 " + "、".join(dict.fromkeys(labels)))
        elif f in ("level", "link", "atk", "def", "lscale"):
            zh = {"level": "等级/阶级", "atk": "攻击力", "def": "守备力",
                  "lscale": "灵摆刻度", "link": "LINK值"}[f]
            if op == "eq":
                v = cond["value"]
                parts.append(f"{zh} = {'?' if v == -2 else v}")
            else:
                lo, hi = cond["range"]
                lo_s = "?" if lo == -2 else lo
                hi_s = "?" if hi == -2 else hi
                if lo is not None and lo == hi:
                    parts.append(f"{zh} = {lo_s}")
                else:
                    parts.append(f"{zh} 在 {lo_s if lo is not None else '−∞'}"
                                 f"~{hi_s if hi is not None else '+∞'}")
        elif f == "setname":
            parts.append(f"系列「{cond['label']}」")
        elif f == "ot":
            names = [C.OT_LABELS.get(v, str(v)) for v in cond["values"]]
            parts.append("卡池 " + "、".join(names))
            if op != "in":
                parts[-1] += "（组合卡池取交集，多选取并集）"
        elif f == "name":
            parts.append(f"卡名含「{cond['keyword']}」")
        elif f == "desc":
            parts.append(desc_condition_label(cond))
        elif f == "category":
            names = []
            for b in cond["bits"]:
                for bit, name in C.CATEGORY_BITS:
                    if bit == b:
                        names.append(name)
            op_zh = {"bit_has_any": "任一", "bit_has_all": "全部",
                     "bit_has_none": "都没有"}[op]
            parts.append(f"效果类型（{op_zh}）：" + "、".join(names))
        elif f == "effects":
            dims = _dims_zh(cond["where"])
            parts.append("存在这样的效果段：" + "；".join(dims))
        elif f == "forbidden":
            names = {0: "禁止", 1: "限制", 2: "准限制", "none": "无限制"}
            parts.append("禁限为 " + "、".join(names[x] for x in cond["values"]))
    text = "且".join(parts) if parts else "无条件（全部卡）"
    return text
