# -*- coding: utf-8 -*-
"""Роутер: лестница ролей, бюджет за ночь, token-bucket под квоты Gemini.
Порядок выбора: первый доступный провайдер роли, прошедший бюджет и rate-limit.
Если платные исчерпаны — остаётся бесплатное (локалка/Gemini free)."""
import collections
import json
import time
import uuid

from . import events, providers, state as state_mod
from . import paths, subscription


class RateWindow:
    """Скользящее окно RPM/TPM. Хранится в памяти процесса; на рестарте — чистое."""
    def __init__(self, rpm=None, tpm=None):
        self.rpm = rpm
        self.tpm = tpm
        self.req = collections.deque()  # timestamps
        self.tok = collections.deque()  # (ts, tokens)

    def _prune(self):
        now = time.time()
        while self.req and now - self.req[0] > 60:
            self.req.popleft()
        while self.tok and now - self.tok[0][0] > 60:
            self.tok.popleft()

    def allow(self):
        if not self.rpm and not self.tpm:
            return True, 0
        self._prune()
        wait = 0
        if self.rpm and len(self.req) >= self.rpm:
            wait = max(wait, 60 - (time.time() - self.req[0]) + 0.5)
        if self.tpm:
            used = sum(t for _, t in self.tok)
            if used >= self.tpm:
                wait = max(wait, 60 - (time.time() - self.tok[0][0]) + 0.5)
        return (wait == 0), wait

    def record(self, tokens):
        now = time.time()
        self.req.append(now)
        self.tok.append((now, tokens))


class Router:
    def __init__(self, cfg, log, wait_hook=None):
        self.cfg = cfg
        self.log = log
        self.wait_hook = wait_hook
        self.role_limits = cfg.get("role_limits") or {}
        self.fail_limit = int(cfg["night"].get("provider_fail_limit", 2))
        self.retry_cap = int(cfg["night"].get("truncation_retry_cap", 64000))
        self.windows = {}
        # Окно rate-limit живёт на API-ключ, а не на провайдера: у Gemini один
        # ключ обслуживает и 3.6-flash, и flash-lite, и общая квота аккаунта
        # одна. Иначе две модели на одном ключе дают 2 x rpm запросов в минуту.
        by_key = {}
        for name, pcfg in cfg["providers"].items():
            if pcfg.get("rpm") or pcfg.get("tpm"):
                key = pcfg.get("api_key_env") or f"provider:{name}"
                win = by_key.get(key)
                if win is None:
                    win = RateWindow(pcfg.get("rpm"), pcfg.get("tpm"))
                    by_key[key] = win
                self.windows[name] = win

    def _budget_left(self, st):
        cap = self.cfg["night"].get("budget_usd_per_night", 1.0)
        return cap - st.get("budget_used_usd", 0.0)

    def _disable(self, st, name, reason):
        st.setdefault("disabled_providers", {})[name] = reason[:160]
        events.emit("provider_disabled", provider=name, reason=reason[:160])
        self.log.warn(f"провайдер {name} отключён до утра: {reason[:120]}")

    @staticmethod
    def _provider_model(pcfg):
        """Реальный model ID кандидата: model_env важнее поля model конфига."""
        model = pcfg.get("model")
        if pcfg.get("model_env"):
            model = providers.env.get(pcfg["model_env"], model)
        return str(model or "")

    def _ladder_models(self, role):
        """Все model ID из лестницы роли (для безопасного исключения без автора)."""
        out = set()
        provs = self.cfg.get("providers", {}) or {}
        for name in self.cfg.get("roles", {}).get(role) or []:
            m = self._provider_model(provs.get(name) or {})
            if m:
                out.add(m)
        return out

    def _forbidden_models(self, role, st):
        """Модели, уже использованные ролью-источником: тот же model ID = не независимость.

        Сравниваем model ID, а не алиас провайдера: два алиаса одной модели
        независимыми не являются. Пустое множество — ограничений нет.
        """
        per_role = st.get("last_model_by_role") or {}
        if role == "critic":
            out = set()
            author = st.get("plan_author_model")
            if author:
                out.add(str(author))
            last_planner = per_role.get("planner")
            if last_planner:
                out.add(str(last_planner))
            # Автор неизвестен (план загружен) — исключаем всю лестницу planner.
            return out or self._ladder_models("planner")
        if role == "verifier":
            last_exec = per_role.get("executor")
            if last_exec:
                return {str(last_exec)}
            # Исполнитель неизвестен — исключаем всю лестницу executor.
            return self._ladder_models("executor")
        return set()

    def call(self, role, st, messages, max_tokens=4096, temperature=0.3, _waited=False):
        ladder = self.cfg["roles"].get(role, [])
        if not ladder:
            raise providers.ProviderError(f"нет провайдеров для роли {role}", "config")
        # Потолок вывода задаётся ролью, а не вызовом: у автора кода он в разы
        # больше, чем у контролёра, и не должен съедаться reasoning-токенами.
        max_tokens = int((self.role_limits.get(role) or {}).get("max_tokens", max_tokens))
        disabled = st.get("disabled_providers") or {}
        fails = st.setdefault("provider_fails", {})
        # Физические попытки (включая retry после обрезки) — отдельно от успешных вызовов.
        # Счётчик привязан к ночи: state.py обнуляет calls/budget при смене даты,
        # но про новый ключ не знает, поэтому сбрасываем сами.
        if st.get("attempts_night") != st.get("night_id"):
            st["attempts_by_provider"] = {}
            st["attempts_night"] = st.get("night_id")
        attempts = st.setdefault("attempts_by_provider", {})
        # Независимость моделей: critic не повторяет автора плана, verifier — исполнителя.
        forbidden = self._forbidden_models(role, st)
        errors = []
        pending_quota = None
        for name in ladder:
            deadline = st.get("request_model_deadline_ts")
            if deadline is not None and time.time() >= deadline:
                raise providers.ProviderError("request model time budget exhausted", "time_budget")
            if disabled.get(name):
                errors.append(f"{name}: отключён до утра ({disabled[name][:60]})")
                continue
            base_pcfg = self.cfg["providers"].get(name)
            if not base_pcfg:
                errors.append(f"{name}: нет конфига")
                continue
            # Тот же model ID под другим алиасом — не независимая проверка. Такой
            # кандидат пропускается только на этот вызов, глобально не отключается.
            model_id = self._provider_model(base_pcfg)
            if model_id and model_id in forbidden:
                events.emit("model_skip", role=role, provider=name,
                            model=model_id, reason="independence")
                errors.append(f"{name}: independence, model={model_id} уже использован")
                continue
            # Каждая физическая попытка должна проходить через учёт роутера, поэтому
            # скрытые HTTP-retry внутри providers.chat выключаем (копия, конфиг не меняем).
            pcfg = dict(base_pcfg, retries=0)
            # Лимит вызовов на ночь: подписка Kimi конечная, квоту не жжём.
            cap_n = (self.cfg["night"].get("max_calls_per_provider") or {}).get(name)
            # Потолок вывода провайдера применяется сразу, до первой попытки.
            max_out = max(1, min(self.retry_cap, int(pcfg.get("max_output_tokens") or self.retry_cap)))
            cur_tokens = max(1, min(int(max_tokens), max_out))
            retried = False
            while True:
                deadline = st.get("request_model_deadline_ts")
                if deadline is not None and time.time() >= deadline:
                    raise providers.ProviderError("request model time budget exhausted", "time_budget")
                # Гейты на каждую физическую попытку: cap, бюджет, rate-limit, health.
                # После truncation-retry они проверяются заново по остатку бюджета.
                used_n = attempts.get(name, 0)
                if cap_n is not None and used_n >= cap_n:
                    errors.append(f"{name}: лимит физических попыток за ночь исчерпан ({used_n}/{cap_n})")
                    break
                # Бюджет: платный провайдер пропускаем, если остаток < оценки попытки.
                est_in_tok = sum(len(str(m.get("content", ""))) for m in messages) // 4
                est_cost = (est_in_tok * pcfg.get("price_in_usd_per_mtok", 0.0)
                            + cur_tokens * pcfg.get("price_out_usd_per_mtok", 0.0)) / 1e6
                left = self._budget_left(st)
                if est_cost > 0 and est_cost > left:
                    errors.append(f"{name}: не хватает бюджета ({est_cost:.3f}$ > {left:.3f}$)")
                    break
                # Rate limit.
                win = self.windows.get(name)
                if win:
                    ok, wait = win.allow()
                    if not ok:
                        self.log.warn(f"rate-limit {name}: ждать {wait:.1f}s — пробуем следующий")
                        errors.append(f"{name}: rate-limit, wait {wait:.1f}s")
                        break
                # Локалка: быстрая проверка живости до долгого запроса.
                if name == "local" and not providers.health(name, pcfg):
                    self.log.warn(f"{role}: local-сервер недоступен (health) — пропускаю")
                    events.emit("model_skip", role=role, provider=name, reason="health fail")
                    errors.append(f"{name}: health-check fail (сервер не отвечает)")
                    break
                if deadline is not None and time.time() >= deadline:
                    raise providers.ProviderError("request model time budget exhausted", "time_budget")
                if pcfg.get("kind") == "opencode-chatgpt":
                    # Reserve account-wide before any possible generation. A failed
                    # transport still counts: the server may have started work.
                    blocked = subscription.reserve(st.setdefault("subscription_run_id", uuid.uuid4().hex),
                                                   self.cfg["night"])
                    if blocked:
                        errors.append(f"{name}: {blocked['reason']}")
                        if blocked["reason"] == "quota":
                            pending_quota = blocked
                        break
                if deadline is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise providers.ProviderError("request model time budget exhausted", "time_budget")
                    pcfg["timeout_s"] = min(base_pcfg.get("timeout_s", 300), remaining)
                    pcfg["_deadline_ts"] = deadline
                attempts[name] = used_n + 1
                if self.wait_hook:
                    state_mod.save(st)  # persist physical-attempt accounting before send
                try:
                    res = providers.chat(name, pcfg, messages,
                                         max_tokens=cur_tokens, temperature=temperature)
                    if deadline is not None and time.time() >= deadline:
                        raise providers.ProviderError("late model response", "time_budget",
                                                      res.cost_usd, res.in_tok, res.out_tok)
                except providers.ProviderError as e:
                    if self.cfg["night"].get("sanitize_provider_errors"):
                        kinds = {"config", "provider", "timeout", "rate", "budget", "empty",
                                 "empty_reasoning", "truncated", "truncated_reasoning", "stream",
                                 "stream_incomplete", "time_budget", "browser_unavailable"}
                        kind = e.kind if e.kind in kinds else "provider"
                        safe_browser_errors = {"unavailable", "deadline_expired", "incomplete_response",
                            "verification_hold", "auth_hold", "rate_limited", "http_error",
                            "invalid_response", "ledger_error", "unknown_model", "invalid_input",
                            "invalid_config", "watchdog_timeout", "lease_active"}
                        code = str(e).removeprefix("browser_gateway:")
                        safe_http_code = (code.startswith("http_") and len(code) == 8
                                          and code[5:].isdigit() and 100 <= int(code[5:]) <= 599)
                        message = (str(e) if str(e).startswith("browser_gateway:") and (code in safe_browser_errors or safe_http_code)
                                   else f"{name}: request_failed ({kind})")
                        e = providers.ProviderError(message, kind,
                                                    e.cost_usd, e.in_tok, e.out_tok)
                    # Неудачный вызов мог стоить денег — учитываем, чтобы бюджет не врал.
                    err_cost = float(getattr(e, "cost_usd", 0.0) or 0.0)
                    err_in = int(getattr(e, "in_tok", 0) or 0)
                    err_out = int(getattr(e, "out_tok", 0) or 0)
                    st["budget_used_usd"] = st.get("budget_used_usd", 0.0) + err_cost
                    if win:
                        win.record(err_in + err_out)
                    self.log.warn(f"{role}: {name} -> {e}")
                    events.emit("model_fail", role=role, provider=name,
                                kind=e.kind, error=str(e)[:200],
                                cost_usd=round(err_cost, 5),
                                in_tok=err_in, out_tok=err_out,
                                attempt=attempts.get(name, 0))
                    errors.append(f"{name}: {e}")
                    if e.kind == "time_budget":
                        raise
                    if deadline is not None and time.time() >= deadline:
                        raise providers.ProviderError("request model time budget exhausted", "time_budget") from e
                    if e.kind == "quota" and pcfg.get("kind") == "opencode-chatgpt":
                        pending_quota = subscription.defer(e, self.cfg["night"])
                        # Quota is not an unhealthy model: do not disable until morning.
                        break
                    # Обрезка по нашему потолку — повтор с удвоенным бюджетом.
                    # Пустота из-за reasoning не лечится удвоением на этой модели:
                    # уходим к следующему провайдеру, у которого reasoning выключен.
                    if e.kind == "truncated" and not retried and cur_tokens * 2 <= max_out:
                        cur_tokens *= 2
                        retried = True
                        self.log.warn(f"{role}: {name} обрезан — повтор с max_tokens={cur_tokens}")
                        continue
                    fails[name] = fails.get(name, 0) + 1
                    if fails[name] >= self.fail_limit:
                        self._disable(st, name, str(e))
                    break
                fails[name] = 0
                st.pop("subscription_blocked", None)
                if win:
                    win.record(res.in_tok + res.out_tok)
                cb = st.setdefault("calls_by_provider", {})
                cb[name] = cb.get(name, 0) + 1
                # Фактическая модель успешного вызова: по ней проверяется независимость
                # следующих ролей (алиас провайдера для этого не годится).
                st.setdefault("last_model_by_role", {})[role] = res.model
                st["budget_used_usd"] = st.get("budget_used_usd", 0.0) + res.cost_usd
                cap = self.cfg["night"].get("budget_usd_per_night", 1.0)
                used = st.get("budget_used_usd", 0.0)
                if cap > 0 and used >= cap * 0.5 > used - res.cost_usd:
                    self.log.warn(f"бюджет: израсходовано {used:.3f}$ из {cap:.3f}$ (половина)")
                    events.emit("budget_warn", used=round(used, 4), cap=cap)
                events.emit("model_call", role=role, provider=name, model=res.model,
                            in_tok=res.in_tok, out_tok=res.out_tok,
                            reasoning_tok=res.reasoning_tok,
                            cost_usd=round(res.cost_usd, 5), latency=round(res.latency, 1),
                            finish=res.finish)
                self.log.log(f"{role}: {name} ok in={res.in_tok} out={res.out_tok} "
                             f"reasoning={res.reasoning_tok} "
                             f"cost=${res.cost_usd:.4f} lat={res.latency:.1f}s")
                return res
        # First use any permitted independent alternative. Only then wait, inside
        # the exact same call: never replay the phase's commands or file writes.
        if pending_quota and not _waited and self.wait_hook:
            deadline = st.get("request_model_deadline_ts")
            if deadline is not None and time.time() >= deadline:
                raise providers.ProviderError("request model time budget exhausted", "time_budget")
            remaining = pending_quota["until"] - time.time()
            if 0 < remaining <= self.cfg["night"].get("subscription_wait_max_s", 21600):
                st["subscription_wait"] = dict(pending_quota, role=role)
                state_mod.save(st)
                events.emit("subscription_wait", role=role, until=pending_quota["until"],
                            weekly=pending_quota["weekly"])
                while time.time() < pending_quota["until"]:
                    self.wait_hook(st, 0)
                    started = time.time()
                    time.sleep(min(15, max(0, pending_quota["until"] - time.time())))
                    elapsed = time.time() - started
                    st["subscription_wait_seconds"] = st.get("subscription_wait_seconds", 0) + elapsed
                    if st.get("request_model_deadline_ts") is not None:
                        st["request_model_deadline_ts"] += elapsed
                    self.wait_hook(st, elapsed)
                st.pop("subscription_wait", None)
                state_mod.save(st)
                return self.call(role, st, messages, max_tokens, temperature, _waited=True)
        if pending_quota:
            st["subscription_blocked"] = pending_quota
        raise providers.ProviderError(f"{role}: все провайдеры недоступны: " + " | ".join(errors), "ladder")
