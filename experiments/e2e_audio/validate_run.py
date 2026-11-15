"""Слой 1: детерминированный адверсариальный валидатор прогона.

По умолчанию ответ FAIL. PASS - только если все проверки явно выполнены.
Валидатор НЕ доверяет полям metrics.json там, где их можно пересчитать
из файлов (WAV: пик, длительность; исходник: корреляция и лаг).

CLI:
  python validate_run.py --run runs/<id> [--kind auto|streaming|e2e]
                         [--min-snr 10] [--allow-missing-vision]
                         [--allow-unverified-source]
Код выхода 0 только если все проверки ok. Пишет <run>/verdict.json.
"""
import argparse
import datetime
import json
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MIN_KB = 1024
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# Латинские слова-заглушки (границы слов, чтобы не ловить «contest») и литерал «...».
PLACEHOLDER_WORDS = re.compile(r"\b(lorem|ipsum|test|example|todo|placeholder)\b", re.IGNORECASE)
KINDS = ("streaming", "e2e")
TIMING_SLACK_MS = 30_000.0
FIRST_PARTIAL_TOL_MS = 5.0
CORR_CLAIM_TOL = 0.15
LAG_CLAIM_TOL_MS = 50.0
MIN_CORR = 0.5          # справочный порог для corr_global (в критерий не входит)
MIN_CORR_PEAK = 0.6     # критерий: медиана корреляции по валидным окнам
MIN_REC_DURATION_S = 5.0
# Оконная методика: независимые такты ADC/DAC дают дрейф лага, проскоки буфера - скачки.
CORR_WIN_S = 4.0
CORR_STEP_S = 2.0
CORR_MIN_WIN = 0.3        # окна с корреляцией ниже отбрасываются
CORR_MIN_VALID_FRAC = 0.6
DRIFT_LIMIT_PPM = 500.0
DRIFT_CLAIM_TOL_PPM = 150.0
VALID_FRAC_CLAIM_TOL = 0.1
OUTLIER_MAD_K = 3.5
OUTLIER_FLOOR_SAMPLES = 4.0  # 0.25 мс при 16 кГц: ниже разрешения пика нет смысла отбрасывать
MIN_PEAK_DBFS = -50.0
SNR_FRAME_MS = 30.0
SNR_NOISE_PCT = 10.0
SNR_SIGNAL_PCT = 90.0
SNR_CLAIM_TOL_DB = 10.0
SNR_EPS = 1e-12


# ------------------------------------------------------------------ helpers
def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


def is_list(v):
    return isinstance(v, list)


def is_dict(v):
    return isinstance(v, dict)


def short(v, n=70):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def norm_text(t):
    return " ".join(t.casefold().split())


class Checks:
    def __init__(self):
        self.items = []

    def add(self, name, ok, expected, actual, detail=""):
        self.items.append({"name": name, "ok": bool(ok), "expected": expected,
                           "actual": actual, "detail": detail})
        return bool(ok)

    @property
    def all_ok(self):
        return bool(self.items) and all(c["ok"] for c in self.items)


def guarded(checks, name, fn):
    """Любое исключение внутри проверки = FAIL с причиной, а не трейсбек."""
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        checks.add(name + ":exception", False, "no exception", type(e).__name__, str(e)[:200])


def resolve_path(p, run_dir):
    """Абсолютный путь как есть; относительный - ищем в run, run/artifacts, cwd, папке скрипта, корне проекта."""
    pp = pathlib.Path(p)
    if pp.is_absolute():
        return pp if pp.exists() else None
    for base in (run_dir, run_dir / "artifacts", pathlib.Path.cwd(), HERE, HERE.parent.parent):
        cand = base / pp
        if cand.exists():
            return cand
    return None


def load_audio(path):
    """Возвращает (sr, mono float64 в [-1,1], peak_dbfs, n_frames). Бросает исключение, если не читается."""
    import numpy as np
    try:
        import scipy.io.wavfile as wavfile
        sr, data = wavfile.read(str(path))
        data = np.asarray(data)
        if data.dtype.kind == "i":
            scale = float(np.iinfo(data.dtype).max) + 1.0
            x = data.astype(np.float64) / scale
        elif data.dtype.kind == "u":
            mid = (float(np.iinfo(data.dtype).max) + 1.0) / 2.0
            x = (data.astype(np.float64) - mid) / mid
        else:
            x = data.astype(np.float64)
    except Exception:  # noqa: BLE001 - запасной путь для 24 бит, flac и т.п.
        import soundfile as sf
        x, sr = sf.read(str(path), dtype="float64", always_2d=False)
        x = np.asarray(x)
    if x.ndim == 2:
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        x = x.mean(axis=1)
    else:
        peak = float(np.max(np.abs(x))) if x.size else 0.0
    peak_db = 20.0 * math.log10(peak) if peak > 0 else -240.0
    return int(sr), x, peak_db, int(len(x))


def recompute_snr(x, sr, frame_ms=SNR_FRAME_MS, noise_pct=SNR_NOISE_PCT, signal_pct=SNR_SIGNAL_PCT):
    """Честный SNR по записи без опоры на поля metrics.json.

    Кадры frame_ms без перекрытия, энергия кадра = mean(x^2); шумовая полка = noise_pct-й процентиль
    энергий кадров, сигнал = signal_pct-й процентиль; SNR = 10*log10(signal/noise).
    Цифровой ноль не даёт inf: обе энергии ограничены снизу SNR_EPS (полная тишина -> 0 дБ).
    Возвращает (snr_db, n_frames, noise_db, signal_db).
    """
    import numpy as np
    x = np.asarray(x, dtype=np.float64)
    n = int(round(sr * frame_ms / 1000.0))
    nf = len(x) // n if n > 0 else 0
    if nf < 10:
        raise ValueError(f"слишком мало кадров для SNR: {nf}")
    e = np.mean(x[: nf * n].reshape(nf, n) ** 2, axis=1)
    noise = max(float(np.percentile(e, noise_pct)), SNR_EPS)
    signal = max(float(np.percentile(e, signal_pct)), SNR_EPS)
    return (10.0 * math.log10(signal / noise), nf,
            10.0 * math.log10(noise), 10.0 * math.log10(signal))


def recompute_corr_lag(ref, sr_ref, rec, sr_rec, max_lag_s=2.5, target_sr=16000):
    """Нормированная кросс-корреляция исходника и записи. Возвращает (corr_peak, lag_ms)."""
    import numpy as np
    import scipy.signal as sig
    from math import gcd

    def to_target(x, sr):
        if sr == target_sr:
            return x
        g = gcd(int(sr), target_sr)
        return sig.resample_poly(x, target_sr // g, int(sr) // g)

    r = to_target(ref, sr_ref)
    x = to_target(rec, sr_rec)
    if len(r) < target_sr // 2 or len(x) < target_sr // 2:
        raise ValueError("слишком короткий сигнал для корреляции")
    # ограничиваем длину опорного сегмента до 60 с, чтобы не тратить память
    r = r[: 60 * target_sr]
    pad = int(max_lag_s * target_sr)
    xp = np.concatenate([x, np.zeros(len(r) + pad)])
    corr = sig.correlate(xp, r, mode="valid", method="fft")
    cs = np.concatenate([[0.0], np.cumsum(xp * xp)])
    ex = cs[len(r):] - cs[:-len(r)]
    nc = np.abs(corr) / (np.sqrt(np.maximum(ex, 0) * float(np.sum(r * r))) + 1e-12)
    nc = nc[: pad + 1]  # лаги 0..max_lag_s
    k = int(np.argmax(nc))
    return float(nc[k]), 1000.0 * k / target_sr


def recompute_corr_lag_windowed(ref, sr_ref, rec, sr_rec, win_s=CORR_WIN_S, step_s=CORR_STEP_S,
                                min_win_corr=CORR_MIN_WIN, max_lag_s=2.5, target_sr=16000,
                                max_ref_s=120.0):
    """Оконная корреляция с линейной моделью лага (основная методика для e2e).

    Мотив: микрофон (ADC) и динамики (DAC) тактируются разными генераторами. Даже при 50 ppm
    за 40 с лаг уезжает на 2 мс, а проскок буфера даёт скачок на несколько мс. Глобальная
    корреляция на длинной записи размывается этим и падает, хотя речь слышна. Поэтому:

      1. окна win_s=4 с, шаг step_s=2 с; в каждом окне лаг ищется кросс-корреляцией (0..max_lag_s);
      2. окна с corr < min_win_corr (0.3) отбрасываются как нерелевантные;
      3. лаг моделируется линейно по времени: Theil-Sen по валидным окнам, затем отброс
         выбросов (|остаток| > 3.5 * 1.4826 * MAD, но не меньше 4 отсчётов) и повторная подгонка;
      4. corr_peak = медиана корреляции валидных окон, lag_ms = медиана локальных лагов,
         drift_ppm = наклон / target_sr * 1e6;
      5. corr_global (глобальный пик) остаётся справочным полем и критерием НЕ является.

    Возвращает dict; при <2 валидных окнах corr_peak/lag_ms/drift_ppm = None.
    """
    import numpy as np
    import scipy.signal as sig
    from scipy.stats import theilslopes

    def to_target(y, sr):
        y = np.asarray(y, dtype=np.float64)
        if sr == target_sr:
            return y
        g = math.gcd(int(sr), int(target_sr))
        return sig.resample_poly(y, target_sr // g, int(sr) // g)

    r = to_target(ref, sr_ref)[: int(max_ref_s * target_sr)]
    x = to_target(rec, sr_rec)
    w = int(round(win_s * target_sr))
    step = max(1, int(round(step_s * target_sr)))
    pad = int(round(max_lag_s * target_sr))
    if len(r) < w or len(x) < w:
        raise ValueError(f"слишком короткий сигнал для оконной корреляции: ref={len(r) / target_sr:.2f} с, "
                         f"rec={len(x) / target_sr:.2f} с, окно {win_s} с")

    # DC убираем: в MME-записи бывает постоянная составляющая
    r = r - float(np.mean(r))
    x = x - float(np.mean(x))
    cs = np.concatenate([[0.0], np.cumsum(x * x)])
    rows = []
    for s in range(0, len(r) - w + 1, step):
        seg = r[s:s + w]
        e_seg = float(np.dot(seg, seg))
        if e_seg <= 0:
            continue
        end = min(len(x), s + w + pad)   # ищем лаг 0..max_lag от начала записи
        if end - w < 1:
            continue
        c = sig.correlate(x[:end], seg, mode="valid", method="fft")
        ex = cs[w:end + 1] - cs[: end - w + 1]
        nc = np.abs(c) / (np.sqrt(np.maximum(ex, 0.0) * e_seg) + 1e-12)
        # c[k] сопоставляет x[k:k+w] с ref[s:s+w]; лаг ОТНОСИТЕЛЬНО окна = k - s (0..pad)
        lo = s
        hi = min(s + pad, len(nc) - 1)
        if hi < lo:
            continue
        k = lo + int(np.argmax(nc[lo:hi + 1]))
        rows.append({"t_s": round(s / target_sr, 3), "corr": round(float(nc[k]), 5),
                     "lag_samples": k - s, "lag_ms": round(1000.0 * (k - s) / target_sr, 3)})

    valid = [q for q in rows if q["corr"] >= min_win_corr]
    corr_g, lag_g = recompute_corr_lag(ref, sr_ref, rec, sr_rec, max_lag_s=max_lag_s,
                                       target_sr=target_sr)
    out = {"win_s": win_s, "step_s": step_s, "min_win_corr": min_win_corr,
           "n_windows": len(rows), "n_valid": len(valid),
           "valid_window_fraction": round(len(valid) / len(rows), 5) if rows else 0.0,
           "corr_global": round(corr_g, 5), "lag_global_ms": round(lag_g, 3),
           "corr_peak": None, "lag_ms": None, "drift_ppm": None,
           "drift_samples_per_s": None, "lag0_ms": None, "n_fit": 0, "dropped_as_outliers": [],
           "windows": rows}
    if len(valid) < 2:
        out["note"] = "менее 2 валидных окон: медиана, лаг и дрейф не определены"
        return out

    t = np.array([q["t_s"] for q in valid], dtype=np.float64)
    lag = np.array([q["lag_samples"] for q in valid], dtype=np.float64)
    corr = np.array([q["corr"] for q in valid], dtype=np.float64)

    slope, icpt, _, _ = theilslopes(lag, t)
    keep = np.ones(len(valid), dtype=bool)
    if len(valid) >= 4:
        resid = lag - (icpt + slope * t)
        med = float(np.median(resid))
        mad = float(np.median(np.abs(resid - med)))
        thr = max(OUTLIER_MAD_K * 1.4826 * mad, OUTLIER_FLOOR_SAMPLES)
        cand = np.abs(resid - med) <= thr
        if int(cand.sum()) >= 3:      # страховка: не оставить меньше 3 окон
            keep = cand
            dropped = [valid[i]["t_s"] for i in range(len(valid)) if not keep[i]]
            out["dropped_as_outliers"] = dropped
            out["outlier_threshold_samples"] = round(thr, 3)
    if int(keep.sum()) >= 3:
        slope, icpt, _, _ = theilslopes(lag[keep], t[keep])
        lag_med_samples = float(np.median(lag[keep]))
        used = [valid[i] for i in range(len(valid)) if keep[i]]
    else:
        lag_med_samples = float(np.median(lag))
        used = valid
    out.update({"corr_peak": round(float(np.median(corr)), 5),
                "lag_ms": round(1000.0 * lag_med_samples / target_sr, 3),
                "drift_ppm": round(float(slope) / target_sr * 1e6, 3),
                "drift_samples_per_s": round(float(slope), 5),
                "lag0_ms": round(1000.0 * float(icpt) / target_sr, 3),
                "n_fit": len(used), "fit_window_t_s": [q["t_s"] for q in used]})
    return out


# ------------------------------------------------------------------ structure
def required_schema(kind):
    s = {
        "kind": is_str, "run_id": is_str, "created": is_str, "simulated": is_bool,
        "engine": is_str,
        "source": is_dict, "source.type": is_str, "source.path": is_str, "source.duration_s": is_num,
        "partial_count": is_int, "final_count": is_int, "first_partial_ms": is_num,
        "finals": is_list, "partials": is_list,
        "timing": is_dict, "timing.p50_ms": is_num, "timing.p95_ms": is_num,
    }
    if kind == "e2e":
        s.update({"audio": is_dict, "audio.recording_path": is_str, "audio.snr_db": is_num,
                  "audio.corr_peak": is_num, "audio.lag_ms": is_num,
                  "audio.corr_global": is_num, "audio.drift_ppm": is_num,
                  "audio.valid_window_fraction": is_num})
    return s


def get_path(d, dotted):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def check_structure(m, kind, checks):
    problems = []
    for name, pred in required_schema(kind).items():
        found, val = get_path(m, name)
        if not found:
            problems.append(f"missing_field:{name}")
            checks.add(f"missing_field:{name}", False, "present", "absent")
        elif not pred(val):
            problems.append(f"bad_type:{name}")
            checks.add(f"bad_type:{name}", False, pred.__name__.replace("is_", ""), type(val).__name__,
                       short(val))
    if is_list(m.get("finals")):
        for i, f in enumerate(m["finals"]):
            if not is_dict(f):
                problems.append(f"bad_type:finals[{i}]")
                checks.add(f"bad_type:finals[{i}]", False, "dict", type(f).__name__)
                continue
            for k, pred in (("text", is_str), ("t_ms", is_num), ("source_end_ms", is_num)):
                if k not in f:
                    problems.append(f"missing_field:finals[{i}].{k}")
                    checks.add(f"missing_field:finals[{i}].{k}", False, "present", "absent")
                elif not pred(f[k]):
                    problems.append(f"bad_type:finals[{i}].{k}")
                    checks.add(f"bad_type:finals[{i}].{k}", False, pred.__name__, type(f[k]).__name__)
    if is_list(m.get("partials")):
        for i, p in enumerate(m["partials"]):
            if not is_dict(p):
                problems.append(f"bad_type:partials[{i}]")
                checks.add(f"bad_type:partials[{i}]", False, "dict", type(p).__name__)
                continue
            for k, pred in (("text", is_str), ("t_ms", is_num)):
                if k not in p:
                    problems.append(f"missing_field:partials[{i}].{k}")
                    checks.add(f"missing_field:partials[{i}].{k}", False, "present", "absent")
                elif not pred(p[k]):
                    problems.append(f"bad_type:partials[{i}].{k}")
                    checks.add(f"bad_type:partials[{i}].{k}", False, pred.__name__, type(p[k]).__name__)
        if len(problems) > 40:
            pass
    checks.add("structure", not problems, "no missing/bad fields",
               "ok" if not problems else f"{len(problems)} problems", "; ".join(problems[:10]))
    return not problems


# ------------------------------------------------------------------ semantic checks
def check_basic(m, run_dir, checks):
    checks.add("simulated_is_false", m["simulated"] is False, False, m["simulated"],
               "строго bool false; true = симуляция, не результат")
    checks.add("run_id_matches_dir", m["run_id"] == run_dir.name, run_dir.name, m["run_id"],
               "защита от копии metrics.json из чужого прогона")
    try:
        datetime.datetime.fromisoformat(m["created"].replace("Z", "+00:00"))
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    checks.add("created_iso8601", ok, "ISO8601", short(m["created"]))
    checks.add("engine_nonempty", bool(m["engine"].strip()), "non-empty", short(m["engine"]))
    dur = m["source"]["duration_s"]
    checks.add("source_duration_positive", dur > 0, ">0", dur)


def check_counts(m, checks):
    finals, partials = m["finals"], m["partials"]
    checks.add("partial_count_gt_0", m["partial_count"] > 0, ">0", m["partial_count"])
    checks.add("final_count_ge_1", m["final_count"] >= 1, ">=1", m["final_count"])
    checks.add("partial_count_matches_list", m["partial_count"] == len(partials), len(partials),
               m["partial_count"], "счётчик должен совпадать с длиной списка")
    checks.add("final_count_matches_list", m["final_count"] == len(finals), len(finals),
               m["final_count"], "счётчик должен совпадать с длиной списка")


def check_texts(m, checks):
    finals, partials = m["finals"], m["partials"]
    texts = [f["text"] for f in finals]
    nonempty = [t for t in texts if t.strip()]
    checks.add("finals_nonempty", bool(texts) and len(nonempty) == len(texts), "all non-empty",
               f"{len(nonempty)}/{len(texts)} non-empty")
    cyr = [t for t in texts if CYRILLIC.search(t)]
    checks.add("finals_cyrillic", bool(texts) and len(cyr) == len(texts), "all contain cyrillic",
               f"{len(cyr)}/{len(texts)}")
    uniq = len({norm_text(t) for t in nonempty})
    total = sum(len(t.strip()) for t in texts)
    if m["final_count"] == 1:
        # один финал: достаточно одного непустого уникального текста; длину проверяет finals_total_len (>=10)
        need = 1
        detail = "final_count==1: достаточно unique==1 (и суммарная длина >=10 ниже)"
        ok_distinct = uniq == 1
    else:
        need = max(2, m["final_count"] - 1)
        detail = "уникальных >= max(2, final_count-1)"
        ok_distinct = uniq >= need
    checks.add("finals_distinct", ok_distinct, f">={need} unique", uniq, detail)
    checks.add("finals_total_len", total >= 10, ">=10 chars", total)
    ptexts = [p["text"] for p in partials if p["text"].strip()]
    puniq = len({norm_text(t) for t in ptexts})
    checks.add("partials_distinct", puniq >= 2, ">=2 unique non-empty partials", puniq,
               "поток partial с одним текстом не доказывает инкрементальность")
    bad = []
    for label, items in (("final", texts), ("partial", [p["text"] for p in partials])):
        for i, t in enumerate(items):
            if "..." in t or "…" in t:
                bad.append(f"{label}[{i}]:'...'")
            mm = PLACEHOLDER_WORDS.search(t)
            if mm:
                bad.append(f"{label}[{i}]:{mm.group(0).lower()}")
    checks.add("no_placeholder_text", not bad, "no lorem/test/example/.../TODO/placeholder",
               "none" if not bad else f"{len(bad)} hits", "; ".join(bad[:8]))
    same = len(texts) > 1 and len({norm_text(t) for t in texts}) == 1
    checks.add("not_all_finals_identical", not same, "not identical", "identical" if same else "varied")


def check_timing(m, checks):
    dur_ms = m["source"]["duration_s"] * 1000.0
    cap = dur_ms + TIMING_SLACK_MS
    checks.add("first_partial_gt_0", m["first_partial_ms"] > 0, ">0", m["first_partial_ms"])
    p50, p95 = m["timing"]["p50_ms"], m["timing"]["p95_ms"]
    checks.add("p50_gt_0", p50 > 0, ">0", p50)
    checks.add("p95_ge_p50", p95 >= p50, ">=p50", f"p50={p50} p95={p95}")
    for label, items in (("finals", m["finals"]), ("partials", m["partials"])):
        ts = [x["t_ms"] for x in items]
        mono = all(b >= a for a, b in zip(ts, ts[1:]))
        checks.add(f"{label}_t_ms_nondecreasing", bool(ts) and mono, "non-decreasing",
                   "ok" if mono and ts else ("empty" if not ts else "decreases"))
        checks.add(f"{label}_t_ms_range", bool(ts) and min(ts) >= 0 and max(ts) <= cap,
                   f"0..{cap:.0f} ms (duration+30s)", f"min={min(ts) if ts else None} max={max(ts) if ts else None}",
                   "защита от выдуманных чисел")
    if m["partials"]:
        fp = min(p["t_ms"] for p in m["partials"])
        checks.add("first_partial_matches_list", abs(fp - m["first_partial_ms"]) <= FIRST_PARTIAL_TOL_MS,
                   f"first_partial_ms ~ min(partials.t_ms) +-{FIRST_PARTIAL_TOL_MS} ms",
                   f"field={m['first_partial_ms']} list_min={fp}")
    se = [f["source_end_ms"] for f in m["finals"]]
    ok = bool(se) and all(b >= a for a, b in zip(se, se[1:])) and min(se) >= 0 and max(se) <= dur_ms + 1000.0
    checks.add("finals_source_end_range", ok, f"non-decreasing, 0..{dur_ms + 1000:.0f} ms",
               f"min={min(se) if se else None} max={max(se) if se else None}")


def check_e2e(m, run_dir, checks, min_snr, allow_unverified_source, extras=None):
    a = m["audio"]
    extras = extras if extras is not None else {}
    extras["snr_db_claimed"] = a["snr_db"]
    extras["snr_db_recomputed"] = None
    checks.add("snr_db_min", a["snr_db"] >= min_snr, f">={min_snr}", a["snr_db"],
               "заявленное значение из metrics.json; честность проверяет snr_recomputed_consistent")
    checks.add("corr_peak_min", MIN_CORR_PEAK <= a["corr_peak"] <= 1.0001, f">={MIN_CORR_PEAK}", a["corr_peak"],
               "медиана корреляции по валидным окнам 4 с; глобальный пик критерием не является")
    checks.add("drift_ppm_limit", abs(a["drift_ppm"]) < DRIFT_LIMIT_PPM, f"|drift| < {DRIFT_LIMIT_PPM} ppm",
               a["drift_ppm"], "наклон лага по окнам: независимые такты ADC/DAC")
    checks.add("valid_window_fraction_min", a["valid_window_fraction"] >= CORR_MIN_VALID_FRAC,
               f">={CORR_MIN_VALID_FRAC}", a["valid_window_fraction"],
               "доля окон с corr>=0.3 от всех окон 4 с / шаг 2 с")
    checks.add("lag_ms_range", 0 <= a["lag_ms"] <= 2000, "0..2000", a["lag_ms"])
    rec_path = resolve_path(a["recording_path"], run_dir)
    checks.add("recording_exists", rec_path is not None and rec_path.is_file(), "file exists",
               str(rec_path) if rec_path else "missing", a["recording_path"])
    if rec_path is None or not rec_path.is_file():
        return
    checks.add("recording_size_gt_1kb", rec_path.stat().st_size > MIN_KB, f">{MIN_KB}", rec_path.stat().st_size)
    try:
        sr, x, peak_db, n = load_audio(rec_path)
    except Exception as e:  # noqa: BLE001
        checks.add("recording_readable", False, "readable wav", type(e).__name__, str(e)[:200])
        return
    dur = n / sr if sr else 0.0
    checks.add("recording_readable", True, "readable wav", f"sr={sr} n={n}")
    # SNR пересчитывается из WAV: кадры 30 мс, шум = p10 энергий, сигнал = p90 энергий
    try:
        snr_re, nfr, noise_db, sig_db = recompute_snr(x, sr)
        extras["snr_db_recomputed"] = round(snr_re, 3)
        claimed = a["snr_db"]
        ok_cons = (claimed <= snr_re + SNR_CLAIM_TOL_DB) and (snr_re >= min_snr)
        checks.add("snr_recomputed_consistent", ok_cons,
                   f"claimed<=recomputed+{SNR_CLAIM_TOL_DB:g} and recomputed>={min_snr:g}",
                   f"claimed={claimed:.2f} recomputed={snr_re:.2f}",
                   f"p10={noise_db:.1f} dB, p90={sig_db:.1f} dB, frames={nfr} x {SNR_FRAME_MS:g} ms; "
                   f"claimed-recomputed={claimed - snr_re:+.2f} дБ")
    except Exception as e:  # noqa: BLE001
        checks.add("snr_recomputed_consistent", False, "snr recomputable", type(e).__name__, str(e)[:200])
    checks.add("recording_duration_gt_5s", dur > MIN_REC_DURATION_S, f">{MIN_REC_DURATION_S} s", round(dur, 3))
    checks.add("recording_peak_dbfs", peak_db > MIN_PEAK_DBFS, f">{MIN_PEAK_DBFS} dBFS",
               round(peak_db, 2), "пересчитано из файла, а не из metrics.json")
    sdur = m["source"]["duration_s"]
    checks.add("recording_covers_source", dur >= 0.8 * sdur, f">=0.8*source ({0.8 * sdur:.1f} s)", round(dur, 3))
    # независимый пересчёт корреляции и лага по исходнику
    src = resolve_path(m["source"]["path"], run_dir)
    src_ok = False
    if src is not None and src.is_file():
        try:
            sr2, ref, _, n2 = load_audio(src)
            wres = recompute_corr_lag_windowed(ref, sr2, x, sr)
            src_ok = True
        except Exception as e:  # noqa: BLE001
            checks.add("source_recheck_readable", allow_unverified_source, "readable source wav",
                       type(e).__name__, str(e)[:200] + (" (разрешено --allow-unverified-source)" if allow_unverified_source else ""))
    else:
        checks.add("source_recheck_available", allow_unverified_source, "source file readable",
                   "missing", "корреляция не пересчитана" + (" (разрешено --allow-unverified-source)" if allow_unverified_source else ""))
    if src_ok:
        extras["corr_peak_recomputed"] = wres["corr_peak"]
        extras["corr_global_recomputed"] = wres["corr_global"]
        extras["drift_ppm_recomputed"] = wres["drift_ppm"]
        extras["valid_window_fraction_recomputed"] = wres["valid_window_fraction"]
        extras["lag_ms_recomputed"] = wres["lag_ms"]
        extras["corr_windows"] = {"n_windows": wres["n_windows"], "n_valid": wres["n_valid"],
                                  "n_fit": wres["n_fit"], "win_s": wres["win_s"], "step_s": wres["step_s"],
                                  "min_win_corr": wres["min_win_corr"],
                                  "dropped_as_outliers": wres["dropped_as_outliers"]}
        # та же формула, что в duplex_e2e: окна 4 с / шаг 2 с, отброс corr<0.3, Theil-Sen + отброс выбросов
        checks.add("corr_windows_enough", wres["n_windows"] >= 2 and wres["n_valid"] >= 2,
                   "n_windows>=2 and n_valid>=2",
                   f"n_windows={wres['n_windows']} n_valid={wres['n_valid']}",
                   "на короткой записи медиана и дрейф не определены")
        if wres["corr_peak"] is None:
            for name, expected in (("corr_recomputed_min", f">={MIN_CORR_PEAK}"),
                                   ("corr_claim_consistent", f"|claim-recomputed|<={CORR_CLAIM_TOL}"),
                                   ("lag_claim_consistent", f"|claim-recomputed|<={LAG_CLAIM_TOL_MS} ms"),
                                   ("drift_claim_consistent", f"|claim-recomputed|<={DRIFT_CLAIM_TOL_PPM} ppm"),
                                   ("valid_fraction_claim_consistent",
                                    f"|claim-recomputed|<={VALID_FRAC_CLAIM_TOL}")):
                checks.add(name, False, expected, "не определено (мало валидных окон)")
        else:
            checks.add("corr_recomputed_min", wres["corr_peak"] >= MIN_CORR_PEAK, f">={MIN_CORR_PEAK}",
                       wres["corr_peak"], "пересчитано из source.path и записи оконной методикой")
            checks.add("corr_claim_consistent", abs(wres["corr_peak"] - a["corr_peak"]) <= CORR_CLAIM_TOL,
                       f"|claim-recomputed|<={CORR_CLAIM_TOL}",
                       f"claim={a['corr_peak']} recomputed={wres['corr_peak']:.4f}")
            checks.add("corr_global_claim_consistent",
                       abs(wres["corr_global"] - a["corr_global"]) <= CORR_CLAIM_TOL,
                       f"|claim-recomputed|<={CORR_CLAIM_TOL}",
                       f"claim={a['corr_global']} recomputed={wres['corr_global']:.4f}",
                       "справочное поле: критерием не является, но заявленное обязано совпадать с пересчётом")
            checks.add("lag_claim_consistent", abs(wres["lag_ms"] - a["lag_ms"]) <= LAG_CLAIM_TOL_MS,
                       f"|claim-recomputed|<={LAG_CLAIM_TOL_MS} ms",
                       f"claim={a['lag_ms']} recomputed={wres['lag_ms']:.1f}")
            checks.add("drift_claim_consistent", abs(wres["drift_ppm"] - a["drift_ppm"]) <= DRIFT_CLAIM_TOL_PPM,
                       f"|claim-recomputed|<={DRIFT_CLAIM_TOL_PPM} ppm",
                       f"claim={a['drift_ppm']} recomputed={wres['drift_ppm']:.1f}")
            checks.add("valid_fraction_claim_consistent",
                       abs(wres["valid_window_fraction"] - a["valid_window_fraction"]) <= VALID_FRAC_CLAIM_TOL,
                       f"|claim-recomputed|<={VALID_FRAC_CLAIM_TOL}",
                       f"claim={a['valid_window_fraction']} recomputed={wres['valid_window_fraction']:.3f}")


def check_artifacts(m, kind, run_dir, checks):
    art = run_dir / "artifacts"
    checks.add("artifacts_dir_exists", art.is_dir(), "dir", "present" if art.is_dir() else "missing")
    if kind == "streaming":
        for name in ("screenshot.png", "page.html"):
            p = art / name
            ok = p.is_file() and p.stat().st_size > MIN_KB
            checks.add(f"artifact:{name}", ok, f"exists, >{MIN_KB} B",
                       p.stat().st_size if p.is_file() else "missing")
        html = art / "page.html"
        if html.is_file():
            try:
                txt = html.read_text(encoding="utf-8", errors="replace")
                checks.add("page_html_cyrillic", bool(CYRILLIC.search(txt)), "contains cyrillic",
                           "yes" if CYRILLIC.search(txt) else "no")
            except Exception as e:  # noqa: BLE001
                checks.add("page_html_cyrillic", False, "readable", type(e).__name__)
    shot = art / "screenshot.png"
    if shot.is_file():
        from check_screenshot import check_image
        ok, values, sub = check_image(shot)
        failed = [c["name"] for c in sub if not c["ok"]]
        checks.add("screenshot_not_blank", ok, "check_screenshot pass",
                   "pass" if ok else "fail: " + ",".join(failed),
                   f"bands={values.get('text_like_bands')} std={values.get('pixel_std')}")
    elif kind == "e2e":
        pass  # для e2e скриншот не обязателен


def check_log(run_dir, checks):
    lg = run_dir / "log.txt"
    if not lg.is_file():
        checks.add("log_exists_nonempty", False, "non-empty file", "missing")
        return
    txt = lg.read_text(encoding="utf-8", errors="replace")
    checks.add("log_exists_nonempty", bool(txt.strip()), "non-empty file", f"{len(txt)} chars")
    checks.add("log_no_traceback", "Traceback (most recent call last)" not in txt, "no traceback",
               "traceback" if "Traceback (most recent call last)" in txt else "none")


# ------------------------------------------------------------------ main
def validate(run_dir, kind_arg="auto", min_snr=10.0, allow_missing_vision=False, allow_unverified_source=False):
    run_dir = pathlib.Path(run_dir)
    checks = Checks()
    extras = {}
    kind = None
    mpath = run_dir / "metrics.json"
    m = None
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
        if not isinstance(m, dict):
            m = None
            raise ValueError("корень metrics.json не объект")
        checks.add("metrics_readable", True, "valid json object", "ok")
    except Exception as e:  # noqa: BLE001
        checks.add("metrics_readable", False, "valid json object", type(e).__name__, str(e)[:200])

    if m is not None:
        mk = m.get("kind")
        if mk in KINDS:
            kind = mk
        checks.add("kind_valid", mk in KINDS, "streaming|e2e", short(mk))
        if kind_arg != "auto":
            checks.add("kind_matches_arg", kind == kind_arg, kind_arg, short(mk),
                       "--kind не совпал с metrics.kind")
            if kind is None:
                kind = kind_arg if kind_arg in KINDS else None
        if kind is not None:
            if check_structure(m, kind, checks):
                guarded(checks, "basic", lambda: check_basic(m, run_dir, checks))
                guarded(checks, "counts", lambda: check_counts(m, checks))
                guarded(checks, "texts", lambda: check_texts(m, checks))
                guarded(checks, "timing", lambda: check_timing(m, checks))
                if kind == "e2e":
                    guarded(checks, "e2e", lambda: check_e2e(m, run_dir, checks, min_snr, allow_unverified_source, extras))
    if kind is not None:
        guarded(checks, "artifacts", lambda: check_artifacts(m or {}, kind, run_dir, checks))
    guarded(checks, "log", lambda: check_log(run_dir, checks))

    ok = checks.all_ok
    verdict = {"layer": 1, "run_id": (m or {}).get("run_id") if isinstance((m or {}).get("run_id"), str) else run_dir.name,
               "run_dir_name": run_dir.name, "kind": kind, "pass": ok,
               "allow_missing_vision": bool(allow_missing_vision),
               "min_snr": min_snr, **extras, "checks": checks.items,
               "created": datetime.datetime.now().astimezone().isoformat()}
    return verdict


def print_table(checks):
    w = max([len("check")] + [len(c["name"]) for c in checks])
    print(f"{'check':<{w}} | {'res':<4} | {'expected':<34} | actual")
    print("-" * (w + 60))
    for c in checks:
        print(f"{c['name']:<{w}} | {'ok' if c['ok'] else 'FAIL':<4} | {short(c['expected'], 34):<34} | {short(c['actual'], 50)}")
        if not c["ok"] and c.get("detail"):
            print(f"{'':<{w}}   -> {short(c['detail'], 110)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Слой 1: валидатор прогона (по умолчанию FAIL)")
    ap.add_argument("--run", required=True, help="путь к runs/<id>")
    ap.add_argument("--kind", default="auto", choices=["auto", "streaming", "e2e"])
    ap.add_argument("--min-snr", type=float, default=10.0)
    ap.add_argument("--allow-missing-vision", action="store_true",
                    help="записать в verdict.json: gate не требует vision-review для streaming")
    ap.add_argument("--allow-unverified-source", action="store_true",
                    help="e2e: не падать, если source.path нельзя прочитать и корреляцию нельзя пересчитать")
    a = ap.parse_args(argv)
    run_dir = pathlib.Path(a.run)
    if not run_dir.is_dir():
        print(f"FAIL: run dir не существует: {run_dir}")
        return 1
    try:
        verdict = validate(run_dir, a.kind, a.min_snr, a.allow_missing_vision, a.allow_unverified_source)
    except Exception as e:  # noqa: BLE001
        verdict = {"layer": 1, "run_id": run_dir.name, "pass": False, "allow_missing_vision": False,
                   "checks": [{"name": "validator_crash", "ok": False, "expected": "no crash",
                               "actual": type(e).__name__, "detail": str(e)[:300]}],
                   "created": datetime.datetime.now().astimezone().isoformat()}
    try:
        (run_dir / "verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        verdict["pass"] = False
        print(f"FAIL: не удалось записать verdict.json: {e}")
    print_table(verdict["checks"])
    failed = [c["name"] for c in verdict["checks"] if not c["ok"]]
    print("LAYER1 PASS" if verdict["pass"] else "LAYER1 FAIL: " + ", ".join(failed))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
