"""新增筛选、隐藏卡种与 AI 服务配置的回归检查。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import app as A
import constants as C
import dsl as D
import llm_client as L
import llm_system_prompt as P


class SearchUpdates(unittest.TestCase):
    def setUp(self):
        self.client = A.app.test_client()

    def search(self, field=None, bounds=None, **extra):
        must = [] if field is None else [
            {"field": field, "op": "between", "value": bounds}]
        response = self.client.post("/api/search",
                                    json={"dsl": {"must": must}, **extra})
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def test_excluded_types_even_when_legacy_flag_false(self):
        result = self.search(exclude_token=False)
        self.assertGreater(result["total"], 0)
        self.assertNotIn("衍生物", [t["label"] for t in A.VOCAB["types"]])
        self.assertNotIn("陷阱怪兽", [t["label"] for t in A.VOCAB["types"]])
        self.assertNotIn("衍生物", [c["name"] for c in A.VOCAB["categories"]])
        for card in result["cards"]:
            self.assertEqual(card["type"] & (C.TYPE_TOKEN | C.TYPE_TRAPMONSTER), 0)

    def test_link_and_pendulum_ranges(self):
        for field, bounds, bit in (
                ("link", [2, 3], C.TYPE_LINK),
                ("lscale", [1, 3], C.TYPE_PENDULUM)):
            result = self.search(field, bounds)
            self.assertGreater(result["total"], 0)
            for card in result["cards"]:
                self.assertTrue(card["type"] & bit)
                value = card["level"] if field == "link" else card["lscale"]
                self.assertLessEqual(bounds[0], value)
                self.assertLessEqual(value, bounds[1])

    def test_level_does_not_include_link(self):
        result = self.search("level", [2, 3])
        self.assertGreater(result["total"], 0)
        self.assertTrue(all(not card["type"] & C.TYPE_LINK for card in result["cards"]))

    def test_link_defense_is_not_arrow_bitmap(self):
        result = self.search("link", [1, 5])
        self.assertGreater(result["total"], 0)
        self.assertTrue(all(card["def_str"] == "—" for card in result["cards"]))

    def test_special_summon_ability_includes_block_dragon(self):
        self.assertIn("特殊召唤", A.VOCAB["type_groups"]["怪兽细分"])
        response = self.client.post("/api/search", json={"dsl": {"must": [
            {"field": "type", "op": "bit_has", "value": "特殊召唤"},
            {"field": "name", "op": "contains", "value": "积木龙"}]}})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(card["name"] == "积木龙"
                            for card in response.get_json()["cards"]))

    def test_alias_expansion_is_off_by_default(self):
        query = {"dsl": {"must": [
            {"field": "name", "op": "contains", "value": "霸王龙 扎克"}]}}
        default = self.client.post("/api/search", json=query).get_json()
        expanded = self.client.post("/api/search",
            json={**query, "expand_alias": True}).get_json()
        self.assertLess(default["total"], expanded["total"])

    def test_same_name_artworks_collapse_before_paging(self):
        for name, original_id in (("黑魔术师", 46986414), ("防火龙", 5043010)):
            result = self.client.post("/api/search", json={"dsl": {"must": [
                {"field": "name", "op": "contains", "value": name}]},
                "limit": 100}).get_json()
            exact = [card for card in result["cards"] if card["name"] == name]
            self.assertEqual([card["id"] for card in exact], [original_id])
            self.assertEqual(result["total"], len(result["cards"]))
            self.assertEqual(len({card["name"] for card in result["cards"]}),
                             result["total"])

        all_cards = self.search(limit=1)
        expected = A.engine.db.execute(
            "SELECT COUNT(DISTINCT t.name) FROM cards.datas d "
            "JOIN cards.texts t ON t.id=d.id WHERE (d.type & ?) = 0",
            (C.TYPE_TOKEN | C.TYPE_TRAPMONSTER,)).fetchone()[0]
        self.assertEqual(all_cards["total"], expected)

    def test_filtered_artwork_is_kept_when_original_does_not_match(self):
        result = self.client.post("/api/search", json={"dsl": {"must": [
            {"field": "type", "op": "bit_has", "value": "通常"},
            {"field": "name", "op": "contains", "value": "混沌战士"}]},
            "limit": 100}).get_json()
        exact = [card for card in result["cards"] if card["name"] == "混沌战士"]
        self.assertEqual([card["id"] for card in exact], [5405695])

    def test_all_ritual_related_results_are_reachable_by_page(self):
        dsl = {"must": [{"field": "effects", "op": "exists", "where": {
            "seg_category_any": ["ritual"]}}]}
        first = self.client.post("/api/search", json={"dsl": dsl,
            "limit": 100, "offset": 0}).get_json()
        self.assertGreater(first["total"], 100)
        seen = set()
        for offset in range(0, first["total"], 100):
            result = self.client.post("/api/search", json={"dsl": dsl,
                "limit": 100, "offset": offset}).get_json()
            self.assertTrue(result["ok"])
            self.assertEqual(result["total"], first["total"])
            self.assertEqual(len(result["cards"]),
                             min(100, first["total"] - offset))
            for card in result["cards"]:
                self.assertNotIn(card["id"], seen)
                seen.add(card["id"])
                effects = A.engine.effects_of(card["id"])
                self.assertTrue(any(D.is_ritual_effect(s["seg_type"], s["text"])
                                    for s in effects))
        self.assertEqual(len(seen), first["total"])

    def test_ritual_effect_type_can_or_with_official_type(self):
        dsl = {"must": [{"field": "effects", "op": "exists", "where": {
            "seg_category_any": ["ritual", 0x10000000]}}]}
        combined = self.client.post("/api/search", json={"dsl": dsl,
            "limit": 1}).get_json()
        self.assertTrue(combined["ok"])
        self.assertIn("仪式相关", combined["described"])
        self.assertIn("融合相关", combined["described"])
        self.assertGreater(combined["total"], 325)
        bad = self.client.post("/api/search", json={"dsl": {"must": [
            {"field": "category", "op": "bit_has_any", "value": "ritual"}]}})
        self.assertEqual(bad.status_code, 400)

    def test_config_presets_and_secret_not_echoed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            saved = L.save_config({"provider": "deepseek", "api_key": "test-secret"},
                                  path)
            self.assertTrue(saved["configured"])
            self.assertNotIn("test-secret", json.dumps(saved))
            self.assertEqual(L.load_config(path)["model"], "deepseek-flash")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            L.save_config({"provider": "deepseek", "api_key": ""}, path)
            self.assertEqual(L.load_config(path)["api_key"], "test-secret")
            with self.assertRaises(L.LLMConfigError):
                L.save_config({"provider": "kimi", "api_key": ""}, path)
            local = L.save_config({"provider": "local", "model": "qwen3",
                                   "base_url": "http://127.0.0.1:11434/v1"},
                                  path)
            self.assertEqual(local["model"], "qwen3")
            with self.assertRaises(L.LLMConfigError):
                L.save_config({"provider": "local", "model": "qwen3",
                               "base_url": "http://example.com/v1"}, path)

    def test_config_api_saves_without_echoing_key(self):
        with tempfile.TemporaryDirectory() as directory:
            original = L.CONFIG_PATH
            L.CONFIG_PATH = Path(directory) / "config.json"
            try:
                response = self.client.post(
                    "/api/llm_config",
                    json={"provider": "glm", "api_key": "api-test-secret"})
                self.assertEqual(response.status_code, 200, response.get_json())
                self.assertNotIn("api-test-secret", response.get_data(as_text=True))
                status = self.client.get("/api/llm_config").get_json()
                self.assertTrue(status["configured"])
                self.assertEqual(status["provider"], "glm")
                self.assertNotIn("api-test-secret", json.dumps(status))
            finally:
                L.CONFIG_PATH = original

    def test_local_model_scan_and_address_guard(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                return b'{"data":[{"id":"qwen3"},{"id":"deepseek-r1"}]}'

        class Opener:
            def open(self, request, timeout):
                self.url = request.full_url
                return Response()

        opener = Opener()
        with patch.object(L.urllib.request, "build_opener", return_value=opener):
            models = L.list_local_models("http://127.0.0.1:8000/v1")
        self.assertEqual(models, ["deepseek-r1", "qwen3"])
        self.assertEqual(opener.url, "http://127.0.0.1:8000/v1/models")
        with self.assertRaises(L.LLMConfigError):
            L.list_local_models("http://example.com/v1")
        with patch.object(A, "list_local_models", return_value=models):
            response = self.client.post("/api/local_models",
                                        json={"base_url": "http://127.0.0.1:8000/v1"})
            self.assertEqual(response.get_json()["models"], models)

    def test_slang_glossary_is_in_natural_language_prompt(self):
        prompt = P.build_system_prompt(A.VOCAB)
        for phrase in ("康", "擦", "威风抗性", "打点", "紫怪",
                       "凡骨/白板＝通常怪兽"):
            self.assertIn(phrase, prompt)
        self.assertIn('"value": ["怪兽", "通常"]', prompt)
        self.assertIn("Token／毛", prompt)


if __name__ == "__main__":
    unittest.main()
