"""Acoustic loopback self-test: play a short quiet tone on default output,
record on default input simultaneously, measure SNR / lag / correlation.

Exit codes: 0 ok, 2 blocked_no_device, 3 blocked_low_snr, 4 blocked_no_signal.
"""
import datetime
import json
import pathlib
import platform
import sys

import numpy as np
import scipy
import scipy.io.wavfile as wavfile
import scipy.signal as sig
import sounddevice as sd

OUT = pathlib.Path(__file__).resolve().parent / "out"
FREQ = 440.0
DUR = 0.6
LEVEL_DBFS = -25.0
FADE = 0.020
BLOCK = 1024
PAD = 0.6  # silence before/after tone (s)
SNR_MIN = 10.0
PEAK_MIN = -50.0
EXIT = {"ok": 0, "blocked_no_device": 2, "blocked_low_snr": 3, "blocked_no_signal": 4}


def db(x, eps=1e-12):
    return 10.0 * np.log10(max(float(x), eps))


def rms_db(x):
    return db(np.mean(np.square(x))) if len(x) else float("nan")


def finish(res):
    OUT.mkdir(parents=True, exist_ok=True)
    res["timestamp"] = datetime.datetime.now().astimezone().isoformat()
    res["versions"] = {"sounddevice": sd.__version__, "numpy": np.__version__,
                       "scipy": scipy.__version__, "python": platform.python_version()}
    res["os"] = platform.platform()
    (OUT / "selftest.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return EXIT[res["status"]]


def main():
    try:
        din, dout = sd.default.device
        if din is None or din < 0 or dout is None or dout < 0:
            raise RuntimeError("no default device")
        di = sd.query_devices(din)
        do = sd.query_devices(dout)
        if di["max_input_channels"] < 1 or do["max_output_channels"] < 1:
            raise RuntimeError("default device has no channels")
    except Exception as e:  # noqa: BLE001
        return finish({"status": "blocked_no_device", "error": str(e)})

    base = {
        "input_device": {"index": din, "name": di["name"],
                         "max_input_channels": di["max_input_channels"],
                         "default_samplerate": di["default_samplerate"]},
        "output_device": {"index": dout, "name": do["name"],
                          "max_output_channels": do["max_output_channels"],
                          "default_samplerate": do["default_samplerate"]},
        "tone": {"freq_hz": FREQ, "dur_s": DUR, "level_dbfs": LEVEL_DBFS,
                 "fade_ms": FADE * 1000},
        "blocksize": BLOCK,
    }

    # pick sample rate: 48000, else fall back to input device default
    sr = 48000
    try:
        sd.check_input_settings(device=din, samplerate=sr, channels=1, dtype="float32")
        sd.check_output_settings(device=dout, samplerate=sr, channels=1, dtype="float32")
        sr_note = "48000 supported"
    except Exception as e:  # noqa: BLE001
        sr = int(di["default_samplerate"])
        sr_note = f"48000 not supported ({e}); fallback to {sr}"
    base["sr"] = sr
    base["sr_note"] = sr_note

    # reference tone
    n_tone = int(DUR * sr)
    t = np.arange(n_tone) / sr
    amp = 10 ** (LEVEL_DBFS / 20) * np.sqrt(2)  # -25 dBFS RMS
    tone = (amp * np.sin(2 * np.pi * FREQ * t)).astype(np.float32)
    nf = int(FADE * sr)
    ramp = np.linspace(0, 1, nf, dtype=np.float32)
    tone[:nf] *= ramp
    tone[-nf:] *= ramp[::-1]
    n_pad = int(PAD * sr)
    play = np.concatenate([np.zeros(n_pad, np.float32), tone,
                           np.zeros(n_pad, np.float32)])[:, None]
    total = len(play)
    rec = np.zeros((total, 1), np.float32)
    pos = {"i": 0}

    def cb(indata, outdata, frames, time_info, status):
        i = pos["i"]
        n = min(frames, total - i)
        outdata[:] = 0
        if n > 0:
            outdata[:n] = play[i:i + n]
            rec[i:i + n] = indata[:n]
        pos["i"] = i + frames
        if i + frames >= total:
            raise sd.CallbackStop

    try:
        with sd.Stream(device=(din, dout), samplerate=sr, blocksize=BLOCK,
                       channels=(1, 1), dtype="float32", callback=cb) as st:
            base["stream_latency_s"] = list(st.latency) if hasattr(st.latency, "__iter__") else st.latency
            sd.sleep(int((total / sr + 0.5) * 1000))
    except Exception as e:  # noqa: BLE001
        base.update({"status": "blocked_no_device", "error": f"stream failed: {e}"})
        return finish(base)

    x = rec[:, 0].astype(np.float64)
    OUT.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(OUT / "selftest_recording.wav"), sr,
                  (np.clip(x, -1, 1) * 32767).astype(np.int16))

    # lag via cross-correlation with reference tone (full play signal)
    ref = tone.astype(np.float64)
    corr = sig.correlate(x, ref, mode="valid", method="fft")
    # normalise by local energy of x and energy of ref
    cs = np.concatenate([[0.0], np.cumsum(x * x)])
    ex = cs[len(ref):] - cs[:-len(ref)]
    nc = np.abs(corr) / (np.sqrt(ex * np.sum(ref * ref)) + 1e-12)
    k = int(np.argmax(nc))
    lag_samples = k - n_pad  # recording offset relative to expected tone start
    corr_peak = float(nc[k])

    # windows: tone window at detected position, noise windows before/after
    s0 = k
    s1 = k + n_tone
    sig_w = x[s0:s1]
    pre = x[max(0, s0 - int(0.4 * sr)):max(0, s0 - int(0.05 * sr))]
    post = x[min(len(x), s1 + int(0.05 * sr)):min(len(x), s1 + int(0.4 * sr))]
    noise = np.concatenate([pre, post])
    e_sig = float(np.mean(sig_w ** 2)) if len(sig_w) else 0.0
    e_noise = float(np.mean(noise ** 2)) if len(noise) else 0.0
    snr = db(e_sig) - db(e_noise)  # (tone+noise power) vs noise power
    peak = db(np.max(np.abs(x)) ** 2) if np.max(np.abs(x)) > 0 else -240.0

    if peak <= PEAK_MIN:
        status = "blocked_no_signal"
    elif snr >= SNR_MIN:
        status = "ok"
    else:
        status = "blocked_low_snr"

    base.update({
        "status": status,
        "rms_db_in": rms_db(play[:, 0]),
        "rms_db_out_recording": rms_db(x),
        "rms_db_tone_window_recording": db(e_sig),
        "rms_db_noise_windows_recording": db(e_noise),
        "peak_dbfs_recording": peak,
        "snr_db": snr,
        "lag_samples": int(lag_samples),
        "lag_ms": 1000.0 * lag_samples / sr,
        "corr_peak": corr_peak,
        "n_samples_in": int(len(play)),
        "n_samples_out": int(len(x)),
        "notes": "rms_db_in = RMS of whole played buffer incl. silence; tone-only RMS is "
                 "-25 dBFS nominal. lag_ms is relative to the nominal tone start in the "
                 "played buffer (includes driver in+out latency and acoustic path).",
    })
    rc = finish(base)
    if status != "ok":
        print("\nDIAGNOSTICS:", file=sys.stderr)
        print(f"  input : [{din}] {di['name']} (max_in={di['max_input_channels']})", file=sys.stderr)
        print(f"  output: [{dout}] {do['name']}", file=sys.stderr)
        print(f"  rms_rec={rms_db(x):.1f} dB, peak={peak:.1f} dBFS, snr={snr:.1f} dB, corr={corr_peak:.3f}", file=sys.stderr)
        print("  causes: mic muted / wrong default input / disabled in Windows mixer / "
              "privacy settings block mic / AGC or noise suppression / speakers muted or "
              "output goes to other device (Bluetooth, HDMI).", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
