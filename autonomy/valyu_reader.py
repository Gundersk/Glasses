"""Bounded Valyu Contents reader; ledger is intentionally independent of WORKSPACE.

Stale in-flight entries and disabled circuits require manual operator inspection
and ledger repair. Reservations are never refunded, including on transport errors.
"""
import datetime as dt
import email.utils
import ipaddress
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import requests

from . import env, paths

_ENDPOINT = "https://api.valyu.ai/v1/contents"
_LIMIT = 256 * 1024
_RESERVE = 0.01
_COST_FIELDS = ('total_cost_dollars', 'total_deduction_dollars', 'cost')


class ValyuUnavailable(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _valid_url(url):
    if not isinstance(url, str) or len(url) > 2048 or not url.isascii():
        return False
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        return False
    try:
        u = urlsplit(url)
        host = u.hostname
        if (u.scheme not in ("http", "https") or not host or u.username or u.password
                or u.query or u.fragment or u.port is not None or u.netloc != host
                or host != host.lower() or host.endswith(".") or "." not in host):
            return False
        if not re.fullmatch(r"[a-z0-9.-]+", host) or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            return False
        if host.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
            return False
        try:
            ipaddress.ip_address(host)
            return False  # Avoid alternate numeric forms and private literal addresses.
        except ValueError:
            if all(c in "0123456789." for c in host):
                return False
        if re.search(r"(?i)(?:token|secret|password|api[_-]?key|signature|credential)", u.path):
            return False
        return not re.search(r"%(?![0-9A-Fa-f]{2})", u.path)
    except ValueError:
        return False


def _scope(scope_id):
    if not isinstance(scope_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", scope_id):
        raise ValyuUnavailable("invalid_scope")


def _connect(ledger_path):
    path = Path(ledger_path) if ledger_path is not None else paths.PROJECT_ROOT / "autonomy" / "workspace" / "valyu.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, scope TEXT NOT NULL, day TEXT NOT NULL, reserved INTEGER NOT NULL, cost REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS circuit (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, lease_until REAL, disabled INTEGER NOT NULL DEFAULT 0, cooldown REAL NOT NULL DEFAULT 0)")
    db.execute("INSERT OR IGNORE INTO circuit(id) VALUES(1)")
    return db


def usage(scope_id, ledger_path=None):
    _scope(scope_id)
    with closing(_connect(ledger_path)) as db:
        count, cents, cost, unknown, charge = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(reserved),0), COALESCE(SUM(cost),0), "
            "COALESCE(SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END),0), "
            "COALESCE(SUM(MAX(reserved / 100.0, COALESCE(cost,0))),0) FROM attempts WHERE scope=?", (scope_id,)
        ).fetchone()
    return {"counts": count, "reserved_usd": cents / 100, "reported_cost_usd": cost,
            "unknown_cost_attempts": unknown, "charge_usd": charge}


def _retry_after(value):
    try:
        seconds = float(value)
        if not math.isfinite(seconds):
            raise ValueError
    except (TypeError, ValueError):
        try:
            date = email.utils.parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=dt.timezone.utc)
            seconds = date.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            seconds = 3600
    return max(60, seconds)


def _reported(data):
    values = []
    for name in _COST_FIELDS:
        value = data.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            values.append(float(value))
    return max(values) if values else None


def _billing_invalid(data):
    values = [data[name] for name in _COST_FIELDS if name in data]
    if any(isinstance(value, bool) or not isinstance(value, (float, int))
           or not math.isfinite(value) or value < 0 for value in values):
        return True
    return bool(values) and max(values) - min(values) > 1e-9


def read_page(url, *, scope_id, budget_usd, max_calls=2, ledger_path=None, timeout_s=40):
    _scope(scope_id)
    if not _valid_url(url):
        raise ValyuUnavailable("invalid_url")
    if (isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float))
            or not math.isfinite(budget_usd) or not 0 <= budget_usd <= 0.5):
        raise ValyuUnavailable("invalid_budget")
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or not 1 <= max_calls <= 12:
        raise ValyuUnavailable("invalid_max_calls")
    if (isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s) or not 1 <= timeout_s <= 60):
        raise ValyuUnavailable("invalid_timeout")
    key = env.get("VALYU_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise ValyuUnavailable("missing_key")
    if len(json.dumps({"url": url, "key": key, "timeout_s": timeout_s}).encode()) > 16384:
        raise ValyuUnavailable("invalid_key")
    attempt_id = uuid.uuid4().hex
    day = dt.datetime.now(dt.timezone.utc).date().isoformat()
    with closing(_connect(ledger_path)) as db:
        db.execute("BEGIN IMMEDIATE")
        owner, disabled, cooldown = db.execute("SELECT owner, disabled, cooldown FROM circuit WHERE id=1").fetchone()
        count, cents = db.execute("SELECT COUNT(*), COALESCE(SUM(reserved),0) FROM attempts WHERE scope=?", (scope_id,)).fetchone()
        daily = db.execute("SELECT COUNT(*) FROM attempts WHERE day=?", (day,)).fetchone()[0]
        code = ("circuit_disabled" if disabled else "inflight" if owner else
                "cooldown" if cooldown > time.time() else "scope_quota" if count >= max_calls else
                "daily_quota" if daily >= 20 else "budget_denied" if (cents + 1) / 100 > budget_usd else None)
        if code:
            db.execute("ROLLBACK")
            raise ValyuUnavailable(code)
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,NULL)", (attempt_id, scope_id, day, 1))
        db.execute("UPDATE circuit SET owner=?, lease_until=? WHERE id=1", (attempt_id, time.time() + timeout_s + 60))
        db.execute("COMMIT")

    attempt = {"provider": "valyu", "requested_url": url, "outcome": "unavailable",
               "error_code": "transport_error", "reserved_usd": _RESERVE,
               "reported_cost_usd": None, "cost_status": "unknown", "attempt_id": attempt_id}
    page, cost, disable, cooldown, completed = None, None, True, 0, False
    try:
        result = _isolated_transport(url, key, timeout_s, attempt_id)
        page, attempt, cost, disable, cooldown = (result[x] for x in ("page", "attempt", "cost", "disable", "cooldown"))
        completed = True
    except _TransportFailure as exc:
        attempt["error_code"] = exc.code
        completed = exc.stopped
    except Exception:
        attempt["error_code"] = "worker_failure"
    finally:
        with closing(_connect(ledger_path)) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE attempts SET cost=? WHERE id=?", (cost, attempt_id))
            if completed:
                db.execute("UPDATE circuit SET owner=NULL, lease_until=NULL, disabled=MAX(disabled,?), cooldown=MAX(cooldown,?) WHERE id=1 AND owner=?",
                           (int(disable), cooldown, attempt_id))
            else:
                db.execute("UPDATE circuit SET disabled=1 WHERE id=1 AND owner=?", (attempt_id,))
            db.execute("COMMIT")
    return {"page": page, "attempt": attempt}


class _TransportFailure(Exception):
    def __init__(self, code, stopped):
        self.code, self.stopped = code, stopped
        super().__init__(code)


def _isolated_transport(url, key, timeout_s, attempt_id):
    payload = json.dumps({"url": url, "key": key, "timeout_s": timeout_s, "attempt_id": attempt_id}).encode()
    if len(payload) > 16384:
        raise _TransportFailure("worker_failure", True)
    try:
        proc = subprocess.Popen([sys.executable, "-m", "autonomy.valyu_reader", "--transport-worker"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                cwd=str(paths.PROJECT_ROOT))
    except OSError:
        raise _TransportFailure("worker_failure", True) from None
    try:
        out, _ = proc.communicate(input=payload, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.communicate(timeout=5)
        except Exception:
            raise _TransportFailure("transport_timeout", False) from None
        raise _TransportFailure("transport_timeout", True) from None
    except Exception:
        try:
            proc.kill()
            proc.communicate(timeout=5)
        except Exception:
            raise _TransportFailure("worker_failure", False) from None
        raise _TransportFailure("worker_failure", True) from None
    if proc.returncode != 0 or len(out) > 400000:
        raise _TransportFailure("worker_failure", True)
    try:
        result = json.loads(out)
        if not isinstance(result, dict) or set(result) != {"page", "attempt", "cost", "disable", "cooldown"}:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise _TransportFailure("worker_failure", True) from None


def _http_transport(url, key, timeout_s, attempt_id):
    attempt = {"provider": "valyu", "requested_url": url, "outcome": "unavailable",
               "error_code": "transport_error", "reserved_usd": _RESERVE,
               "reported_cost_usd": None, "cost_status": "unknown", "attempt_id": attempt_id}
    page, cost, disable, cooldown = None, None, False, 0
    response = None
    data = None
    try:
        response = requests.post(_ENDPOINT, headers={"x-api-key": key, "Content-Type": "application/json"},
                                 json={"urls": [url], "response_length": "short", "extract_effort": "normal",
                                        "summary": False, "screenshot": False, "max_age": 0},
                                 timeout=timeout_s, stream=True, allow_redirects=False)
        status = response.status_code
        attempt["http_status"] = status
        if status != 200:
            attempt["error_code"] = "http_error"
            disable = status in (401, 403)
            if status == 429:
                cooldown = time.time() + _retry_after(response.headers.get("Retry-After"))
            elif 500 <= status <= 599:
                cooldown = time.time() + 300
            try:
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    raw.extend(chunk)
                    if len(raw) > _LIMIT:
                        raise ValueError("body_too_large")
                data = json.loads(raw)
                if isinstance(data, dict):
                    cost = _reported(data)
                    if cost is not None:
                        attempt.update(reported_cost_usd=cost, cost_status="reported")
                        disable = disable or cost > _RESERVE
            except (requests.RequestException, ValueError, TypeError, UnicodeError):
                pass
        else:
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                raw.extend(chunk)
                if len(raw) > _LIMIT:
                    raise ValueError("body_too_large")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("invalid_response")
            attempt['response_fields'] = sorted(name for name in data
                if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,47}', name))
            cost = _reported(data)
            if cost is not None:
                attempt.update(reported_cost_usd=cost, cost_status="reported")
                disable = cost > _RESERVE
            if data.get("success") is False:
                attempt["error_code"] = "remote_failure"
            else:
                results = data.get("results")
                if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
                    raise ValueError("invalid_response")
                result = results[0]
                attempt['result_fields'] = sorted(name for name in result
                    if isinstance(name, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,47}', name))
                content = result.get("content")
                if result.get("url") != url:
                    attempt["error_code"] = "url_mismatch"
                elif result.get("status") not in ("success", "ok") or result.get("error"):
                    attempt["error_code"] = "remote_failure"
                elif (result.get("data_type") not in (None, "unstructured") or not isinstance(content, str)
                      or not content.strip()):
                    attempt["error_code"] = "invalid_content"
                elif key in content:
                    attempt['error_code'] = 'credential_echo_rejected'
                    disable = True
                elif re.search(r"(?i)captcha|verify (?:you are|you're) human|checking your browser|cloudflare ray id|access denied", content):
                    attempt["error_code"] = "challenge"
                else:
                    page = {"url": url, "content": content[:30000], "retrieval": {"provider": "valyu", "method": "contents", "attempt_id": attempt_id}}
                    attempt.update(outcome="success", error_code=None)
    except (requests.RequestException, ValueError, TypeError, UnicodeError):
        attempt["error_code"] = "invalid_response" if response is not None and response.status_code == 200 else "transport_error"
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
    if cost is None and (page is None or not isinstance(data, dict)
                         or any(field in data for field in _COST_FIELDS)):
        disable = True
        page = None
        attempt.update(outcome="unavailable", error_code="unknown_cost")
    if isinstance(data, dict) and _billing_invalid(data):
        disable, page = True, None
        attempt.update(outcome='unavailable', error_code='billing_conflict')
    # An omitted usage field is not zero cost. A valid fixed-price Contents page
    # may use the pre-approved per-attempt reserve; malformed usage is rejected.
    return {"page": page, "attempt": attempt, "cost": cost, "disable": disable, "cooldown": cooldown}


if __name__ == "__main__" and sys.argv[1:] == ["--transport-worker"]:
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError
        args = json.loads(raw)
        result = _http_transport(args["url"], args["key"], args["timeout_s"], args["attempt_id"])
        output = json.dumps(result, ensure_ascii=True).encode()
        if len(output) > 400000:
            raise ValueError
        sys.stdout.buffer.write(output)
    except Exception:
        sys.exit(1)
