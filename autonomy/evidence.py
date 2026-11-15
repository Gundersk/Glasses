"""Протокол исполнения команд: хэши и полный вывод без известных секретов.

Это след исполнения, не доказательство правильности научной методики и не
криптографически защищённый журнал: процесс работает с правами владельца.
"""
import hashlib
import json
import os
import platform
import re
import sys
import time
import uuid

from . import env, paths


def redact(text):
    env.load_env()
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    value = str(text or "")
    secrets = [v for k, v in os.environ.items()
               if re.search(r"KEY|TOKEN|SECRET|PASSWORD", k, re.I) and len(v) >= 8]
    for secret in sorted(secrets, key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return re.sub(r"(?i)\bBearer\s+[\w.\-+/=]+", "Bearer [REDACTED]", value)


def fingerprint(rel):
    if not isinstance(rel, str) or not paths.inside_project(rel):
        return {"path": str(rel), "status": "outside_project"}
    fp = paths.resolve(rel)
    if fp.name.startswith(".env") or "temp" in fp.relative_to(paths.PROJECT_ROOT).parts:
        return {"path": rel, "status": "sensitive_omitted"}
    if not fp.is_file():
        return {"path": rel, "status": "missing_or_not_file"}
    h = hashlib.sha256()
    with fp.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    stat = fp.stat()
    return {"path": rel, "status": "file", "sha256": h.hexdigest(),
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def outputs(task):
    """Все файловые результаты приёмки, а не только file_exists."""
    result = set()
    for check in task.get("acceptance", []):
        if not isinstance(check, dict):
            raise ValueError("невалидная файловая приёмка")
        for kind in ("file_exists", "json_eq", "number_range", "regex_in_file"):
            if kind in check:
                value = check[kind]
                rel = value if kind == "file_exists" else value[0]
                if not isinstance(rel, str) or not rel:
                    raise ValueError("пустой или нестроковый путь результата")
                result.add(rel)
    return sorted(result)


def command_sha256(command):
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _write_new(fp, obj):
    with fp.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2)


def begin(task, plan_sha256, *, mock=False):
    run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
    directory = paths.WORKSPACE / "evidence" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    rec = {"version": 2, "run_id": run_id, "task_id": task["id"],
           "plan_sha256": plan_sha256, "execution": task.get("execution", "model_proposed"),
           "mock": bool(mock), "started_ns": time.time_ns(),
           "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
           "seed": task.get("seed"), "protocol": task.get("protocol"),
           "inputs": [fingerprint(p) for p in task.get("inputs", [])],
           "outputs_before": [fingerprint(p) for p in outputs(task)], "commands": []}
    _write_new(directory / "start.json", rec)
    return directory, rec


def record_command(directory, rec, command, result, started_ns, *, status="completed"):
    index = len(rec["commands"])
    item = {"command": redact(command), "command_sha256": command_sha256(command),
            "returncode": result.returncode, "status": status,
            "started_ns": started_ns, "finished_ns": time.time_ns()}
    for key in ("stdout", "stderr"):
        fp = directory / f"command-{index:03d}.{key}.txt"
        with fp.open("x", encoding="utf-8") as stream:
            stream.write(redact(getattr(result, key, "")))
        item[key] = fingerprint(str(fp.relative_to(paths.PROJECT_ROOT)))
    rec["commands"].append(item)
    _write_new(directory / f"command-{index:03d}.json", item)


def finish(directory, rec, task):
    rec["finished_ns"] = time.time_ns()
    rec["outputs_after"] = [fingerprint(p) for p in outputs(task)]
    fp = directory / "receipt.json"
    _write_new(fp, rec)
    return str(fp.relative_to(paths.PROJECT_ROOT)).replace("\\", "/")


def validate(receipt, task, plan_sha256):
    """Приёмка измерительного запуска: успешные команды и свежие результаты."""
    try:
        fp = paths.resolve(receipt)
        fp.relative_to(paths.WORKSPACE / "evidence")
        rec = json.loads(fp.read_text(encoding="utf-8"))
        if (rec.get("version") != 2 or rec.get("task_id") != task["id"]
                or rec.get("plan_sha256") != plan_sha256
                or rec.get("mock") or rec.get("execution") != "approved_commands"):
            return False, "не совпадает задача/план/режим либо это mock"
        commands = rec.get("commands") or []
        expected_commands = task.get("commands") or []
        if (not expected_commands or [c.get("command_sha256") for c in commands]
                != [command_sha256(c) for c in expected_commands]):
            return False, "число/порядок команд не совпадает с утверждённым протоколом"
        if any(c.get("returncode") != 0 or c.get("status") != "completed" for c in commands):
            return False, "нет успешного полного исполнения команд"
        before = {p["path"]: p for p in rec.get("outputs_before", [])}
        after = rec.get("outputs_after") or []
        expected_outputs = outputs(task)
        if (not expected_outputs or sorted(before) != expected_outputs
                or sorted(p["path"] for p in after) != expected_outputs
                or len(rec.get("outputs_before", [])) != len(expected_outputs)):
            return False, "протокол не покрывает все файлы приёмки"
        for item in after:
            now = fingerprint(item["path"])
            if item.get("status") != "file" or now != item:
                return False, "результат отсутствует или изменился после запуска"
            if before.get(item["path"]) == item:
                return False, "предъявлен старый файл без обновления в этом запуске"
        for cmd in commands:
            for key in ("stdout", "stderr"):
                item = cmd[key]
                if item != fingerprint(item["path"]):
                    return False, "журнал команды отсутствует или изменён"
        inputs = rec.get("inputs", [])
        if sorted(p["path"] for p in inputs) != sorted(task.get("inputs", [])):
            return False, "протокол не покрывает заявленные входы"
        for item in inputs:
            if item.get("status") != "file" or item != fingerprint(item["path"]):
                return False, "заявленный вход отсутствовал или изменился"
        return True, "команды и свежие артефакты связаны протоколом; методика требует отдельного ревью"
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return False, "недействительный протокол исполнения"
