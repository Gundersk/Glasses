"""Shared ChatGPT account guard. SQLite serializes reservations across request runs.

Local caps are policy, not knowledge of the provider's remaining allowance.
The ledger is intentionally outside an isolated mentor-request workspace.
"""
import sqlite3
import time
from contextlib import contextmanager

from . import paths

LEDGER = paths.AUTONOMY_DIR / "workspace" / "subscription.sqlite3"


class WaitStopped(BaseException):
    """Owner interrupt, not a model failure for critic/repair to swallow."""


@contextmanager
def _db():
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(LEDGER, timeout=10)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS attempts (ts REAL, run TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS cooldown (id INTEGER PRIMARY KEY, until REAL, weekly INTEGER)")
        with db:
            yield db
    finally:
        db.close()


def reserve(run_id, cfg, now=None):
    now = time.time() if now is None else now
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        cooldown = db.execute("SELECT until, weekly FROM cooldown WHERE id=1").fetchone()
        if cooldown and cooldown[0] > now:
            return {"reason": "quota", "until": cooldown[0], "weekly": bool(cooldown[1])}
        weekly = db.execute("SELECT COUNT(*) FROM attempts WHERE ts>?", (now - 7 * 86400,)).fetchone()[0]
        run = db.execute("SELECT COUNT(*) FROM attempts WHERE run=?", (run_id,)).fetchone()[0]
        if run >= cfg.get("chatgpt_max_attempts_per_run", 10):
            return {"reason": "run_cap"}
        if weekly >= cfg.get("chatgpt_max_attempts_7d", 60):
            return {"reason": "local_weekly_cap"}
        db.execute("INSERT INTO attempts VALUES (?,?)", (now, run_id))
    return None


def defer(error, cfg, now=None):
    now = time.time() if now is None else now
    weekly = bool(getattr(error, "weekly", False))
    until = getattr(error, "retry_at", None)
    # Unknown weekly reset is never assumed to clear in five hours.
    if until is None:
        until = now + (7 * 86400 if weekly else cfg.get("subscription_reset_fallback_s", 18300))
    until = max(now + 60, until + 60)  # boundary safety margin
    with _db() as db:
        old = db.execute("SELECT until, weekly FROM cooldown WHERE id=1").fetchone()
        if old and old[0] > until:
            until, weekly = old[0], bool(old[1])
        db.execute("INSERT OR REPLACE INTO cooldown VALUES (1,?,?)", (until, int(weekly)))
    return {"reason": "quota", "until": until, "weekly": weekly}
