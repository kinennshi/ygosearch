# -*- coding: utf-8 -*-
"""词汇表：/api/vocab 与 LLM 系统提示词的同一数据源（保证与校验层一致）。"""
from typing import Dict

import constants as C
import dsl as D


def build_vocab(setnames: Dict[int, str], available_ot=None) -> Dict:
    type_groups = {
        "主类型": ["怪兽", "魔法", "陷阱"],
        "怪兽细分": ["通常", "效果", "仪式", "融合", "同调", "超量", "灵摆",
                     "连接", "调整", "反转", "灵魂", "联合", "二重", "卡通", "特殊召唤",
                     ],
        "魔法细分": ["通常", "仪式", "速攻", "永续", "装备", "场地"],
        "陷阱细分": ["通常", "永续", "反击"],
    }
    # 扁平类型列表（label + bit + group）：前端 chips 用，可显示位值
    bit_by_label = {lab: bit for lab, bit, _scope in C.TYPE_LABELS}
    bit_by_label.update({"怪兽": C.TYPE_MONSTER, "魔法": C.TYPE_SPELL,
                         "陷阱": C.TYPE_TRAP})
    types = [{"label": lab, "bit": bit_by_label[lab], "group": group}
             for group, labs in type_groups.items() for lab in labs]
    categories = [{"bit": bit, "name": name} for bit, name in C.CATEGORY_BITS]
    ritual_position = next(i for i, category in enumerate(categories)
                           if category["name"] == "超量相关") + 1
    categories.insert(ritual_position,
                      {"bit": D.RITUAL_CATEGORY, "name": "仪式相关"})
    return {
        "type_groups": type_groups,
        "types": types,
        "attributes": [name for _b, name in C.ATTRIBUTE_BITS.items()],
        "races": [name for _b, name in C.RACE_BITS.items()],
        "categories": [c for c in categories if c["name"] != "衍生物"],
        "setnames": sorted(setnames.values()),
        "ot": [{"value": v, "label": lab} for v, lab in C.OT_LABELS.items()
               if available_ot is None or v in available_ot],
        "effects": {
            "targets": [{"value": 1, "label": "取对象"},
                        {"value": 0, "label": "不取对象"}],
            "activation": [{"value": v, "label": C.ACTIVATION_ZH[v]}
                           for v in C.ACTIVATION_VALUES if v != "none"],
            "location": [{"value": v, "label": C.LOCATION_ZH[v]}
                         for v in C.LOCATION_VALUES],
            "timing": [{"value": v, "label": C.TIMING_ZH[v]}
                       for v in C.TIMING_VALUES],
            "negate_type": [{"value": v, "label": C.NEGATE_ZH[v]}
                            for v in C.NEGATE_VALUES],
        },
        "fields": sorted(D.FIELD_OPS.keys()),
    }
