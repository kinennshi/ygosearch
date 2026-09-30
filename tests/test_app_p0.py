# -*- coding: utf-8 -*-
"""P0 验收测试：Web 层 + AI 模式（mock LLM）+ 注入安全。

运行：python tests/test_app_p0.py  （无 pytest 依赖，直接可跑）
"""
import io
import json
import sys
import unittest
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import dsl as D                          # noqa: E402
import app as app_module                 # noqa: E402
import llm_client as LC                  # noqa: E402
from strings_conf import parse_strings_conf  # noqa: E402
from vocab import build_vocab            # noqa: E402

app = app_module.app
app.testing = True
client = app.test_client()

SETNAMES, _ = parse_strings_conf()
VOCAB = build_vocab(SETNAMES)

# 基准 DSL：不取对象破坏卡片的仪式怪兽（文档基准 ≈22 张）
BASE_DSL = {"must": [
    {"field": "type", "op": "bit_has", "value": ["怪兽", "仪式"]},
    {"field": "effects", "op": "exists", "where": {
        "targets": 0, "seg_category_any": [1, 2], "exclude_negate": True}},
]}

# 三个基准查询：手动 DSL 与 AI(mock LLM) 产出 DSL 必须结果一致
BENCHMARKS = [
    ("不取对象破坏卡片的仪式怪兽", BASE_DSL),
    ("投掷硬币相关的陷阱卡", {"must": [
        {"field": "type", "op": "bit_has", "value": "陷阱"},
        {"field": "desc", "op": "contains", "value": "投掷硬币"}]}),
    ("8星以上暗属性龙族", {"must": [
        {"field": "race", "op": "bit_has", "value": "龙"},
        {"field": "attribute", "op": "bit_has", "value": "暗"},
        {"field": "level", "op": "between", "value": [8, None]}]}),
]


class StubLLM:
    """替换 app 模块里的 LLMClient：按脚本返回固定 DSL 或失败。"""

    def __init__(self, script):
        self.script = script

    def nl_to_dsl(self, text, vocab, setnames):
        item = self.script.pop(0)
        if item.get("ok"):
            return {"ok": True, "dsl": item["dsl"], "raw": "stub"}
        return {"ok": False, "message": item.get(
            "message", "这句话我没能理解，换个说法试试")}


def post(path, body):
    r = client.post(path, data=json.dumps(body),
                    content_type="application/json")
    return r.status_code, r.get_json()


def get(path):
    r = client.get(path)
    return r.status_code, r.get_json()


class TestVocab(unittest.TestCase):

    def test_vocab_shape(self):
        st, r = get("/api/vocab")
        self.assertEqual(st, 200)
        self.assertTrue(r["ok"])
        v = r["vocab"]
        for key in ("type_groups", "types", "attributes", "races",
                    "categories", "setnames", "ot", "effects"):
            self.assertIn(key, v)
        self.assertNotIn("none", [x["value"] for x in v["effects"]["activation"]])
        self.assertEqual(len(v["setnames"]), len(set(v["setnames"])))
        self.assertTrue(all("bit" in t and "label" in t for t in v["types"]))


class TestManualSearch(unittest.TestCase):

    def test_baseline_22(self):
        """P0 基准：不取对象破坏卡片的仪式怪兽 ≈22（±3）。"""
        st, r = post("/api/search", {"dsl": BASE_DSL})
        self.assertEqual(st, 200)
        self.assertTrue(r["ok"])
        self.assertLessEqual(abs(r["total"] - 22), 3,
                             f"基准查询命中 {r['total']} 张，期望 22±3")
        self.assertGreater(len(r["cards"]), 0)
        self.assertTrue(r["cards"][0].get("hit_reasons"))

    def test_when_optional_result_set(self):
        """P0：timing=when_optional 结果集非空且命中段时点正确。"""
        dsl = {"must": [{"field": "effects", "op": "exists", "where": {
            "timing": "when_optional"}}]}
        st, r = post("/api/search", {"dsl": dsl, "limit": 30})
        self.assertEqual(st, 200)
        self.assertGreater(r["total"], 0)
        eng = app_module.engine
        for c in r["cards"][:10]:
            segs = eng._matching_segments(c["id"], {"timing": ["when_optional"]})
            self.assertTrue(segs, f"{c['name']} 无 when_optional 段")
            self.assertTrue(all(s["timing"] == "when_optional" for s in segs))

    def test_effects_enum_dims_from_vocab(self):
        """防回归：四个枚举维度用 vocab 首个取值走 API 必须成功。

        （曾因前端 option value 取错字段导致 activation/location/
        negate_type 报「非法取值」，此用例锁死后端枚举合法性。）
        """
        st, vr = get("/api/vocab")
        self.assertEqual(st, 200)
        fx = vr["vocab"]["effects"]
        for dim in ("activation", "location", "timing", "negate_type"):
            first = fx[dim][0]["value"]
            dsl = {"must": [{"field": "effects", "op": "exists",
                             "where": {dim: [first]}}]}
            st, r = post("/api/search", {"dsl": dsl, "limit": 5})
            self.assertEqual(st, 200, f"{dim}={first!r} 检索失败：{r}")
            self.assertTrue(r.get("ok"), f"{dim}={first!r}：{r.get('message')}")
            self.assertGreater(r["total"], 0,
                               f"{dim}={first!r} 不应有 0 结果")

    def test_pagination_and_limit(self):
        st, r = post("/api/search", {"dsl": BASE_DSL, "limit": 5, "offset": 2})
        self.assertEqual(st, 200)
        self.assertLessEqual(len(r["cards"]), 5)

    def test_bad_dsl_readable_error(self):
        st, r = post("/api/search", {"dsl": {"must": [{"field": "非法字段",
                                                       "op": "eq"}]}})
        self.assertEqual(st, 400)
        self.assertIn("field 非法", r["message"])

    def test_malformed_values_are_client_errors(self):
        for condition in (
                {"field": "level", "op": "between", "value": ["abc", 10]},
                {"field": "atk", "op": "eq", "value": 10 ** 100},
                {"field": "level", "op": "eq", "value": 4.5},
                {"field": "effects", "op": "exists",
                 "where": {"activation": [{}]}},
                {"field": "effects", "op": "exists",
                 "where": {"targets": True}}):
            st, r = post("/api/search", {"dsl": {"must": [condition]}})
            self.assertEqual(st, 400, r)

    def test_rule_text_is_not_an_effect(self):
        st, r = post("/api/search", {"dsl": {"must": [
            {"field": "effects", "op": "exists",
             "where": {"activation": "none"}}]}})
        self.assertEqual(st, 200)
        self.assertEqual(r["total"], 0)

    def test_alias_still_obeys_card_pool(self):
        st, r = post("/api/search", {"dsl": {"must": [
            {"field": "name", "op": "contains", "value": "混沌战士"},
            {"field": "ot", "op": "in", "value": [1]}]},
            "expand_alias": True})
        self.assertEqual(st, 200)
        self.assertTrue(r["cards"])
        self.assertTrue(all(c["ot"] == 1 for c in r["cards"]))

    def test_alias_chain_expands_transitively(self):
        st, r = post("/api/search", {"dsl": {"must": [
            {"field": "name", "op": "contains", "value": "霸王龙 扎克"}]},
            "expand_alias": True})
        self.assertEqual(st, 200)
        ids = {c["id"] for c in r["cards"]}
        self.assertTrue({13331639, 6218704} <= ids)
        self.assertNotIn(6218705, ids)  # 同名异画只展示一张


class TestInjectionSafety(unittest.TestCase):

    def test_name_keyword_injection(self):
        """单引号/分号/注释注入：要么被转义当普通文本，要么报可读错误，绝不执行。"""
        for payload in ["'; DROP TABLE texts;--",
                        "%' OR 1=1 --", "x%'; UPDATE datas SET atk=999999--"]:
            st, r = post("/api/search", {"dsl": {"must": [
                {"field": "name", "op": "contains", "value": payload}]}})
            self.assertIn(st, (200, 400), payload)
            if st == 200:
                for c in r["cards"]:
                    self.assertIn(payload.replace("\\", "").replace("%", "")
                                  .strip("' ;")[:6],
                                  json.dumps(c["name"], ensure_ascii=False)
                                  + c["name"])
        # 表还在（DROP 未执行）
        st, r = post("/api/search", {"dsl": {"must": [
            {"field": "name", "op": "contains", "value": "黑魔术师"}]}})
        self.assertEqual(st, 200)

    def test_sql_structure_is_parameterized(self):
        norm = D.normalize(BASE_DSL, SETNAMES)
        q = D.compile(norm, SETNAMES)
        # SQL 里不允许出现裸引号包裹的用户值（值全在 params）
        for p in q.params:
            self.assertNotIn("DROP", str(p).upper())
        self.assertIn("?", q.sql)

    def test_setname_injection(self):
        st, r = post("/api/search", {"dsl": {"must": [
            {"field": "setname", "op": "eq",
             "value": "闪刀'; DROP TABLE card_effects;--"}]}})
        self.assertIn(st, (200, 400))
        # 表还在
        st, r = post("/api/search", {"dsl": BASE_DSL})
        self.assertEqual(st, 200)


class TestNlSearchMockLLM(unittest.TestCase):

    def setUp(self):
        self._orig = app_module.LLMClient

    def tearDown(self):
        app_module.LLMClient = self._orig

    def _stub(self, script):
        app_module.LLMClient = lambda *a, **k: StubLLM(list(script))

    def test_benchmark_consistency(self):
        """P0：3 个基准查询，AI(mock) 与手动模式结果集完全一致。"""
        for _query, dsl in BENCHMARKS:
            st_manual, r_manual = post("/api/search", {"dsl": dsl})
            self.assertEqual(st_manual, 200)
            self._stub([{"ok": True, "dsl": dsl}])
            st_ai, r_ai = post("/api/nl_search", {"query": _query})
            self.assertEqual(st_ai, 200, r_ai)
            self.assertTrue(r_ai["ok"])
            # AI 响应回显的 DSL 应与 mock LLM 产出一致（原样回显）
            self.assertEqual(r_ai["dsl"], dsl)
            self.assertEqual(r_ai["total"], r_manual["total"])
            names_ai = [c["id"] for c in r_ai["cards"]]
            names_man = [c["id"] for c in r_manual["cards"]]
            self.assertEqual(names_ai, names_man)

    def test_nl_result_carries_dsl_echo(self):
        self._stub([{"ok": True, "dsl": BASE_DSL}])
        st, r = post("/api/nl_search", {"query": "不取对象破坏卡片的仪式怪兽"})
        self.assertEqual(st, 200)
        self.assertIn("dsl", r)
        self.assertIn("nl_described", r)

    def test_real_llm_client_contract(self):
        cfg = ROOT / "tmp" / "test_real_llm_contract.json"
        cfg.write_text(json.dumps({"llm": {"base_url": "http://mock/v1",
                                           "api_key": "k", "model": "m"}}),
                       encoding="utf-8")
        try:
            llm = LC.LLMClient(cfg)
            llm._chat = lambda messages, temperature=0.0: json.dumps(BASE_DSL)
            app_module.LLMClient = lambda *a, **k: llm
            st, r = post("/api/nl_search", {"query": "不取对象破坏卡片的仪式怪兽"})
            self.assertEqual(st, 200, r)
            self.assertGreater(r["total"], 0)
        finally:
            cfg.unlink(missing_ok=True)

    def test_llm_fail_twice_friendly_message(self):
        self._stub([{"ok": False}])
        st, r = post("/api/nl_search", {"query": "随便什么东西"})
        self.assertEqual(st, 422)
        self.assertFalse(r["ok"])
        self.assertIn("这句话我没能理解，换个说法试试", r["message"])

    def test_empty_and_oversize_query(self):
        self._stub([])
        st, r = post("/api/nl_search", {"query": "  "})
        self.assertEqual(st, 400)
        st, r = post("/api/nl_search", {"query": "字" * 501})
        self.assertEqual(st, 400)


class TestLLMClientRetryLogic(unittest.TestCase):
    """llm_client 自身：JSON 解析 + 校验失败回喂重试一次 + 两次失败报错。"""

    def setUp(self):
        # 临时 config
        self.cfg = Path(ROOT / "tmp" / "test_llm_config.json")
        self.cfg.write_text(json.dumps({
            "llm": {"base_url": "http://mock/v1", "api_key": "k",
                    "model": "m"}}), encoding="utf-8")

    def tearDown(self):
        self.cfg.unlink(missing_ok=True)

    def _client_with_chat(self, replies):
        c = LC.LLMClient(self.cfg)
        c._chat = lambda messages, temperature=0.0: replies.pop(0)
        return c

    def test_clean_json_ok(self):
        c = self._client_with_chat(['{"must": []}'])
        r = c.nl_to_dsl("任意", VOCAB, SETNAMES)
        self.assertTrue(r["ok"])

    def test_markdown_fence_ok(self):
        c = self._client_with_chat(['```json\n{"must": []}\n```'])
        r = c.nl_to_dsl("任意", VOCAB, SETNAMES)
        self.assertTrue(r["ok"])

    def test_retry_on_invalid_dsl(self):
        bad = '{"no_must_field": 1}'
        good = '{"must": [{"field": "type", "op": "bit_has", "value": "陷阱"}]}'
        c = self._client_with_chat([bad, good])
        r = c.nl_to_dsl("陷阱卡", VOCAB, SETNAMES)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["dsl"]["must"][0]["field"], "type")

    def test_retry_prompt_contains_error(self):
        captured = []
        c = LC.LLMClient(self.cfg)
        replies = ['{"wrong": true}',
                   '{"must": [{"field": "type", "op": "bit_has", "value": "陷阱"}]}']

        def fake_chat(messages, temperature=0.0):
            captured.append(list(messages))
            return replies.pop(0)
        c._chat = fake_chat
        r = c.nl_to_dsl("陷阱卡", VOCAB, SETNAMES)
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(len(captured), 2)
        # 第二轮的 user 消息里带了第一轮的校验错误
        last_user = [m for m in captured[1] if m["role"] == "user"][-1]
        self.assertIn("DSL", last_user["content"])

    def test_fail_twice_friendly(self):
        c = self._client_with_chat(['{"wrong": 1}', 'not json at all'])
        r = c.nl_to_dsl("任意", VOCAB, SETNAMES)
        self.assertFalse(r["ok"])
        self.assertEqual(r["message"], "这句话我没能理解，换个说法试试")

    def test_config_missing_readable(self):
        with self.assertRaises(LC.LLMConfigError) as cm:
            LC.load_config(ROOT / "tmp" / "no_such_config.json")
        self.assertIn("config.json", str(cm.exception))

    def test_config_incomplete(self):
        p = ROOT / "tmp" / "test_bad_config.json"
        p.write_text(json.dumps({"llm": {"base_url": "x"}}), encoding="utf-8")
        with self.assertRaises(LC.LLMConfigError) as cm:
            LC.load_config(p)
        self.assertIn("api_key", str(cm.exception))
        p.unlink(missing_ok=True)


class TestCardDetail(unittest.TestCase):

    def test_card_detail_with_segments(self):
        st, r = get("/api/card/17732278")   # 打草惹蛇
        if st == 404:
            self.skipTest("样例卡不在库中")
        self.assertEqual(st, 200)
        self.assertTrue(r["card"]["effects"])

    def test_card_404(self):
        st, _r = get("/api/card/99999999")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(
        sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
