"""Text fallback semantics, safe literal matching, and model/API contract."""
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'core'))
import app as A
import dsl as D
import llm_client as L
import llm_system_prompt as P
from text_reference import corpus_reference


class TextSearchTests(unittest.TestCase):
    def test_alternative_wordings_are_or(self):
        words = ['不能对应', '不能连锁']
        query = {'must': [{'field': 'desc', 'op': 'contains_any', 'value': words}]}
        result = A.engine.search(query, limit=100)
        expected = A.engine.db.execute(
            'SELECT COUNT(DISTINCT t.name) FROM cards.datas d JOIN cards.texts t ON d.id=t.id '
            'WHERE (d.type & ?) = 0 AND (instr(t.desc, ?) > 0 OR instr(t.desc, ?) > 0)',
            [A.C.TYPE_TOKEN | A.C.TYPE_TRAPMONSTER, *words]).fetchone()[0]
        self.assertEqual(result['total'], expected)
        self.assertGreater(result['total'], 0)
        self.assertIn('文本含任一', result['described'])
        self.assertTrue(all(any(w in c['desc'] for w in words) for c in result['cards']))

    def test_same_segment_and_literal_escaping(self):
        db = sqlite3.connect(':memory:')
        db.execute('CREATE TABLE card_effects (card_id, seg_type, text, seg_category)')
        db.executemany('INSERT INTO card_effects VALUES (?, ?, ?, ?)', [
            (1, 'monster', '送回卡组最下面。', 32),
            (2, 'monster', '回到卡组。', 32),
            (2, 'monster', '卡组最下面的卡加入手卡。', 512),
            (3, 'rule', '送回卡组最下面。', 32),
            (4, 'monster', 'literal %_\\ term', 0),
            (5, 'monster', 'literal any term', 0),
        ])
        try:
            params = []
            sql = D._effects_subsql({'seg_category_any': [32], 'text_any': ['卡组最下面', '卡组最下方']}, params)
            self.assertEqual(db.execute('SELECT card_id FROM card_effects e WHERE '+sql, params).fetchall(), [(1,)])
            params = []
            sql = D._effects_subsql({'text_all': ['literal', '%_\\']}, params)
            self.assertEqual(db.execute('SELECT card_id FROM card_effects e WHERE '+sql, params).fetchall(), [(4,)])
        finally:
            db.close()

    def test_reject_invalid_text_lists(self):
        for value in ([], '', [None], [''], ['x'*161], ['x']*17, {'x': 'y'}):
            for query in (
                {'must': [{'field': 'desc', 'op': 'contains_any', 'value': value}]},
                {'must': [{'field': 'effects', 'op': 'exists', 'where': {'text_any': value}}]},
            ):
                with self.assertRaises(D.DSLError):
                    D.normalize(query, {})

    def test_prompt_has_attested_examples_and_valid_dsls(self):
        prompt = P.build_system_prompt(A.VOCAB)
        self.assertIn('不能直接搜', prompt)
        self.assertIn('同一个 effects.where', prompt)
        self.assertTrue(corpus_reference())
        for entry in corpus_reference():
            for item in entry['attested_wording']:
                self.assertIn(item['phrase'], item['excerpt'])
        for line in P.TEXT_RULES_PATH.read_text().splitlines():
            if line.startswith('输出：'):
                D.normalize(json.loads(line.removeprefix('输出：')), A.engine.setnames)

    def test_nl_endpoint_preserves_structured_and_text_conditions(self):
        query = {'must': [
            {'field': 'type', 'op': 'bit_has', 'value': ['魔法', '速攻']},
            {'field': 'desc', 'op': 'contains_any', 'value': ['不能对应', '不能连锁']}]}
        captured = []
        def fake_chat(self, messages):
            captured.append(messages[0]['content'])
            return json.dumps(query, ensure_ascii=False)
        with patch.object(L, 'load_config', return_value={'base_url': 'http://localhost/v1', 'api_key': 'test', 'model': 'test'}), patch.object(L.LLMClient, '_chat', fake_chat):
            result = A.app.test_client().post('/api/nl_search', json={'query': '不能被连锁响应的速攻魔法'})
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['dsl'], query)
        self.assertEqual(data['total'], A.engine.search(query, limit=1)['total'])
        self.assertIn('文本含任一', data['nl_described'])
        self.assertIn('本地卡库措辞参考', captured[0])

    def test_explicit_unmapped_error_cannot_search_everything(self):
        client = object.__new__(L.LLMClient)
        replies = iter(['{"must": [], "error": "需要具体局面才能判断苏生限制"}'] * 2)
        client._chat = lambda messages: next(replies)
        result = client.nl_to_dsl('找现在可以苏生的怪兽', A.VOCAB, A.engine.setnames)
        self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()
