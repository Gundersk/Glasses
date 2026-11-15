"""Bounded, auditable context capture; no model or runner side effects."""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from . import paths


class ContextError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ContextError("invalid_json_value") from None


def _safe_path(value):
    try:
        root = Path(paths.PROJECT_ROOT).resolve()
        raw = Path(value)
        candidate = raw if raw.is_absolute() else root / raw
        # Check both lexical and resolved paths, including links into denied areas.
        lexical = Path(os.path.abspath(candidate))
        resolved = candidate.resolve()
        for p in (lexical, resolved):
            rel = p.relative_to(root)
            for part in rel.parts:
                name = part.casefold()
                if name in ("temp", "secrets", "credentials", ".env") or name.startswith(".env.") or "credential" in name or "secret" in name or name.endswith((".key", ".pem")):
                    raise ContextError("path_denied")
        if lexical != resolved:
            raise ContextError("path_denied")
        return resolved, resolved.relative_to(root).as_posix()
    except ContextError:
        raise
    except (ValueError, OSError, RuntimeError, TypeError):
        raise ContextError("path_denied") from None


class Capture:
    def __init__(self):
        self.records = []

    def read(self, path, limit=8000, required=False, mode="prefix"):
        if type(limit) is not int or not 1 <= limit <= 1_000_000:
            raise ContextError("invalid_limit")
        if type(required) is not bool or mode not in ("prefix", "status_current"):
            raise ContextError("invalid_selection")
        fp, rel = _safe_path(path)
        record = dict(path=rel, sha256=None, source_characters=0, included_characters=0,
                      omitted_characters=0, required=required, status="missing", selection_mode=mode,
                      omitted_history=False)
        try:
            with fp.open("rb") as f:
                data = f.read(2_000_001)
        except FileNotFoundError:
            self.records.append(record)
            if required:
                raise ContextError("required_component_missing") from None
            return "[missing: " + rel + "]"
        except OSError:
            raise ContextError("file_read_failed") from None
        if len(data) > 2_000_000:
            raise ContextError("file_too_large")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeError:
            raise ContextError("invalid_utf8") from None
        record.update(sha256=hashlib.sha256(data).hexdigest(), source_characters=len(text), status="included")
        selected = text
        if mode == "status_current":
            for match in re.finditer(r"^##[ \t]+([^\r\n]+)", text, re.MULTILINE):
                if match.group(1).strip().casefold().startswith(("предыдущ", "истор")):
                    selected = text[:match.start()]
                    record["omitted_history"] = True
                    break
        if len(selected) > limit and (required or mode == "status_current"):
            record.update(status="rejected", omitted_characters=len(text))
            self.records.append(record)
            raise ContextError("current_status_too_large" if mode == "status_current" else "required_component_too_large")
        included = selected[:limit]
        omitted = len(text) - len(included)
        record.update(included_characters=len(included), omitted_characters=omitted)
        self.records.append(record)
        if omitted:
            return included + ("\n[history omitted: " if record["omitted_history"] else "\n[content omitted: ") + str(omitted) + " characters]"
        return included


_POLICY = ("topics", "max_queries", "pages_per_query", "max_plan_revisions", "max_followup_rounds", "answer_attempts", "min_sources", "min_domains", "reuse_sources", "retrieval_budget_usd", "max_reader_calls")
_RUNTIME = ("needs_human", "request_force_partial", "request_outcome", "request_answer_attempts", "request_sources_attempted", "request_work_seconds", "paid_work_blocked", "disabled_providers")


def _error_ref(value):
    if value is None:
        return {"present": False, "sha256": None}
    if not isinstance(value, str):
        raise ContextError("invalid_state")
    try:
        digest = hashlib.sha256(value.encode("utf-8", "strict")).hexdigest()
    except UnicodeError:
        raise ContextError("invalid_state") from None
    return {"present": bool(value), "sha256": digest}


def _no_credentials(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or any(s in key.casefold() for s in ("secret", "credential", "password", "api_key", "token")):
                raise ContextError("invalid_state")
            _no_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _no_credentials(item)


def handoff(st, card=None):
    if not isinstance(st, dict) or (card is not None and not isinstance(card, dict)):
        raise ContextError("invalid_state")
    task = st.get("task") or {}
    tasks = st.get("tasks", [])
    if not isinstance(task, dict) or not isinstance(tasks, list) or len(tasks) > 100 or any(not isinstance(t, dict) for t in tasks):
        raise ContextError("invalid_tasks")
    full_task = next((item for item in tasks if item.get('id') == task.get('id')), task)
    spec = (card.get("spec", card) if card is not None else {})
    if not isinstance(spec, dict):
        raise ContextError("invalid_card")
    policy = spec.get("research_policy") or {}
    if not isinstance(policy, dict):
        raise ContextError("invalid_policy")
    disabled = st.get("disabled_providers")
    if disabled is not None and not isinstance(disabled, dict):
        raise ContextError("invalid_state")
    if disabled is not None and any(not isinstance(k, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", k) for k in disabled):
        raise ContextError("invalid_state")
    snapshot = {
        "schema_version": 1,
        "run": {"night_id": st.get("night_id"), "phase": st.get("phase"), "current_task_id": task.get("id"), "iter": task.get("iter", st.get("iter"))},
        "purpose": ({k: spec.get(k) for k in ("id", "closes", "instruction", "requirements")} if card is not None else
                    {key: full_task.get(key) for key in ('id', 'goal', 'closes', 'acceptance')}),
        "permissions": {"run_started_by_this_packet": False, "new_search_authorized_by_this_packet": False, "canonical_docs_may_change": False, "owner_controls_stage_closure": True},
        "tasks": [{k: t.get(k) for k in ("id", "status", "verify_file", "receipt")} for t in tasks],
        "constraints": {k: policy[k] for k in _POLICY if k in policy},
        "runtime": {**{k: st.get(k) for k in _RUNTIME if k not in ("needs_human", "disabled_providers")}, "needs_human": _error_ref(st.get("needs_human")), "disabled_providers": ({k: _error_ref(v) for k, v in disabled.items()} if disabled is not None else None), "allowed_budget_usd": spec.get("budget_usd"), "time_limit_minutes": spec.get("time_limit_minutes")},
        "last_error": _error_ref(st.get("last_error")),
        "validation_feedback_present": bool(task.get("validation_feedback")),
        "warning": "Process DONE does not imply an accepted outcome.",
    }
    _no_credentials(snapshot)
    serialized = _json(snapshot)
    if len(serialized) > 16000:
        raise ContextError("handoff_too_large")
    return json.loads(serialized)


def save_manifest(role, messages, capture, st, *, max_chars=220000, card=None, rejection_code=None):
    if not isinstance(role, str) or not re.fullmatch(r"[a-z_]{1,40}", role) or not isinstance(messages, list) or len(messages) > 20 or type(max_chars) is not int or max_chars < 1:
        raise ContextError("invalid_packet")
    if rejection_code is not None and (not isinstance(rejection_code, str) or not re.fullmatch(r"[a-z_]{1,80}", rejection_code)):
        raise ContextError("invalid_packet")
    if any(not isinstance(m, dict) or set(m) != {"role", "content"} or not all(isinstance(m[k], str) for k in ("role", "content")) for m in messages):
        raise ContextError("invalid_packet")
    if not isinstance(capture, Capture) or not isinstance(st, dict):
        raise ContextError("invalid_packet")
    payload = _json(messages)
    try:
        encoded = payload.encode("utf-8", "strict")
    except UnicodeError:
        raise ContextError("invalid_packet") from None
    chars = sum(len(m["content"]) for m in messages)
    snapshot = handoff(st, card)
    manifest = {"schema_version": 1, "role": role, "night_id": st.get("night_id"), "task_id": snapshot["run"]["current_task_id"], "packet_sha256": hashlib.sha256(encoded).hexdigest(), "characters": chars, "utf8_bytes": len(encoded), "policy_max_chars": max_chars, "files": capture.records, "handoff": snapshot, "status": "rejected" if chars > max_chars or rejection_code else "ready", "limitations": ["not tokenizer/quality measurement"]}
    if rejection_code or chars > max_chars:
        manifest["rejection_code"] = rejection_code or "packet_too_large"
    serialized = _json(manifest)
    try:
        root = Path(paths.PROJECT_ROOT).resolve()
        workspace = Path(paths.WORKSPACE)
        if not workspace.is_absolute():
            workspace = root / workspace
        if workspace.resolve() != Path(os.path.abspath(workspace)):
            raise ValueError("workspace redirect")
        workspace.resolve().relative_to(root)
        directory = workspace / "context"
        directory.mkdir(parents=True, exist_ok=True)
        if directory.resolve() != directory or not directory.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("context redirect")
        fp = directory / (uuid.uuid4().hex + ".json")
        with fp.open("x", encoding="utf-8", newline="\n") as out:
            out.write(serialized)
        relative = fp.relative_to(root).as_posix()
    except (OSError, ValueError, RuntimeError):
        raise ContextError("manifest_write_failed") from None
    previous = st.get("context_manifests", [])
    if not isinstance(previous, list):
        previous = []
    st["context_manifests"] = (previous + [relative])[-20:]
    st["last_context_manifest"] = relative
    if chars > max_chars and rejection_code is None:
        raise ContextError("packet_too_large")
    return Path(relative)
