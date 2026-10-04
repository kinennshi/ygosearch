# -*- coding: utf-8 -*-
"""Flask 应用：手动筛选 + AI 自然语言双模式检索。

路由：
- GET  /                → web/index.html
- GET  /api/vocab       → 词汇表（前端控件数据源）
- POST /api/search      → 手动筛选：前端直接提交 DSL JSON
- POST /api/nl_search   → AI 模式：自然语言 → LLM 翻译成 DSL → 同一引擎执行
- GET  /api/card/<id>   → 卡片详情（含效果段拆分与五维分类）

安全性：所有 SQL 由 core/dsl.py 编译，全部参数化（? 占位符），
本层不拼接任何用户输入进 SQL。
"""
import io
import json
import sys
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import constants as C
import dsl as D
from engine import Engine
from llm_client import (LLMClient, LLMConfigError, config_status, save_config,
                        list_local_models, load_config)
from strings_conf import parse_lflist_version
from vocab import build_vocab

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

app = Flask(__name__, static_folder=None)

engine = Engine()
AVAILABLE_OT = {row[0] for row in engine.db.execute("SELECT DISTINCT ot FROM cards.datas")}
VOCAB = build_vocab(engine.setnames, AVAILABLE_OT)
CARD_COUNT = engine.db.execute("SELECT COUNT(*) FROM cards.datas").fetchone()[0]
CARD_VERSION = parse_lflist_version()
MAX_QUERY_LEN = 500


def ok(payload: dict) -> Response:
    payload.setdefault("ok", True)
    return jsonify(payload)


def fail(message: str, status: int = 400) -> Response:
    return jsonify({"ok": False, "message": message}), status


@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/assets/<path:filename>")
def web_asset(filename):
    return send_from_directory(WEB_DIR / "assets", filename)


@app.get("/api/vocab")
def api_vocab():
    return ok({"vocab": VOCAB, "card_count": CARD_COUNT,
               "card_version": CARD_VERSION})


@app.get("/api/llm_config")
def api_llm_config():
    return ok(config_status())


@app.post("/api/llm_config")
def api_save_llm_config():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("请求体应为 JSON 对象")
    try:
        return ok({"config": save_config(body)})
    except LLMConfigError as e:
        return fail(str(e))


@app.post("/api/local_models")
def api_local_models():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("请求体应为 JSON 对象")
    try:
        base_url = body.get("base_url", "")
        api_key = body.get("api_key", "")
        if not api_key:
            try:
                saved = load_config()
                if (saved.get("provider") == "local"
                        and saved.get("base_url") == base_url):
                    api_key = saved["api_key"]
            except LLMConfigError:
                pass
        models = list_local_models(base_url, api_key)
        return ok({"models": models})
    except LLMConfigError as e:
        return fail(str(e), 502)


def _run_search(dsl_json, limit, offset, expand_alias=None, sort=None):
    try:
        result = engine.search(dsl_json, expand_alias=expand_alias,
                               limit=limit, offset=offset, sort=sort)
    except D.DSLError as e:
        return fail(str(e))
    except Exception as e:   # 防御性兜底，不把堆栈抛给前端
        return fail(f"检索执行失败：{e}", 500)
    return ok({"total": result["total"], "described": result["described"],
               "cards": result["cards"]})


_SORTS = (None, "atk_asc", "atk_desc", "def_asc", "def_desc",
          "level_asc", "level_desc", "id_asc", "id_desc")


@app.post("/api/search")
def api_search():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("请求体应为 JSON 对象")
    dsl_json = body.get("dsl")
    if dsl_json is None:
        dsl_json = {"must": body.get("must", []),
                    "exclude_token": body.get("exclude_token", True)}
    limit = _int_param(body.get("limit"), default=100, lo=1, hi=500)
    offset = _int_param(body.get("offset"), default=0, lo=0, hi=10 ** 9)
    expand = body.get("expand_alias")
    if expand is not None and not isinstance(expand, bool):
        return fail("expand_alias 应为布尔值")
    sort = body.get("sort")
    if sort not in _SORTS:
        return fail("sort 参数非法")
    return _run_search(dsl_json, limit, offset, expand, sort)


@app.post("/api/nl_search")
def api_nl_search():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return fail("请求体应为 JSON 对象")
    query = body.get("query")
    if not isinstance(query, str):
        return fail("query 应为字符串")
    query = query.strip()
    if not query:
        return fail("请输入自然语言查询")
    if len(query) > MAX_QUERY_LEN:
        return fail(f"查询过长（最多 {MAX_QUERY_LEN} 字）")

    try:
        client = LLMClient()
    except LLMConfigError as e:
        return fail(str(e), 503)

    llm = client.nl_to_dsl(query, VOCAB, engine.setnames)
    if not llm.get("ok"):
        return fail(llm.get("message", "这句话我没能理解，换个说法试试"), 422)

    limit = _int_param(body.get("limit"), default=100, lo=1, hi=500)
    offset = _int_param(body.get("offset"), default=0, lo=0, hi=10 ** 9)
    resp = _run_search(llm["dsl"], limit, offset, expand_alias=False)
    # AI 模式附加：回显 LLM 产出的 DSL 与人类可读解释
    if resp.status_code == 200:
        data = resp.get_json()
        data["dsl"] = llm["dsl"]
        data["nl_described"] = data.get("described")
        resp = jsonify(data)
    return resp


@app.get("/api/card/<int:card_id>")
def api_card(card_id: int):
    c = engine.card(card_id)
    if not c:
        return fail("卡片不存在", 404)
    dec = engine._decode_card(c)
    segs = engine.effects_of(card_id)
    dec["effects"] = [
        {"effect_no": s["effect_no"], "seg_type": s["seg_type"],
         "text": s["text"], "text_ja": s["text_ja"],
         "targets": s["targets"], "activation": s["activation"],
         "location": s["location"], "timing": s["timing"],
         "negate_type": s["negate_type"],
         "seg_category_names": s["seg_category_names"],
         "confidence": s["confidence"]}
        for s in segs]
    return ok({"card": dec})


def _int_param(v, default: int, lo: int, hi: int) -> int:
    try:
        v = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


@app.errorhandler(404)
def not_found(_e):
    return fail("接口不存在", 404)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"YGOSearch 已启动：http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
