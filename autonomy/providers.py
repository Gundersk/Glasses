# -*- coding: utf-8 -*-
"""Провайдеры: единый OpenAI-совместимый chat-клиент (локалка, OpenRouter, Gemini, Kimi).
Локальная модель: длинный таймаут, НОЛЬ ретраев (повтор добивает очередь).
Облако: 2 ретрая с экспоненциальным backoff, уважение 429/Retry-After."""
import json
import random
import time
from pathlib import Path

import requests

from . import env

# Strata выдаёт новый порт при каждом старте; ищем живой сервер сами.
DISCOVERY_DIRS = [
    Path(r"C:\Users\Yurgirus\AppData\Local\Strata\procs"),
]
DESKTOP_LOGS = Path(r"C:\Users\Yurgirus\AppData\Local\Strata\logs")
NATIVE_INSTANCES = Path(r"C:\Users\Yurgirus\.strata\data\native-instances")
_discovered = {"url": None, "ts": 0.0}


class ProviderError(Exception):
    def __init__(self, msg, kind="provider", cost_usd=0.0, in_tok=0, out_tok=0):
        super().__init__(msg)
        # provider | timeout | rate | budget | empty | empty_reasoning | truncated
        # | truncated_reasoning | stream | stream_incomplete
        self.kind = kind
        # Вызов мог стоить денег, даже если ответ оказался непригодным.
        self.cost_usd = cost_usd
        # Оплаченные токены неудачного вызова, если провайдер их вернул.
        self.in_tok = in_tok
        self.out_tok = out_tok


class Result:
    def __init__(self, text, provider, model, in_tok, out_tok, cost_usd, latency,
                 finish="stop", reasoning_tok=0):
        self.text = text
        self.provider = provider
        self.model = model
        self.in_tok = in_tok
        self.out_tok = out_tok
        self.cost_usd = cost_usd
        self.latency = latency
        self.finish = finish  # stop | length | ...
        self.reasoning_tok = reasoning_tok

    def digest(self):
        return str(hash(self.text))[:8] if self.text else "empty"


def _usage_cost(usage, in_tok, out_tok, pcfg):
    """Стоимость вызова: usage.cost, если это валидное число >= 0, иначе оценка.

    usage.cost приходит от провайдера (OpenRouter) и учитывает reasoning; оценка
    по прайсу — только запасной путь. Это число для бюджета ночи, а не гарантия
    абсолютного счёта: расхождение с биллингом провайдера возможно.
    """
    raw = (usage or {}).get("cost")
    try:
        val = float(raw)
    except (TypeError, ValueError):
        val = None
    # NaN/inf и отрицательные значения не считаем валидной стоимостью.
    if val is not None and val >= 0 and val != float("inf"):
        return val
    return (in_tok * pcfg.get("price_in_usd_per_mtok", 0.0)
            + out_tok * pcfg.get("price_out_usd_per_mtok", 0.0)) / 1e6


def _candidate_endpoints():
    """(url, api_key|None) — откуда может отвечать живой сервер Strata."""
    import re
    cfg_key = env.get("LOCAL_LLM_API_KEY", "")
    cands = []
    # 1. Шлюз приложения: порт в свежем desktop-логе ("strata host · http://127.0.0.1:PORT").
    if DESKTOP_LOGS.exists():
        try:
            logs = sorted(DESKTOP_LOGS.glob("desktop-*.log"), key=lambda p: p.stat().st_mtime)
            for fp in reversed(logs[-3:]):
                m = re.findall(r"strata host\s*·\s*http://127\.0\.0\.1:(\d+)",
                               fp.read_text(encoding="utf-8", errors="ignore"))
                if m:
                    cands.append((f"http://127.0.0.1:{m[-1]}/v1", cfg_key))
                    break
        except Exception:
            pass
    # 2. Движок: порт из procs + api_key из native-instances.
    inst_key = None
    if NATIVE_INSTANCES.exists():
        try:
            for fp in sorted(NATIVE_INSTANCES.glob("*.json"),
                             key=lambda p: p.stat().st_mtime, reverse=True):
                d = json.loads(fp.read_text(encoding="utf-8"))
                if d.get("api_key"):
                    inst_key = d["api_key"]
                    break
        except Exception:
            inst_key = None
    ports = []
    for d in DISCOVERY_DIRS:
        if not d.exists():
            continue
        for fp in d.glob("*.json"):
            try:
                info = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if info.get("role") != "server":
                continue
            cmd = info.get("cmd", [])
            for i, a in enumerate(cmd):
                if a == "--port" and i + 1 < len(cmd):
                    try:
                        ports.append(int(cmd[i + 1]))
                    except ValueError:
                        pass
    for port in ports:
        for key in [k for k in (cfg_key, inst_key) if k]:
            cands.append((f"http://127.0.0.1:{port}/v1", key))
    seen, out = set(), []
    for u, k in cands:
        if (u, k) not in seen:
            seen.add((u, k))
            out.append((u, k))
    return out


def discover_local(timeout=3.0, ttl=60.0):
    """Найти живой локальный сервер Strata (порт и ключ меняются при рестарте).
    Возвращает (base_url, api_key) или (None, None). Кэш на ttl секунд."""
    now = time.time()
    if _discovered["url"] and now - _discovered["ts"] < ttl:
        url, key = _discovered["url"], _discovered.get("key", "")
        if _probe(url, key, timeout):
            return url, key
    for url, key in _candidate_endpoints():
        if _probe(url, key, timeout):
            _discovered["url"], _discovered["key"], _discovered["ts"] = url, key, now
            return url, key
    _discovered["url"] = None
    return None, None


def _probe(base_url, api_key, timeout):
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = requests.get(base_url.rstrip("/") + "/models", headers=headers, timeout=timeout)
        return r.status_code < 400
    except requests.exceptions.RequestException:
        return False


def health(name, pcfg):
    """Быстрая проверка живости. Для локалки — ГЛУБОКАЯ проба: gateway может
    отвечать 200 на /models, пока engine грузит модель и отдаёт 502 на чат."""
    if pcfg.get("base_url_env") == "LOCAL_LLM_BASE_URL":
        url, key = discover_local(timeout=3.0)
        if not url:
            return False
        model = env.get("LOCAL_LLM_MODEL", "default")
        try:
            r = requests.post(url.rstrip("/") + "/chat/completions",
                              headers={"Authorization": f"Bearer {key}"} if key else {},
                              json={"model": model,
                                    "messages": [{"role": "user", "content": "ping"}],
                                    "max_tokens": 1, "enable_thinking": False},
                              timeout=25)
            return r.status_code == 200
        except requests.exceptions.RequestException:
            return False
    base_url, api_key, _ = _resolve(pcfg)
    return _probe(base_url, api_key, 5) if base_url else False


def _resolve(pcfg):
    base_url = env.get("LOCAL_LLM_BASE_URL") if "base_url_env" in pcfg and pcfg["base_url_env"] == "LOCAL_LLM_BASE_URL" else pcfg.get("base_url")
    if "base_url_env" in pcfg and pcfg["base_url_env"] != "LOCAL_LLM_BASE_URL":
        base_url = env.get(pcfg["base_url_env"], base_url)
    api_key = env.get(pcfg["api_key_env"], "") if "api_key_env" in pcfg else ""
    model = pcfg.get("model")
    if pcfg.get("model_env"):
        model = env.get(pcfg["model_env"], model)
    # Для локалки: авто-обнаружение актуальных порта и ключа важнее конфига.
    if pcfg.get("base_url_env") == "LOCAL_LLM_BASE_URL":
        found_url, found_key = discover_local()
        if found_url:
            base_url = found_url
            if found_key:
                api_key = found_key
    return base_url, api_key, model


def _chat_stream(name, pcfg, url, headers, payload, model):
    """SSE-стриминг: спасает от gateway-таймаута (~300 c) на длинной генерации —
    живой поток байтов шлюз не убивает. kind='stream' => шлюз стриминг не умеет."""
    t0 = time.time()
    p = dict(payload, stream=True, stream_options={"include_usage": True})
    read_to = pcfg.get("stream_idle_timeout_s", 180)
    for _attempt in range(2):
        try:
            r = requests.post(url, headers=headers, json=p,
                              timeout=(15, read_to), stream=True)
        except requests.exceptions.Timeout:
            raise ProviderError(f"{name}: stream: нет данных {read_to}s (движок занят/грузится)", "provider")
        except requests.exceptions.RequestException as e:
            raise ProviderError(f"{name}: stream: {e}", "provider")
        if r.status_code in (400, 404, 405, 406, 415):
            # возможно, не знает stream_options — повторим без него
            if "stream_options" in p:
                p.pop("stream_options", None)
                continue
            raise ProviderError(f"{name}: stream не поддерживается (HTTP {r.status_code})", "stream")
        break
    if r.status_code >= 500:
        raise ProviderError(f"{name}: HTTP {r.status_code}", "provider")
    if r.status_code >= 400:
        raise ProviderError(f"{name}: HTTP {r.status_code}: {r.text[:200]}", "provider")
    content, finish, usage, done = [], None, {}, False
    r.encoding = "utf-8"
    try:
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            body = raw[5:].strip()
            if body == "[DONE]":
                done = True
                break
            try:
                chunk = json.loads(body)
            except json.JSONDecodeError:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                # reasoning_content — не результат: финальную выдачу даёт только content.
                if d.get("content"):
                    content.append(d["content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    except requests.exceptions.ChunkedEncodingError as e:
        raise ProviderError(f"{name}: stream оборвался: {e}", "provider")
    text = "".join(content)
    details = (usage or {}).get("completion_tokens_details") or {}
    reasoning_tok = int(details.get("reasoning_tokens") or 0)
    in_tok = usage.get("prompt_tokens") or max(1, len(json.dumps(payload.get("messages", ""), ensure_ascii=False)) // 4)
    out_tok = usage.get("completion_tokens") or max(1, len(text) // 4)
    cost = _usage_cost(usage, in_tok, out_tok, pcfg)
    mt = payload.get("max_tokens")
    if (finish or "") == "length":
        raise ProviderError(f"{name}: stream обрезан по max_tokens={mt} "
                            f"(reasoning={reasoning_tok})", "truncated", cost,
                            in_tok, out_tok)
    if not text.strip():
        kind = "empty_reasoning" if reasoning_tok else "empty"
        raise ProviderError(f"{name}: stream вернул пустоту "
                            f"(reasoning={reasoning_tok})", kind, cost, in_tok, out_tok)
    # Оборванный поток без terminal finish/[DONE] — не успех, даже если текст есть.
    if not done and not finish:
        raise ProviderError(f"{name}: stream оборван без terminal finish "
                            f"(reasoning={reasoning_tok})", "stream_incomplete",
                            cost, in_tok, out_tok)
    return Result(text, name, model, in_tok, out_tok, cost, time.time() - t0,
                  finish or "stop", reasoning_tok)


def chat(name, pcfg, messages, max_tokens=4096, temperature=0.3):
    if pcfg.get("kind") == "browser-session":
        from . import browser_gateway
        return browser_gateway.chat(name, pcfg, messages, max_tokens, temperature)
    if pcfg.get("kind") == "opencode-chatgpt":
        from . import opencode_provider
        return opencode_provider.chat(name, pcfg, messages, max_tokens)
    base_url, api_key, model = _resolve(pcfg)
    if not base_url or not model:
        raise ProviderError(f"provider {name}: не задан base_url/model", "config")
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": pcfg.get("temperature", temperature),  # override провайдера (kimi=1)
        "stream": False,
    }
    # Модели с обязательным reasoning (deepseek1017, glm, qwen) иначе съедают весь
    # max_tokens на размышления и возвращают пустой content. Проверено 11.11.2026.
    if pcfg.get("reasoning") is not None:
        payload["reasoning"] = pcfg["reasoning"]
    timeout = pcfg.get("timeout_s", 300)
    retries = pcfg.get("retries", 0)
    attempts = retries + 1

    if pcfg.get("stream"):
        try:
            return _chat_stream(name, pcfg, url, headers, payload, model)
        except ProviderError as e:
            if e.kind != "stream":
                raise  # 502/обрыв — наружу, grace-слой сам решит
            # шлюз не умеет SSE — тихо переходим на обычный запрос

    last_err = None
    for i in range(attempts):
        t0 = time.time()
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except requests.exceptions.Timeout:
            last_err = ProviderError(f"{name}: timeout после {timeout}s", "timeout")
            # Для локалки (retries=0) сюда не доходит; для облака — retry.
            if i < attempts - 1:
                time.sleep(_backoff(i, r=None))
                continue
            raise last_err
        except requests.exceptions.RequestException as e:
            last_err = ProviderError(f"{name}: {e}", "provider")
            if i < attempts - 1:
                time.sleep(_backoff(i, r=None))
                continue
            raise last_err

        if r.status_code == 429:
            wait = _retry_after(r) or _backoff(i, r)
            if i < attempts - 1:
                time.sleep(wait)
                continue
            raise ProviderError(f"{name}: 429 rate limit (после {attempts} попыток)", "rate")
        if r.status_code >= 500:
            last_err = ProviderError(f"{name}: HTTP {r.status_code}", "provider")
            if i < attempts - 1:
                time.sleep(_backoff(i, r))
                continue
            raise last_err
        if r.status_code >= 400:
            raise ProviderError(f"{name}: HTTP {r.status_code}: {r.text[:300]}", "provider")

        try:
            data = r.json()
            choice = data["choices"][0]
            message = choice["message"]
            # reasoning_content — не результат: финальную выдачу даёт только content.
            text = message.get("content") or ""
            finish = choice.get("finish_reason", "stop")
        except (ValueError, KeyError, IndexError) as e:
            raise ProviderError(f"{name}: плохой ответ: {e}", "provider")

        usage = data.get("usage", {}) or {}
        in_tok = usage.get("prompt_tokens") or 0
        out_tok = usage.get("completion_tokens") or 0
        details = usage.get("completion_tokens_details") or {}
        reasoning_tok = int(details.get("reasoning_tokens") or 0)
        cost = _usage_cost(usage, in_tok, out_tok, pcfg)

        # Ответ, из которого нельзя взять результат, — не успех. Раньше такой вызов
        # считался ok:out=0 и сжигал итерацию задачи (ночь 11.11.2026).
        burned = reasoning_tok >= max(1, int(0.9 * max_tokens))
        if not text.strip():
            kind = "empty_reasoning" if (burned or reasoning_tok) else "empty"
            raise ProviderError(
                f"{name}: пустой ответ (finish={finish}, out={out_tok}, "
                f"reasoning={reasoning_tok} из max_tokens={max_tokens})", kind, cost,
                in_tok, out_tok)
        if finish == "length":
            kind = "truncated_reasoning" if (burned or reasoning_tok) else "truncated"
            raise ProviderError(
                f"{name}: обрезано лимитом max_tokens={max_tokens} "
                f"(finish=length, out={out_tok}, reasoning={reasoning_tok})", kind, cost,
                in_tok, out_tok)

        return Result(text, name, model, in_tok, out_tok, cost, time.time() - t0,
                      finish, reasoning_tok)

    raise last_err or ProviderError(f"{name}: исчерпаны попытки", "provider")


def _backoff(i, r=None):
    base = 2 ** i
    return base + random.uniform(0, base / 2)


def _retry_after(r):
    v = r.headers.get("Retry-After") if r else None
    try:
        return min(float(v), 60) if v else None
    except (TypeError, ValueError):
        return None
