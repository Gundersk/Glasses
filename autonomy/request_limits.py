"""Shared, persisted budgets for an explicitly authorized research request."""
import math
import time
from contextlib import contextmanager

from . import request_research


class TimeBudgetExceeded(ValueError):
    pass


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {name}")
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f"invalid {name}") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def _counter(value, allowed, name):
    if type(value) is not int or not 0 <= value <= allowed:
        raise ValueError(f"invalid {name}")
    return value


def lane_caps(card):
    try:
        spec = card["spec"]
        if not isinstance(spec.get("research_policy"), dict) or not spec["research_policy"]:
            raise ValueError("research policy required")
        minutes = _number(spec["time_limit_minutes"], "time_limit_minutes")
        answer = minutes * 60.0
        if not math.isfinite(answer):
            raise ValueError("invalid time limit")
        return {"sources": 600.0, "answer": answer}
    except (KeyError, TypeError, AttributeError):
        raise ValueError("invalid research card") from None


def _times(st):
    if not isinstance(st, dict):
        raise ValueError("invalid state")
    work = st.get("request_work_seconds", {})
    if not isinstance(work, dict) or set(work) - {"sources", "answer"}:
        raise ValueError("invalid work state")
    return {lane: _number(work.get(lane, 0), lane) for lane in ("sources", "answer")}


def remaining(card, st, lane):
    caps = lane_caps(card)
    if lane not in caps:
        raise ValueError("invalid lane")
    used = _times(st)
    total_used = used["sources"] + used["answer"]
    if not math.isfinite(total_used):
        raise ValueError("invalid total work")
    return max(0.0, min(caps[lane] - used[lane], sum(caps.values()) - total_used))


def snapshot(card, st, coordinator_minutes=50):
    caps = lane_caps(card)
    used = _times(st)
    policy = card["spec"]["research_policy"]
    plan = request_research.read_plan(card)
    counts = {}
    for name, key, value in (
        ("queries", "max_queries", st.get("request_sources_attempted", 0)),
        ("plan_revisions", "max_plan_revisions", plan["plan_revisions"]),
        ("followup_rounds", "max_followup_rounds", plan["followup_rounds"]),
        ("answer_attempts", "answer_attempts", st.get("request_answer_attempts", 0)),
    ):
        allowed = policy.get(key)
        if type(allowed) is not int or allowed < 0:
            raise ValueError(f"invalid {key}")
        value = _counter(value, allowed, name)
        counts[name] = {"allowed": allowed, "used": value, "remaining": allowed - value}
    planned = len(plan["queries"])
    _counter(planned, counts["queries"]["allowed"], "planned queries")
    counts["queries"].update(planned=planned, unplanned_capacity=counts["queries"]["allowed"] - planned)
    times = {}
    for lane in caps:
        times[lane] = {"allowed_seconds": caps[lane], "used_seconds": used[lane],
                       "remaining_seconds": remaining(card, st, lane),
                       "scope": "shared across all collection tasks" if lane == "sources" else "shared across all answer attempts"}
    total = sum(caps.values())
    total_used = sum(used.values())
    times["work_total"] = {"allowed_seconds": total, "used_seconds": total_used,
                           "remaining_seconds": max(0.0, total - total_used)}
    coordinator = _number(coordinator_minutes, "coordinator_minutes") * 60
    if not math.isfinite(coordinator):
        raise ValueError("invalid coordinator time")
    times["coordinator"] = {"allowed_seconds": coordinator, "scope": "wall active excluding subscription wait, includes planning/review/verification"}
    return {"schema_version": 1, "counts": counts, "time": times,
            "subscription_wait_seconds": _number(st.get("subscription_wait_seconds", 0), "subscription wait")}


@contextmanager
def account(card, st, lane, save=None):
    available = remaining(card, st, lane)
    wait_before = _number(st.get("subscription_wait_seconds", 0), "subscription wait")
    if available <= 0:
        raise TimeBudgetExceeded("work time exhausted")
    if lane == "answer" and "request_model_deadline_ts" in st:
        raise ValueError("nested model deadline")
    if lane == "answer":
        st["request_model_deadline_ts"] = time.time() + available
    try:
        if save is not None:
            save(st)
        start = time.monotonic()
        try:
            yield available
        finally:
            elapsed = _number(time.monotonic() - start, "elapsed time")
            try:
                wait_after = _number(st.get("subscription_wait_seconds", 0), "subscription wait")
                pause = wait_after - wait_before
                if pause < 0 or pause > elapsed:
                    raise ValueError("invalid subscription wait delta")
            except ValueError:
                # Unknown wait must not turn elapsed work into free time.
                work = _times(st)
                work[lane] += elapsed
                st["request_work_seconds"] = work
                raise
            work = _times(st)
            charged = elapsed - pause
            work[lane] += charged
            if not math.isfinite(work[lane]):
                raise ValueError("invalid charged work")
            st["request_work_seconds"] = work
            if charged > available:
                raise TimeBudgetExceeded("work time exceeded")
    finally:
        if lane == "answer":
            st.pop("request_model_deadline_ts", None)
        if save is not None:
            save(st)
