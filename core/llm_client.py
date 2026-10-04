# -*- coding: utf-8 -*-
"""LLM 客户端：自然语言 → DSL JSON。

约束（任务规格）：
- 配置走 config.json：{"llm": {"base_url": "...", "api_key": "...", "model": "..."}}
- OpenAI 兼容 /chat/completions 接口
- 输出必须是合法 DSL JSON → 过 validate() → 失败时把错误信息回喂 LLM 重试一次
- 再失败则明确告知用户「这句话我没能理解，换个说法试试」
- 系统提示词不硬编码卡片名单，词汇表运行时注入
"""
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

import llm_system_prompt as SP

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
PRESETS_PATH = ROOT / "config.presets.json"
LOCAL_URL_RE = re.compile(
    r"http://(127\.0\.0\.1|localhost)(:\d{1,5})?(/[^?#]*)?")

RETRY_PROMPT = (
    "你上一次的输出没有通过 DSL 校验。校验错误信息：\n{error}\n\n"
    "上一次输出：\n{raw}\n\n"
    "请根据错误信息修正，重新输出。只输出修正后的 DSL JSON 本身，"
    "不要任何解释、不要 markdown 代码块标记。"
)


class LLMConfigError(Exception):
    """config.json 缺失/不完整，message 面向用户可读。"""


def _local_base_url(value: str) -> str:
    if not isinstance(value, str) or not LOCAL_URL_RE.fullmatch(value):
        raise LLMConfigError("本地服务地址需使用 localhost 或 127.0.0.1 的 HTTP 地址")
    return value.rstrip("/")


def list_local_models(base_url: str, api_key: str = "") -> list[str]:
    """读取本机 OpenAI 兼容服务的 /models 列表，不跟随重定向。"""
    base = _local_base_url(base_url)
    if not isinstance(api_key, str):
        raise LLMConfigError("API Key 格式不正确")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        NoRedirect())
    req = urllib.request.Request(
        base + "/models",
        headers={"Authorization": f"Bearer {api_key.strip() or 'ollama'}"})
    try:
        with opener.open(req, timeout=5) as response:
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as e:
        raise LLMConfigError(f"本地服务返回 HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMConfigError(f"无法连接本地服务：{e}") from e
    if len(raw) > 1_000_000:
        raise LLMConfigError("本地模型列表过大")
    try:
        data = json.loads(raw)
        models = data["data"]
        names = sorted({item["id"] for item in models
                        if isinstance(item, dict) and isinstance(item.get("id"), str)})
    except (ValueError, KeyError, TypeError):
        raise LLMConfigError("本地服务没有返回 OpenAI 兼容的模型列表")
    return names


def load_config(config_path: Optional[Path] = None) -> Dict:
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        raise LLMConfigError(
            "尚未找到 config.json。请在 AI 搜索页打开「API 配置」。")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise LLMConfigError(f"config.json 解析失败：{e}")
    llm = cfg.get("llm") or {}
    missing = [k for k in ("base_url", "api_key", "model") if not llm.get(k)]
    if missing:
        raise LLMConfigError(
            f"config.json 的 llm 节缺少字段：{', '.join(missing)}")
    return llm


def load_presets() -> list:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["providers"]


def config_status(config_path: Optional[Path] = None) -> Dict:
    path = Path(config_path) if config_path else CONFIG_PATH
    presets = load_presets()
    status = {"providers": presets, "configured": False, "provider": "deepseek",
              "model": "", "base_url": "", "has_key": False}
    if path.exists():
        try:
            llm = load_config(path)
        except LLMConfigError:
            return status
        provider = llm.get("provider") or next(
            (p["id"] for p in presets if p["base_url"] == llm["base_url"]
             and p["model"] == llm["model"]), "custom")
        status.update(configured=True, provider=provider,
                      model=llm["model"], base_url=llm["base_url"],
                      has_key=bool(llm["api_key"]))
    return status


def save_config(data: Dict, config_path: Optional[Path] = None) -> Dict:
    path = Path(config_path) if config_path else CONFIG_PATH
    presets = {p["id"]: p for p in load_presets()}
    provider = data.get("provider")
    if provider not in presets:
        raise LLMConfigError("请选择有效的 AI 服务")
    preset = presets[provider]
    key = data.get("api_key", "")
    if not isinstance(key, str):
        raise LLMConfigError("API Key 格式不正确")
    key = key.strip()
    if not key and path.exists():
        try:
            old = load_config(path)
            if old.get("provider") == provider:
                key = old["api_key"]
        except LLMConfigError:
            pass
    if preset["needs_key"] and not key:
        raise LLMConfigError("请填写 API Key")
    if provider == "local":
        model = data.get("model", "")
        base_url = data.get("base_url", preset["base_url"])
        if not isinstance(model, str) or not model.strip():
            raise LLMConfigError("请填写本地模型名称")
        base_url = _local_base_url(base_url)
        model = model.strip()
        key = key or "ollama"
    else:
        model, base_url = preset["model"], preset["base_url"]
    llm = {"provider": provider, "base_url": base_url,
           "api_key": key, "model": model}
    content = json.dumps({"llm": llm}, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return config_status(path)


def _strip_code_fence(text: str) -> str:
    """剥离 LLM 可能加的 markdown 代码块标记。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        return m.group(1).strip()
    # 有些模型只给半个围栏
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _extract_json(text: str) -> str:
    """兜底：从混杂输出里截取最外层 JSON 对象。"""
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


class LLMClient:
    def __init__(self, config_path: Optional[Path] = None,
                 timeout: int = 60, http=None):
        self.cfg = load_config(config_path)
        self.timeout = timeout
        self._http = http or self._post_http   # 便于测试注入 mock

        base = self.cfg["base_url"].rstrip("/")
        if not base.endswith("/chat/completions"):
            self.url = base + "/chat/completions"
        else:
            self.url = base

    # ---------- HTTP ----------
    def _post_http(self, url: str, headers: Dict[str, str],
                   body: bytes, timeout: int) -> Dict:
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except OSError:
                pass
            raise RuntimeError(f"LLM 接口返回 HTTP {e.code}：{detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RuntimeError(f"LLM 接口连接失败：{e}") from e

    def _chat(self, messages, temperature: float = 0.0) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cfg['api_key']}",
        }
        payload = {
            "model": self.cfg["model"],
            "messages": messages,
            "temperature": temperature,
        }
        resp = self._http(self.url, headers,
                          json.dumps(payload).encode("utf-8"), self.timeout)
        try:
            content = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"LLM 响应格式异常：{e}") from e
        if not isinstance(content, str):
            raise RuntimeError("LLM 响应 content 不是字符串")
        return content

    # ---------- 主流程 ----------
    def nl_to_dsl(self, user_text: str, vocab: Dict,
                  setnames: Dict[int, str]) -> Dict:
        """自然语言 → DSL。

        返回 {"ok": True, "dsl": {...}, "raw": str} 或
             {"ok": False, "message": "面向用户的可读错误"}。
        """
        system = SP.build_system_prompt(vocab)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user_text}]
        try:
            raw = self._chat(messages)
        except RuntimeError as e:
            return {"ok": False, "message": f"LLM 调用失败：{e}"}

        dsl, err = self._parse_and_validate(raw, setnames)
        if dsl is not None:
            return {"ok": True, "dsl": dsl, "raw": raw}

        # 第一次失败：把错误信息回喂，重试一次
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user",
                         "content": RETRY_PROMPT.format(error=err, raw=raw)})
        try:
            raw2 = self._chat(messages)
        except RuntimeError as e:
            return {"ok": False,
                    "message": f"LLM 调用失败（重试阶段）：{e}"}

        dsl2, err2 = self._parse_and_validate(raw2, setnames)
        if dsl2 is not None:
            return {"ok": True, "dsl": dsl2, "raw": raw2}

        # 两次都失败：明确告知用户
        return {"ok": False, "message": "这句话我没能理解，换个说法试试",
                "debug_error": err2}

    def _parse_and_validate(self, raw: str,
                            setnames: Dict[int, str]):
        """解析并校验 LLM 输出。返回 (dsl, None) 或 (None, 错误信息)。"""
        import dsl as D
        text = _strip_code_fence(raw)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            frag = _extract_json(text)
            try:
                obj = json.loads(frag)
            except json.JSONDecodeError as e:
                return None, f"输出不是合法 JSON：{e}（原始输出前 200 字：{text[:200]}）"
        try:
            if isinstance(obj, dict) and obj.get("error"):
                return None, "无法完整表达查询：" + str(obj["error"])[:300]
            D.normalize(obj, setnames)
        except D.DSLError as e:
            return None, str(e)
        except Exception as e:   # 防御：奇怪结构导致的意外异常
            return None, f"DSL 结构无法解析：{e}"
        # Engine.search owns normalization. Return the wire-format DSL so it
        # can validate and compile the same contract used by manual search.
        return obj, None


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    from strings_conf import parse_strings_conf
    from vocab import build_vocab
    setnames, _ = parse_strings_conf()
    client = LLMClient()
    r = client.nl_to_dsl("不取对象破坏卡片的仪式怪兽",
                         build_vocab(setnames), setnames)
    print(json.dumps(r, ensure_ascii=False, indent=2))
