# -*- coding: utf-8 -*-
"""Детерминированная проверка задачи. Модель ничего не объявляет сама —
только verify.json с pass/fail по факту. Checks из task['acceptance']."""
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from . import paths


def _load_json(fp):
    return json.loads(Path(fp).read_text(encoding="utf-8"))


def run_checks(task, cfg):
    """task: dict с acceptance. Возвращает dict {pass, checks:[...]}."""
    checks = task.get("acceptance", [])
    if not isinstance(checks, list) or not checks:
        return {"task_id": task.get("id"), "pass": False,
                "checks": [{"check": {"acceptance": True}, "ok": False,
                            "detail": "acceptance должен быть непустым списком"}],
                "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    results = []
    all_ok = True
    for c in checks:
        try:
            ok, detail = _run_one(c, cfg)
        except Exception as e:
            ok, detail = False, f"invalid check: {type(e).__name__}"
        results.append({"check": c, "ok": ok, "detail": detail})
        all_ok = all_ok and ok
    return {"task_id": task.get("id"), "pass": all_ok, "checks": results,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}


def _run_one(c, cfg):
    if not isinstance(c, dict) or len(c) != 1:
        return False, "проверка должна содержать ровно один тип"
    if "research_collection" in c:
        if not cfg.get("request_id") or c["research_collection"] != cfg["request_id"]:
            return False, {"error_code": "request_id_mismatch"}
        from . import intake, source_outcomes
        try:
            card = intake.load(c["research_collection"], require_current=False)
            result = source_outcomes.validate_collection(card)
            return result["pass"], result
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            return False, {"error_code": "collection_manifest_invalid"}
    # file_exists: "<path>"
    if "mentor_response" in c:
        from . import intake
        from .claim_validation import ClaimValidationError
        if not cfg.get("request_id") or c["mentor_response"] != cfg["request_id"]:
            return False, {"schema_version": 1, "errors": [
                {"claim_id": None, "codes": ["request_id_mismatch"]}]}
        try:
            result = intake.check_response(c["mentor_response"])
            return True, result
        except ClaimValidationError as error:
            return False, error.diagnostics
        except (ValueError, TypeError, KeyError, OSError, AttributeError):
            return False, {"schema_version": 1, "errors": [
                {"claim_id": None, "codes": ["response_structure_invalid"]}],
                "limitation": "Invalid response structure; no semantic acceptance"}
    if "file_exists" in c:
        p = paths.resolve(c["file_exists"])
        return p.exists(), f"exists={p.exists()}"
    # json_eq: [path, dotted.key, expected]
    if "json_eq" in c:
        path, key, exp = c["json_eq"]
        try:
            val = _get(_load_json(paths.resolve(path)), key)
            return val == exp, f"got={val!r} expected={exp!r}"
        except Exception as e:
            return False, f"error: {e}"
    # number_range: [path, dotted.key, min, max]
    if "number_range" in c:
        path, key, lo, hi = c["number_range"]
        try:
            val = _get(_load_json(paths.resolve(path)), key)
            ok = isinstance(val, (int, float)) and lo <= val <= hi
            return ok, f"got={val} range=[{lo},{hi}]"
        except Exception as e:
            return False, f"error: {e}"
    # regex_in_file: [path, pattern]
    if "regex_in_file" in c:
        path, pat = c["regex_in_file"]
        try:
            txt = paths.resolve(path).read_text(encoding="utf-8")
            found = re.search(pat, txt) is not None
            return found, f"matched={found}"
        except Exception as e:
            return False, f"error: {e}"
    # command: "python ..."  -> exit code 0
    if "command" in c:
        try:
            if not isinstance(c["command"], str) or not paths.command_allowed(c["command"], cfg):
                return False, "команда приёмки запрещена политикой"
            from . import shellutil
            r = shellutil.run_command(c["command"], str(paths.PROJECT_ROOT), timeout=600)
            return r.returncode == 0, f"rc={r.returncode} err={(r.stderr or '')[-200:]}"
        except Exception as e:
            return False, f"error: {e}"
    return False, "unknown check"


def _get(obj, dotted):
    for part in dotted.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def write_result(task_id, verdict):
    paths.ensure_dirs()
    payload = json.dumps(verdict, ensure_ascii=False, indent=2)
    directory = paths.WORKSPACE / "verdicts"
    directory.mkdir(parents=True, exist_ok=True)
    versioned = directory / f"{task_id}-{time.time_ns()}-{uuid.uuid4().hex[:8]}.json"
    with versioned.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    # Совместимая ссылка «последний», не единственное доказательство.
    (paths.WORKSPACE / f"verify.{task_id}.json").write_text(payload, encoding="utf-8")
    return versioned
