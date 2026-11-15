"""Диагностика низкой корреляции duplex-прогона: дрейф лага (расхождение тактовых частот микрофона и динамиков).

Берёт <run>/artifacts/source_played.wav и recording.wav, считает лаг и корреляцию в окнах 4 с (шаг 2 с),
устойчиво (Theil-Sen по окнам с corr>=0.6) оценивает наклон лага и проверяет гипотезу: если скомпенсировать
линейный дрейф, глобальная корреляция растёт. Это ДИАГНОСТИКА причины blocked_low_correlation, а не метрика прогона:
metrics.json она не меняет и не создаёт. Пишет <run>/drift_analysis.json.

CLI: python diag_drift.py --run runs/<id>
"""
import argparse
import json
import pathlib
import sys

import numpy as np
import scipy.signal as sig
import soundfile as sf
from scipy.stats import theilslopes

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from duplex_e2e import xcorr_lag  # noqa: E402

WIN_S, STEP_S, SEARCH_S, MIN_WIN_CORR = 4.0, 2.0, 0.1, 0.6


def local_lag(play, rec, s, g, sr):
    w = int(WIN_S * sr)
    r = play[s:s + w].astype(np.float64)
    lo = max(s + g - int(SEARCH_S * sr), 0)
    x = rec[lo:s + g + int(SEARCH_S * sr) + w].astype(np.float64)
    if len(x) < len(r):
        return None
    c = sig.correlate(x, r, mode="valid", method="fft")
    cs = np.concatenate([[0.0], np.cumsum(x * x)])
    ex = cs[len(r):] - cs[:-len(r)]
    nc = np.abs(c) / (np.sqrt(np.maximum(ex, 0) * np.sum(r * r)) + 1e-12)
    k = int(np.argmax(nc))
    return float(nc[k]), lo + k - s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    run = pathlib.Path(a.run)
    play, sr = sf.read(str(run / "artifacts" / "source_played.wav"), dtype="float32")
    rec, sr2 = sf.read(str(run / "artifacts" / "recording.wav"), dtype="float32")
    assert sr == sr2
    corr0, g = xcorr_lag(play, rec, sr)
    rows = []
    for s in range(0, len(play) - int(WIN_S * sr) + 1, int(STEP_S * sr)):
        r = local_lag(play, rec, s, g, sr)
        if r:
            rows.append({"t_s": s / sr, "corr": round(r[0], 4), "lag_samples": int(r[1]), "lag_ms": round(1000.0 * r[1] / sr, 2)})
    good = [r for r in rows if r["corr"] >= MIN_WIN_CORR]
    out = {"global_corr_peak": corr0, "global_lag_samples": g, "windows": rows, "n_windows": len(rows),
           "n_windows_corr_ge_0.6": len(good), "win_s": WIN_S, "step_s": STEP_S,
           "windows_corr_median": float(np.median([r["corr"] for r in rows])) if rows else None,
           "note": "ДИАГНОСТИКА причины blocked_low_correlation, не метрика прогона"}
    if len(good) >= 4:
        t = np.array([r["t_s"] for r in good])
        l = np.array([r["lag_samples"] for r in good], dtype=float)
        slope, icpt, _, _ = theilslopes(l, t)  # сэмплов лага на секунду
        d = slope / sr  # безразмерный дрейф
        out["drift"] = {"slope_samples_per_s": float(slope), "ppm": float(d * 1e6), "lag0_samples": float(icpt),
                        "total_drift_samples_over_play": float(slope * len(play) / sr),
                        "total_drift_ms_over_play": float(1000.0 * slope * len(play) / sr / sr)}
        n = np.arange(len(play))
        pos = icpt + n * (1.0 + d)
        ok = pos < len(rec) - 1
        comp = np.interp(pos[ok], np.arange(len(rec)), rec.astype(np.float64))
        r = play[: ok.sum()].astype(np.float64)
        nc = float(np.abs(np.dot(comp, r)) / (np.sqrt(np.dot(comp, comp) * np.dot(r, r)) + 1e-12))
        out["corr_after_linear_drift_compensation_lag0"] = nc
        out["hypothesis_note"] = ("корреляция после линейной компенсации дрейфа (скалярное произведение при лаге 0 по "
                                  "перераспределённой записи); сравнить с global_corr_peak")
    # санитарная проверка: есть ли в записи речь (RMS окон речи vs пауз) при лаге, взятом по медиане хороших окон
    info_p = run / "source_info.json"
    if good and info_p.is_file():
        from duplex_e2e import windows_snr
        import validate_run
        clips = json.loads(info_p.read_text(encoding="utf-8"))["clips"]
        lag_ms = float(np.median([r["lag_ms"] for r in good]))
        ws = windows_snr(rec, sr, lag_ms, clips, len(rec) / sr)
        snr_p, _, _, _ = validate_run.recompute_snr(rec.astype(np.float64), sr)
        out["sanity"] = {"lag_ms_used_median_good_windows": lag_ms, "speech_rms_dbfs": ws["speech_rms_dbfs"],
                         "pause_rms_dbfs": ws["pause_rms_dbfs"], "snr_windows_db": ws["snr_db"],
                         "snr_p90_p10_db": snr_p, "per_clip_speech_rms_dbfs": ws["per_clip_speech_rms_dbfs"],
                         "note": "диагностика; в metrics.json не попадает (прогон blocked)"}
    (run / "drift_analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(f"t={r['t_s']:5.1f}s corr={r['corr']:.3f} lag={r['lag_samples']} ({r['lag_ms']} ms)")
    print(json.dumps({k: v for k, v in out.items() if k != "windows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
