"""Small, local corpus references for NL → literal card wording. No model calls."""
from functools import lru_cache
from pathlib import Path
import sqlite3

DB_PATH = Path(__file__).resolve().parent.parent / "cdb" / "card_effects.db"
TERMS = {
    "响应限制（不能连锁）": ("不能对应", "不能连锁"),
    "代替处理（须核对代替的动作）": ("代替破坏", "作为代替"),
    "取对象抗性": ("不会成为效果的对象", "不会成为对方的效果的对象", "不能把这张卡作为卡的效果的对象"),
    "效果影响抗性（须区分适用范围）": ("不受其他卡的效果影响", "不受对方的效果影响"),
    "回卡组底": ("卡组最下面", "卡组最下方"),
    "离场（不一定是离场触发）": ("从场上离开", "离开场上"),
    "卡名次数限制": ("1回合只能使用1次", "1回合只能发动1张"),
    "卡名变化": ("卡名当作", "卡名只要"),
    "丢弃作为代价": ("丢弃才能发动", "丢弃去墓地才能发动"),
    "战斗期间限制发动": ("直到伤害步骤结束时", "直到伤害计算步骤结束时"),
}


@lru_cache(maxsize=1)
def corpus_reference():
    """Only offer phrases that actually occur; bounded excerpts are data, not rules."""
    if not DB_PATH.exists():
        return []
    result = []
    db = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)
    try:
        for concept, phrases in TERMS.items():
            entries = []
            for phrase in phrases:
                row = db.execute(
                    "SELECT text FROM card_effects WHERE instr(text, ?) > 0 "
                    "ORDER BY length(text), card_id, effect_no LIMIT 1", (phrase,)).fetchone()
                if row:
                    text = row[0]
                    start = max(0, text.index(phrase) - 60)
                    entries.append({"phrase": phrase, "excerpt": text[start:start + 220]})
            if entries:
                result.append({"concept": concept, "attested_wording": entries})
    finally:
        db.close()
    return result
