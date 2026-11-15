"""Слой 2: проверка, что страница субтитров реально отдаёт меняющийся русский текст.

Берёт N проб страницы через urllib (без JS!). Текст субтитров - содержимое элементов
с CSS-классом, содержащим «subtitle» (outermost); если таких нет - весь видимый текст <body>
(в detail указано, какой вариант сработал). Если ответ text/event-stream - читает тело
потоком и считает кадры `data:`.

ОГРАНИЧЕНИЕ: это серверный HTML. Если страница обновляется JS-скриптом, urllib этого
не увидит (текст не изменится -> FAIL). Для таких страниц нужен слой 3 (скриншоты + vision).

CLI: python check_dom.py --url http://127.0.0.1:8765/ --samples 8 --interval 0.5 --out dom_checks.json
Код выхода 0 при pass.
"""
import argparse
import datetime
import json
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
        "source", "track", "wbr"}
BLOCK = {"div", "p", "li", "br", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}
SKIP = {"script", "style", "noscript", "template", "head", "title"}


class Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.sub_chunks = []   # список текстов outermost-элементов subtitle
        self._cap_depth = None
        self._cap_buf = None
        self.body_buf = []
        self.in_body = False
        self.skip_depth = 0
        self.has_body_tag = False

    def handle_starttag(self, tag, attrs):
        cls = ""
        for k, v in attrs:
            if k == "class" and v:
                cls = v
        if tag in BLOCK:
            if self._cap_buf is not None:
                self._cap_buf.append("\n")
            self.body_buf.append("\n")
        if tag in VOID:
            return
        self.stack.append(tag)
        if tag == "body":
            self.in_body = True
            self.has_body_tag = True
        if tag in SKIP:
            self.skip_depth += 1
        if self._cap_buf is None and any("subtitle" in t.lower() for t in cls.split()):
            self._cap_buf = []
            self._cap_depth = len(self.stack)

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK:
            if self._cap_buf is not None:
                self._cap_buf.append("\n")
            self.body_buf.append("\n")

    def handle_endtag(self, tag):
        if tag in VOID or tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            if top in SKIP:
                self.skip_depth = max(0, self.skip_depth - 1)
            if self._cap_buf is not None and len(self.stack) < self._cap_depth:
                self.sub_chunks.append("".join(self._cap_buf))
                self._cap_buf = None
                self._cap_depth = None
            if top == "body":
                self.in_body = False
            if top == tag:
                break
        if tag in BLOCK:
            self.body_buf.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self._cap_buf is not None:
            self._cap_buf.append(data)
        if self.in_body or not self.has_body_tag:
            self.body_buf.append(data)

    def close(self):
        super().close()
        if self._cap_buf is not None:
            self.sub_chunks.append("".join(self._cap_buf))
            self._cap_buf = None


def to_lines(text):
    out = []
    for ln in text.split("\n"):
        ln = " ".join(ln.split())
        if ln:
            out.append(ln)
    return out


def extract_text(html):
    """Возвращает (lines, selector_description)."""
    p = Extractor()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 - битый HTML: берём что успели
        pass
    sub_lines = []
    for chunk in p.sub_chunks:
        sub_lines.extend(to_lines(chunk))
    if p.sub_chunks and sub_lines:
        return sub_lines, "class*=subtitle"
    if p.sub_chunks:
        return [], "class*=subtitle (элементы найдены, но пустые)"
    return to_lines("".join(p.body_buf)), "fallback: visible text of <body>"


def classify_error(e):
    r = getattr(e, "reason", e)
    if isinstance(e, urllib.error.HTTPError):
        return f"http_{e.code}"
    if isinstance(r, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(r, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(r, ConnectionResetError):
        return "connection_reset"
    return f"unreachable:{type(r).__name__}"


def make_opener():
    # игнорируем системные прокси: проверяем именно локальный сервер
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sse_text(payload):
    payload = payload.strip()
    try:
        obj = json.loads(payload)
        if isinstance(obj, dict):
            for k in ("text", "subtitle", "line", "final", "partial"):
                if isinstance(obj.get(k), str):
                    return obj[k]
        if isinstance(obj, str):
            return obj
    except Exception:  # noqa: BLE001
        pass
    return payload


def read_sse(resp, duration_s, t0):
    frames = []
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline and len(frames) < 500:
        try:
            line = resp.readline()
        except (socket.timeout, TimeoutError):
            continue
        except Exception:  # noqa: BLE001
            break
        if not line:
            break
        s = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if s.startswith("data:"):
            frames.append({"t": round(time.monotonic() - t0, 3), "text": sse_text(s[5:])})
    return frames


def run(url, samples, interval, timeout=5.0):
    checks = []

    def add(name, ok, expected, actual, detail=""):
        checks.append({"name": name, "ok": bool(ok), "expected": expected, "actual": actual, "detail": detail})

    res = {"layer": 2, "url": url, "pass": False, "mode": None, "selector": None, "samples": [],
           "distinct_texts": 0, "checks": checks, "reason": None,
           "created": datetime.datetime.now().astimezone().isoformat()}
    opener = make_opener()
    t0 = time.monotonic()
    texts = []
    statuses = []
    for i in range(samples):
        try:
            resp = opener.open(urllib.request.Request(url, headers={"Accept": "text/html,*/*"}), timeout=timeout)
        except Exception as e:  # noqa: BLE001
            reason = classify_error(e)
            res["reason"] = reason
            add(reason, False, "server responds", reason, str(e)[:200])
            add("http_200", False, 200, reason)
            return finish(res)
        status = resp.status
        statuses.append(status)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in ctype:
            res["mode"] = "sse"
            frames = read_sse(resp, samples * interval + 1.0, t0)
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            res["samples"] = frames
            res["selector"] = "SSE data: frames"
            texts = [f["text"] for f in frames]
            add("http_200", status == 200, 200, status)
            add("sse_frames_ge_2", len(frames) >= 2, ">=2", len(frames))
            break
        try:
            body = resp.read(2_000_000)
            charset = resp.headers.get_content_charset() or "utf-8"
            html = body.decode(charset, errors="replace")
        except Exception as e:  # noqa: BLE001
            reason = classify_error(e)
            res["reason"] = reason
            add(reason, False, "readable body", reason, str(e)[:200])
            return finish(res)
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        res["mode"] = "html"
        lines, selector = extract_text(html)
        res["selector"] = selector
        text = "\n".join(lines)
        res["samples"].append({"t": round(time.monotonic() - t0, 3), "text": text})
        texts.append(text)
        if i < samples - 1:
            time.sleep(interval)
    if res["mode"] == "html":
        add("http_200", bool(statuses) and all(s == 200 for s in statuses), 200, sorted(set(statuses)))

    non_empty = [t for t in texts if t.strip()]
    changes = sum(1 for a, b in zip(texts, texts[1:]) if a != b)
    distinct = len(set(non_empty))
    res["distinct_texts"] = distinct
    max_lines = max([len(to_lines(t)) for t in texts] or [0])
    add("text_changes_at_least_once", changes >= 1, ">=1 change", changes,
        f"селектор: {res['selector']}; режим: {res['mode']}")
    add("lines_ge_1", max_lines >= 1, ">=1 line", max_lines, f"селектор: {res['selector']}")
    cyr = sum(1 for t in non_empty if CYRILLIC.search(t))
    add("cyrillic_present", cyr >= 1, ">=1 sample with cyrillic", cyr)
    add("distinct_texts_ge_2", distinct >= 2, ">=2 distinct non-empty texts", distinct,
        "защита от одной и той же копии текста")
    return finish(res)


def finish(res):
    res["pass"] = bool(res["checks"]) and all(c["ok"] for c in res["checks"])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Слой 2: DOM-проверка страницы субтитров")
    ap.add_argument("--url", required=True)
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--out", required=True, help="путь к dom_checks.json")
    a = ap.parse_args(argv)
    try:
        res = run(a.url, max(1, a.samples), max(0.0, a.interval))
    except Exception as e:  # noqa: BLE001
        res = {"layer": 2, "url": a.url, "pass": False, "samples": [], "distinct_texts": 0,
               "checks": [{"name": "unexpected_error", "ok": False, "expected": "no error",
                           "actual": type(e).__name__, "detail": str(e)[:200]}],
               "created": datetime.datetime.now().astimezone().isoformat()}
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in res["checks"]:
        print(f"{c['name']:<30} {'ok' if c['ok'] else 'FAIL':<5} expected={c['expected']} actual={c['actual']}")
    print("DOM PASS" if res["pass"] else "DOM FAIL" + (f": {res['reason']}" if res.get("reason") else ""))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
