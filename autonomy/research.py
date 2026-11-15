# -*- coding: utf-8 -*-
"""Проверка фактов: TinyFish MCP search/fetch_content + локальный кэш.
Формат: claim / source_url / quote / accessed / verdict. Нет цитаты — нет факта."""
import hashlib
import json
import re
import time
from pathlib import Path

import requests

from . import env, paths
from .source_selection import select_sources


def _page_text(item):
    for key in ('text', 'content', 'markdown'):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ''


def _valid_page(item, allowed):
    if not isinstance(item, dict) or not isinstance(item.get('url'), str) or item['url'] not in allowed:
        return False
    if item.get('error') or item.get('isError') or item.get('is_error'):
        return False
    for status in (item.get('status'), item.get('status_code')):
        if status is None:
            continue
        if type(status) is int:
            if status >= 400:
                return False
        elif isinstance(status, str):
            if (status.lower() in {'error', 'failed', 'failure', 'blocked', 'bot_blocked',
                                   'rate_limited', 'unauthorized', 'forbidden'}
                    or status.isdigit() and int(status) >= 400):
                return False
        else:
            return False
    text = _page_text(item)
    if re.search(r'cf-please-wait|captcha|checking your browser|just a moment\.\.\.', text, re.I):
        return False
    return bool(text)


def _safe_errors(errors):
    """Codes only: never persist URLs, response bodies, arbitrary messages or secrets."""
    codes = []
    for item in errors if isinstance(errors, list) else []:
        code = item.get('error') if isinstance(item, dict) else None
        if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', code):
            codes.append(code)
        else:
            codes.append('unclassified_error')
    return codes[:10]


class TinyFish:
    def __init__(self, cfg, log):
        self.url = cfg["research"]["tinyfish_mcp_url"]
        self.key = env.get(cfg["research"]["tinyfish_key_env"], "")
        self.log = log
        self.cache_dir = paths.resolve(cfg["research"]["cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = None

    # --- MCP streamable HTTP: initialize -> tools/call -------------------
    def _rpc(self, method, params, call_id):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.key}",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        body = {"jsonrpc": "2.0", "id": call_id, "method": method, "params": params}
        r = requests.post(self.url, headers=headers, json=body, timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"tinyfish {method}: HTTP {r.status_code} (body redacted)")
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        return self._parse(r)

    @staticmethod
    def _parse(r):
        """JSON или SSE (data: {...}) — оба варианта ответа MCP."""
        text = r.text
        if "data:" in text and not text.lstrip().startswith("{"):
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload:
                        return json.loads(payload)
            raise RuntimeError("SSE без data-строк")
        return json.loads(text)

    def _ensure_init(self):
        if self.session_id is None:
            self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "night-runner", "version": "0.1"},
            }, 0)
            try:
                self._rpc("notifications/initialized", {}, None)
            except Exception:
                pass

    def _tool(self, name, args):
        self._ensure_init()
        resp = self._rpc("tools/call", {"name": name, "arguments": args}, 1)
        if not isinstance(resp, dict) or "error" in resp:
            raise RuntimeError(f"tinyfish {name}: MCP RPC error (details redacted)")
        result = resp.get("result", {})
        if not isinstance(result, dict) or result.get("isError"):
            raise RuntimeError(f"tinyfish {name}: MCP tool error (details redacted)")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        blocks = result.get("content", [])
        if not isinstance(blocks, list):
            raise RuntimeError(f"tinyfish {name}: invalid MCP content schema")
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            data = json.loads(joined)
        except json.JSONDecodeError:
            raise RuntimeError(f"tinyfish {name}: non-JSON tool response (body redacted)")
        if not isinstance(data, dict):
            raise RuntimeError(f"tinyfish {name}: unexpected JSON schema")
        return data

    # --- публичные методы с кэшем ----------------------------------------
    def _cache_path(self, kind, key):
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{kind}-{h}.json"

    def search(self, query, purpose, domain_type=None, max_age_days=None):
        cp = self._cache_path("search", query + "|" + (domain_type or ""))
        age_days = 7 if max_age_days is None else max_age_days
        if cp.exists() and time.time() - cp.stat().st_mtime < age_days * 86400:
            self.log.log(f"tinyfish search cache hit: {query[:60]}")
            return json.loads(cp.read_text(encoding="utf-8"))
        args = {"query": query, "purpose": purpose}
        if domain_type:
            args["domain_type"] = domain_type
        out = self._tool("search", args)
        cp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out

    def fetch(self, urls, purpose, fresh=False):
        if isinstance(urls, str):
            urls = [urls]
        results, errors, uncached, invalid_results = [], [], [], 0
        for u in urls:
            cp = self._cache_path("page", u)
            if not fresh and cp.exists() and time.time() - cp.stat().st_mtime < 3 * 86400:
                item = json.loads(cp.read_text(encoding="utf-8"))
                if _valid_page(item, {u}):
                    results.append(item)
                else:
                    uncached.append(u)
            else:
                uncached.append(u)
        if uncached:
            out = self._tool("fetch_content", {"urls": uncached, "format": "markdown",
                                               "purpose": purpose})
            if not isinstance(out.get('results'), list) or not isinstance(out.get('errors', []), list):
                raise RuntimeError('tinyfish fetch_content: invalid results/errors schema')
            for item in out['results']:
                if _valid_page(item, set(uncached)):
                    results.append(item)
                    self._cache_path("page", item["url"]).write_text(
                        json.dumps(item, ensure_ascii=False), encoding="utf-8")
                else:
                    invalid_results += 1  # Never return/cache an invalid or unrequested page as content.
            errors = out.get("errors", [])
        return {"results": results, "errors": errors, "invalid_results": invalid_results}


def make_claim(claim, url, quote, note=""):
    """Каноническая запись факта. quote ДОЛЖЕН быть точной цитатой из fetched-текста."""
    return {
        "claim": claim,
        "source_url": url,
        "quote": quote,
        "accessed": time.strftime("%Y-%m-%d"),
        "verdict": "supported" if quote else "unverified",
        "note": note,
    }


def quote_in_page(claim_obj, page_text):
    """Скриптовая проверка: цитата реально есть на странице (нормализация пробелов)."""
    norm = lambda s: " ".join(str(s).split()).lower()
    return norm(claim_obj["quote"]) in norm(page_text)


class _PrintLog:
    def log(self, msg):
        print(msg, flush=True)


def _slug(text, limit=40):
    keep = [c.lower() if c.isalnum() else "-" for c in str(text)]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:limit] or "query"


def refresh(query, purpose, max_pages=2, dry_run=False, out=None, fresh=False, allow_unavailable=False):
    """Найти внешние ориентиры и сложить их в заметку.

    Система НЕ извлекает числа сама: она сохраняет ссылки и фрагменты, чтобы
    число попало в docs/benchmarks.md только после проверки цитаты. Иначе
    получится выдуманный ориентир — тот же дефект, что 12.11.2026.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 5:
        raise ValueError("max_pages must be an integer in 1..5")
    note_dir = paths.resolve("docs/research/notes")
    stamp = time.strftime("%Y-%m-%d")
    out_path = paths.resolve(out) if out else note_dir / f"{stamp}-{_slug(query)}.md"
    if not paths.inside_project(str(out_path)) or out_path.suffix != ".md":
        raise ValueError("заметка должна быть .md внутри проекта")
    if dry_run:
        print(f"[dry-run] запрос: {query}\n[dry-run] заметка была бы: {out_path}")
        return out_path

    import yaml
    cfg = yaml.safe_load((paths.AUTONOMY_DIR / "config.yaml").read_text(encoding="utf-8"))
    if out and out_path.parent.parent == paths.resolve("autonomy/workspace/requests"):
        # subprocess не наследует переназначенные Python globals родителя.
        cfg["research"]["cache_dir"] = str(out_path.parent / "run/cache/web")
    tf = TinyFish(cfg, _PrintLog())
    found = tf.search(query, purpose=purpose, max_age_days=0 if fresh else None)
    if not isinstance(found, dict):
        raise RuntimeError('tinyfish search: invalid results schema')
    items = found.get('results', found.get('items'))
    if not isinstance(items, list):
        raise RuntimeError('tinyfish search: invalid results schema')
    manifest = select_sources(query, items, max_pages)
    urls = manifest['selected']
    pages = tf.fetch(urls, purpose=purpose, fresh=fresh) if urls else {"results": []}
    if not isinstance(pages, dict) or not isinstance(pages.get('results'), list) or not isinstance(pages.get('errors', []), list):
        raise RuntimeError('tinyfish fetch_content: invalid results/errors schema')
    if allow_unavailable and (pages.get('invalid_results', 0) != 0
                             or any(not _valid_page(p, set(urls)) for p in pages['results'])):
        raise RuntimeError('tinyfish fetch_content: invalid page or challenge')
    pages['results'] = [p for p in pages.get('results', []) if _valid_page(p, set(urls))]
    sources = [{"url": p["url"], "content": _page_text(p)[:30000]}
               for p in pages.get("results", [])]
    missing = [url for url in urls if url not in {p['url'] for p in sources}]
    codes = _safe_errors(pages.get('errors', []))
    if allow_unavailable:
        from .source_outcomes import RESOURCE_ERRORS
        if any(code not in RESOURCE_ERRORS for code in codes):
            raise RuntimeError('tinyfish fetch_content: fatal error code')
        if not urls and not items:
            codes = ['no_results']
        elif (not urls or len(codes) != len(missing)):
            raise RuntimeError('tinyfish fetch_content: unexplained missing page or schema')
    if not sources:
        reason = ','.join(codes) if codes else ('no_selected_urls' if not urls else 'no_valid_page_or_schema')
        if not allow_unavailable:
            raise RuntimeError("нет прочитанных страниц; поиск не считается выполненным; причины=" + reason)

    lines = [f"# Поиск: {query}", "", f"Дата: {stamp}", f"Зачем: {purpose}", "",
             "Это источник, не измерение. Числа переносить в `docs/benchmarks.md`",
             "только после проверки цитаты функцией `quote_in_page`.",
             "Подсказки первоисточника — эвристика, не подтверждение первичности или достоверности.", "",
             "## Найденные ссылки"]
    for i, item in enumerate(items[:10], 1):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("name") or "(без названия)"
        lines.append(f"{i}. {title} — {item.get('url', '')}")
        snippet = str(item.get("snippet") or item.get("description") or "")[:300]
        if snippet:
            lines.append(f"   > {snippet}")
    lines += ["", "## Фрагменты страниц"]
    if not sources:
        lines += ['', 'SOURCE UNAVAILABLE - not evidence']
    for page in pages.get("results", [])[:max_pages]:
        url = page.get("url", "")
        text = _page_text(page)[:1500]
        lines += ["", f"### {url}", "", text or "(пусто)"]
    document = {"query": query,
        "accessed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "fresh_requested": fresh,
        "sources": sources, "selection_manifest": manifest,
        "limitation": "Fetched content, not a verified scientific conclusion; primary-source hints are unverified heuristics"}
    if allow_unavailable:
        document.update(schema_version=2, collection_status='available' if sources else 'unavailable',
                        unavailable_urls=missing, error_codes=codes,
                        search_results_count=len(items), fetch_attempted=bool(urls))
        from .source_outcomes import inspect_document
        inspect_document(document)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(str(out_path) + ".json").write_text(json.dumps(document,
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"заметка: {out_path} (ссылок: {len(urls)})")
    return out_path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Поиск внешних ориентиров (TinyFish + кэш)")
    ap.add_argument("query")
    ap.add_argument("--purpose", default="найти внешний ориентир для метрики проекта")
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--allow-unavailable", action="store_true")
    a = ap.parse_args(argv)
    refresh(a.query, a.purpose, max_pages=a.max_pages, dry_run=a.dry_run, out=a.out, fresh=a.fresh,
            allow_unavailable=a.allow_unavailable)
    return 0


def brief(query, max_pages=1, chars=700, purpose="проверка внешнего факта"):
    """Компактная выжимка для модели: ссылки, сниппеты, фрагменты.

    Возвращает текст (не числа!). Заметка со ссылками сохраняется в
    docs/research/notes/, чтобы у любого утверждения был адрес. Числа попадают
    в docs/benchmarks.md только после проверки цитаты.
    """
    import yaml
    cfg = yaml.safe_load((paths.AUTONOMY_DIR / "config.yaml").read_text(encoding="utf-8"))
    isolated = paths.WORKSPACE.parent.parent == paths.resolve("autonomy/workspace/requests")
    if isolated:
        cfg["research"]["cache_dir"] = str(paths.CACHE_DIR / "web")
    tf = TinyFish(cfg, _PrintLog())
    found = tf.search(query, purpose=purpose)
    items = [i for i in (found.get("results") or found.get("items") or [])
             if isinstance(i, dict)]
    lines = [f"ЗАПРОС: {query}"]
    for i, it in enumerate(items[:6], 1):
        title = it.get("title") or it.get("name") or "(без названия)"
        lines.append(f"{i}. {title} — {it.get('url', '')}")
        snippet = str(it.get("snippet") or it.get("description") or "")[:220]
        if snippet:
            lines.append(f"   > {snippet}")
    urls = [it.get("url") for it in items if it.get("url")][:max_pages]
    if urls:
        pages = tf.fetch(urls, purpose=purpose)
        for page in pages.get("results", [])[:max_pages]:
            url = page.get("url", "")
            text = _page_text(page)[:chars]
            lines.append(f"### {url}\n{text or '(пусто)'}")
    body = "\n".join(lines)[:4000]

    note_dir = paths.WORKSPACE / "research" if isolated else paths.resolve("docs/research/notes")
    note_dir.mkdir(parents=True, exist_ok=True)
    note = note_dir / f"{time.strftime('%Y-%m-%d')}-{_slug(query)}.md"
    note.write_text(
        f"# Поиск: {query}\n\nДата: {time.strftime('%Y-%m-%d')}\nЗачем: {purpose}\n\n"
        "Источник, не измерение. Числа — только после проверки цитаты.\n\n" + body + "\n",
        encoding="utf-8")
    return body


if __name__ == "__main__":
    raise SystemExit(main())
