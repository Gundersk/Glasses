"""Tool-free ChatGPT generation via the authenticated OpenCode V2 CLI.

No OAuth/credential files, direct paid API, or agent prompt loop. Large context
is uploaded as durable instruction entries in bounded chunks (Windows argv < 32767).
"""
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from . import paths


def _request(method, route, payload=None, timeout=30):
    from .providers import ProviderError
    # Native executable, not cmd.exe: untrusted prompt text must never be shell
    # syntax. npm's wrapper has a fixed path to this binary on this installation.
    exe = shutil.which("opencode.exe")
    if not exe:
        wrapper = shutil.which("opencode.cmd")
        if wrapper:
            candidate = Path(wrapper).parent / "node_modules/@opencode/cli/bin/opencode.exe"
            if candidate.is_file():
                exe = str(candidate)
    if not exe:
        raise ProviderError("OpenCode native launcher unavailable", "config")
    args = [exe, "api", method.lower(), route]
    if payload is not None:
        args += ["--data", json.dumps(payload, ensure_ascii=False)]
    if len(subprocess.list2cmdline(args)) > 28000:
        raise ProviderError("OpenCode request exceeds Windows argv budget", "context")
    try:
        p = subprocess.run(args, capture_output=True, encoding="utf-8", timeout=timeout,
                           shell=False, cwd=paths.PROJECT_ROOT,
                           env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    except (OSError, subprocess.TimeoutExpired):
        raise ProviderError("OpenCode transport failed; not automatically replayed", "provider")
    try:
        if not p.stdout.strip() and p.returncode == 0:
            return {}  # HTTP 204 (instruction update/delete)
        data = json.loads(p.stdout)
    except ValueError:
        raise ProviderError("OpenCode returned non-JSON response", "provider")
    if p.returncode or (isinstance(data, dict) and data.get("_tag")):
        text = str(data.get("message", "")).lower() if isinstance(data, dict) else ""
        quota = (data.get("reason") == "rate_limit" or data.get("status") == 429
                 or any(s in text for s in ("usage_limit", "usage limit", "weekly limit",
                                            "5-hour", "quota exceeded")))
        e = ProviderError("OpenCode subscription quota" if quota else
                          "OpenCode request failed (raw error redacted)",
                          "quota" if quota else "provider")
        e.weekly = "week" in text
        raw = data.get("retryAfterMs")
        if isinstance(raw, (int, float)) and 0 <= raw <= 7 * 86400 * 1000:
            e.retry_at = time.time() + raw / 1000
        raise e
    return data


def chat(name, pcfg, messages, max_tokens):
    from .providers import ProviderError, Result
    t0 = time.time()
    deadline = pcfg.get("_deadline_ts")

    def request(method, route, payload=None, timeout=30):
        if deadline is None:
            return _request(method, route, payload, timeout=timeout)
        remaining = deadline - time.time()
        if remaining <= 0:
            raise ProviderError("request model time budget exhausted", "time_budget")
        try:
            result = _request(method, route, payload, timeout=min(timeout, remaining))
        except ProviderError as e:
            if time.time() >= deadline and e.kind != "time_budget":
                raise ProviderError("request model time budget exhausted", "time_budget",
                                    e.cost_usd, e.in_tok, e.out_tok) from e
            raise
        if time.time() >= deadline:
            data = result.get("data", {}) if isinstance(result, dict) else {}
            data = data if isinstance(data, dict) else {}
            usage = data.get("tokens") or {}
            raise ProviderError("late OpenCode response", "time_budget",
                                float(data.get("cost", 0) or 0),
                                int(usage.get("input", 0)), int(usage.get("output", 0)))
        return result

    model, variant = pcfg["model"], pcfg["variant"]
    catalog = request("GET", "/api/model?" + urlencode({
        "location[directory]": str(paths.PROJECT_ROOT)}))
    entry = next((m for m in catalog.get("data", [])
                  if m.get("providerID") == "openai" and m.get("id") == model), None)
    # Empty pricing is OpenCode's subscription-route metadata. If the owner
    # changes the account to API-key billing, stop rather than silently pay.
    if not entry or entry.get("cost") or not entry.get("enabled"):
        raise ProviderError("ChatGPT subscription model unavailable (or API-priced)", "config")
    v = next((v for v in entry.get("variants", []) if v["id"] == variant), {})
    cap = (v.get("body") or {}).get("max_output_tokens")
    if not isinstance(cap, int) or cap > max_tokens:
        raise ProviderError("OpenCode variant lacks required hard output cap", "config")
    marker = "END_" + uuid.uuid4().hex
    context = json.dumps(messages, ensure_ascii=False)
    # Conservative UTF-8 byte bound, not a tokenizer measurement; never silently
    # truncate a task. Reserve additional room for project instructions.
    input_cap = min(int(entry["limit"].get("input", 0)), pcfg.get("max_input_tokens", 160000))
    if len(context.encode("utf-8")) + cap + 16000 > input_cap:
        raise ProviderError("ChatGPT input exceeds conservative budget; split task", "context")
    session = request("POST", "/api/session", {
        "title": "autonomy: " + name,
        "location": {"directory": str(paths.PROJECT_ROOT)},
        "model": {"providerID": "openai", "id": model, "variant": variant},
        "permissions": [{"action": "*", "resource": "*", "effect": "deny"}],
    })["data"]["id"]
    for i in range(0, len(context), 5000):
        request("PUT", f"/api/experimental/session/{session}/instructions/entries/autonomy-{i // 5000:04d}",
                 {"value": context[i:i + 5000]})
    data = request("POST", f"/api/session/{session}/generate", {
        "prompt": "Concatenate the autonomy-* instruction entry string values in numeric key order into a role-labelled "
                  "JSON message list. Follow those role instructions and return only the "
                  f"requested answer, then on a new line exactly {marker} (outside the answer).",
    }, timeout=pcfg.get("timeout_s", 300))["data"]
    text = data.get("text", "").rstrip()
    usage = data.get("tokens") or {}
    cost = float(data.get("cost", 0) or 0)
    in_tok, out_tok = int(usage.get("input", 0)), int(usage.get("output", 0))
    if cost != 0:
        raise ProviderError("ChatGPT unexpectedly reported API cost", "budget", cost, in_tok, out_tok)
    if not text.endswith(marker):
        raise ProviderError("ChatGPT answer incomplete (missing completion marker)",
                            "truncated_reasoning", 0, in_tok, out_tok)
    text = text[:-len(marker)].rstrip()
    if not text:
        raise ProviderError("ChatGPT empty answer", "empty", 0, in_tok, out_tok)
    return Result(text, name, model, in_tok, out_tok, 0, time.time() - t0,
                  reasoning_tok=int(usage.get("reasoning", 0)))
