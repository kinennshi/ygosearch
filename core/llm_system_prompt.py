# -*- coding: utf-8 -*-
"""LLM 系统提示词：把自然语言解析成检索 DSL。

设计约束：
- 提示词内不出现任何硬编码卡片名单；词汇表在运行时从 vocab 注入；
- DSL schema 与 core/dsl.py 校验层同一来源（vocab.build_vocab），保证一致。
"""
from pathlib import Path
from typing import Dict

SLANG_PATH = Path(__file__).resolve().parent.parent / "docs" / "玩家黑话检索词典.md"

DSL_SCHEMA = """检索 DSL 是一个 JSON 对象：
{"must": [条件...]}
- "must" 是条件数组，条件之间为 AND 关系；无需条件时输出 {"must": []}
- 检索结果固定排除衍生物和陷阱怪兽

每个条件的格式（field 只能用下列字段，op 只能用该字段列出的 op）：

1. 类型（位标签，支持中文名或位值）
   {"field": "type", "op": "bit_has", "value": ["怪兽", "仪式"]}
   传数组=要求同时具备全部标签；传单个字符串=只要求该标签
2. 属性：{"field": "attribute", "op": "bit_has", "value": "暗"}
3. 种族：{"field": "race", "op": "bit_has", "value": "龙"}
4. 等级/阶级：{"field": "level", "op": "between", "value": [4, 8]}
   区间为闭区间，null 表示不设边界；等值用 {"field": "level", "op": "eq", "value": 7}
5. 灵摆刻度：{"field": "lscale", "op": "between", "value": [1, 5]}
   LINK 值：{"field": "link", "op": "between", "value": [2, 4]}
6. 攻击力/守备力：{"field": "atk", "op": "between", "value": [1000, 2000]}
   "?" 用 -2 表示：{"field": "atk", "op": "eq", "value": -2}
7. 系列（卡名括号里的系列名）：{"field": "setname", "op": "eq", "value": "系列名"}
8. 卡池：{"field": "ot", "op": "in", "value": [1, 3, 9, 11]}
9. 卡名关键词：{"field": "name", "op": "contains", "value": "关键词"}
10. 效果文本关键词：{"field": "desc", "op": "contains", "value": "关键词"}
11. 官方 32 位效果类型（category 位）：
    {"field": "category", "op": "bit_has_any", "value": [1, 2]}   任一位有
    {"field": "category", "op": "bit_has_all", "value": [2, 262144]}  全部都有
    {"field": "category", "op": "bit_has_none", "value": [8388608]}   都没有
12. 效果段精修条件（对每张卡的效果段做匹配，存在至少一段满足即命中）：
    {"field": "effects", "op": "exists", "where": {...}}
    where 可用键（可组合，至少一个）：
      "targets": 0 或 1                    0=不取对象，1=取对象
      "activation": "ignition"|"trigger"|"quick"|"continuous"（或数组）
      "location": "hand"|"field"|"grave"|"banished"|"deck"（或数组）
      "timing": "when_optional"|"if_optional"|"if_mandatory"（或数组）
      "negate_type": "activation"|"effect"（或数组）
      "seg_category_any": [位值或"ritual"...]  段级效果类型，任一命中
                                           "ritual"=仪式相关：效果段文本含
                                           仪式召唤/仪式魔法/仪式怪兽/仪式卡
      "exclude_negate": true               破坏为效果自身动作时使用：
                                           排除『发动无效并破坏』这种
                                           附带破坏的段（negate_type 段）

时点术语对照（timing）：
- when_optional = 「…时才能发动」——会错过时点
- if_optional   = 「…场合才能发动」——不会错过时点
- if_mandatory  = 「…场合发动」——必发

发动类型术语对照（activation）：
- ignition    = 起动效果（自己主要阶段主动发动）
- trigger     = 诱发效果（满足事件条件时发动）
- quick       = 诱发即时效果（对方回合也能发动/咒文速度2）
- continuous  = 永续效果（无需发动，持续适用）

【重要规则】
- 只输出 DSL JSON 本身，不要输出任何解释文字或 markdown 代码块标记。
- 取值必须严格来自下方词汇表，禁止编造。
- 用户问的效果语义（取不取对象、在哪发动、错过时点、无效类型）优先用
  "effects" 条件表达，比 desc 关键词更准。
- 查询『破坏卡片的怪兽/卡』这类破坏语义时，把破坏位（bit 1=魔陷破坏、
  bit 2=怪兽破坏）放进 seg_category_any，并加 "exclude_negate": true。
- 查询『仪式相关效果』时用 effects.where.seg_category_any=["ritual"]；
  仅查询仪式怪兽或仪式魔法卡种时用 type，不能混淆两者。
- 无法从用户输入提取出任何条件时，输出 {"must": [], "error": "说明原因"}。"""


def few_shot_examples() -> str:
    """≥6 条 few-shot：纯字段 / 五维 / 系列 / 混合 / 效果类别 / 降级。"""
    return r"""【示例 1 · 纯字段查询】
用户：等级4以下的暗属性机械族怪兽
输出：{"must": [{"field": "level", "op": "between", "value": [1, 4]}, {"field": "attribute", "op": "bit_has", "value": "暗"}, {"field": "race", "op": "bit_has", "value": "机械"}]}

【示例 2 · 五维查询（取对象 + 发动位置）】
用户：能在手卡发动的不取对象的怪兽效果
输出：{"must": [{"field": "type", "op": "bit_has", "value": "怪兽"}, {"field": "effects", "op": "exists", "where": {"targets": 0, "location": "hand"}}]}

【示例 3 · 五维查询（会错过时点）】
用户：有哪些会错过时点的选发效果
输出：{"must": [{"field": "effects", "op": "exists", "where": {"timing": "when_optional"}}]}

【示例 4 · 系列查询 + 混合条件】
用户：正义盟军里守备力0的怪兽
输出：{"must": [{"field": "setname", "op": "eq", "value": "正义盟军"}, {"field": "type", "op": "bit_has", "value": "怪兽"}, {"field": "def", "op": "eq", "value": 0}]}

【示例 5 · 效果类别查询（破坏类）】
用户：不取对象破坏卡片的仪式怪兽
输出：{"must": [{"field": "type", "op": "bit_has", "value": "怪兽"}, {"field": "type", "op": "bit_has", "value": "仪式"}, {"field": "category", "op": "bit_has_any", "value": [1, 2]}, {"field": "effects", "op": "exists", "where": {"targets": 0, "seg_category_any": [1, 2], "exclude_negate": true}}]}

【示例 6 · 无效系查询】
用户：能把魔陷的发动无效的陷阱卡
输出：{"must": [{"field": "type", "op": "bit_has", "value": "陷阱"}, {"field": "effects", "op": "exists", "where": {"negate_type": "activation", "seg_category_any": [1]}}]}

【示例 7 · 降级（无法映射）】
用户：帮我推荐一副卡组
输出：{"must": [], "error": "这句话不是卡片检索条件，请描述想找的卡片特征，例如属性、种族、等级或效果"}

【示例 8 · 玩家黑话】
用户：能康的怪兽
输出：{"must": [{"field": "type", "op": "bit_has", "value": "怪兽"}, {"field": "effects", "op": "exists", "where": {"negate_type": ["activation", "effect"]}}]}

【示例 9 · 卡种与数值黑话】
用户：打点3000以上的紫怪
输出：{"must": [{"field": "type", "op": "bit_has", "value": "融合"}, {"field": "atk", "op": "between", "value": [3000, null]}]}

【示例 10 · 仪式相关效果】
用户：有仪式相关效果的卡
输出：{"must": [{"field": "effects", "op": "exists", "where": {"seg_category_any": ["ritual"]}}]}

【示例 11 · 通常怪兽黑话】
用户：找白板怪兽
输出：{"must": [{"field": "type", "op": "bit_has", "value": ["怪兽", "通常"]}]}"""


def build_system_prompt(vocab: Dict) -> str:
    """运行时注入词汇表，生成完整系统提示词。"""
    v = vocab or {}
    cat_lines = "\n".join(
        (f"  - bit {c['bit']}（{hex(c['bit'])}）：{c['name']}"
         if isinstance(c["bit"], int) else
         f"  - 派生值 {c['bit']}：{c['name']}（仅用于 effects.where.seg_category_any）")
        for c in v.get("categories", []))
    setnames = "、".join(v.get("setnames", []))
    races = "、".join(v.get("races", []))
    attrs = "、".join(v.get("attributes", []))
    slang = SLANG_PATH.read_text(encoding="utf-8")
    return f"""你是游戏王卡片检索系统的意图解析器。把用户的自然语言解析成检索 DSL，输出纯 JSON。

{DSL_SCHEMA}

== 词汇表（唯一合法取值来源）==

主类型：怪兽、魔法、陷阱
怪兽细分标签：{('、'.join(v.get('type_groups', {}).get('怪兽细分', [])))}
怪兽能力中的「特殊召唤」是卡片类型位，指特殊召唤怪兽（如积木龙），与效果类型中表示“具有特殊召唤效果”的「特殊召唤」不同。用户明确找特殊召唤怪兽时用 type；找能特殊召唤其他怪兽的效果时用 category 或 effects。
魔法细分标签：{('、'.join(v.get('type_groups', {}).get('魔法细分', [])))}
陷阱细分标签：{('、'.join(v.get('type_groups', {}).get('陷阱细分', [])))}
属性：{attrs}
种族：{races}
卡池 ot 值：{('；'.join(str(o['value']) + '=' + o['label'] for o in v.get('ot', [])))}

官方 category 32 位及派生效果类型对照：
{cat_lines}

系列名（共 {len(v.get('setnames', []))} 个，必须精确使用其中之一）：
{setnames}

== few-shot 示例 ==

{few_shot_examples()}

== 玩家用语词典 ==

{slang}

应用词典时保持严格语义：例如「擦」不能等同于所有效果无效，「耐性」默认指战斗破坏抗性。当前检索固定排除衍生物；若用户仅查询 Token／毛，不要改查其他卡种。遇到 DSL 无法精确表达的概念，使用可验证的卡片文本条件或返回无法精确映射的原因，不要编造字段。

现在请解析用户输入，只输出 DSL JSON。"""
