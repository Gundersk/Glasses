"""Самотест приёмки: фикстуры -> validate_run / check_dom / check_screenshot / gate.

Все фикстуры СИНТЕТИЧЕСКИЕ (генерируются здесь в fixtures/_generated/) и нужны только чтобы
проверить, что валидатор ловит ложный PASS. Они не являются результатами экспериментов,
хотя содержат `"simulated": false` (иначе нельзя проверить остальные правила).

Код выхода 0 только если все ожидания совпали.
"""
import copy
import datetime
import hashlib
import http.server
import json
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time

import numpy as np
import scipy.io.wavfile as wavfile
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
GEN = HERE / "fixtures" / "_generated"
PY = sys.executable
ENV_UTF8 = {"PYTHONUTF8": "1"}

FINALS = ["добрый день коллеги", "сегодня мы обсуждаем систему субтитров",
          "задержка должна быть небольшой", "спасибо за внимание"]
PARTIALS = ["добрый", "добрый день", "добрый день кол", "добрый день коллеги", "сегодня",
            "сегодня мы обсуждаем", "задержка должна", "задержка должна быть небольшой"]


# ------------------------------------------------------------------ генерация
def now():
    return datetime.datetime.now().astimezone().isoformat()


def write_wav(path, x, sr=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), sr, (np.clip(x, -1, 1) * 32767).astype(np.int16))


def make_source(path, sr=16000, dur=8.0):
    """Свип 300->6300 Гц (мгновенная частота) с амплитудной модуляцией: широкополосный, лаг однозначен.

    Медленный свип 300->1200 Гц давал пик корреляции шириной ~4 мс и ложный наклон ~1800 ppm
    в фикстуре дрейфа, поэтому полоса расширена.
    """
    t = np.arange(int(sr * dur)) / sr
    f = 300 + (6000 / dur) * t / 2
    x = 0.3 * np.sin(2 * np.pi * f * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * t))
    write_wav(path, x, sr)
    return x


def make_recording(path, src, sr=16000, lag_s=0.3, gain=0.2, noise=0.002, seed=12345, drift_ppm=0.0):
    """Запись источника с лагом lag_s и (опционально) линейным дрейфом лага drift_ppm."""
    rng = np.random.default_rng(seed)
    n = len(src) + int(1.0 * sr)
    d = drift_ppm * 1e-6
    pos = np.arange(len(src), dtype=np.float64) * (1.0 + d) + lag_s * sr  # индекс в записи для i-го отсчёта
    x = np.interp(np.arange(n, dtype=np.float64), pos, gain * np.asarray(src, dtype=np.float64),
                  left=0.0, right=0.0)
    x += rng.normal(0, noise, n)
    write_wav(path, x, sr)


def make_noise_wav(path, sr=16000, dur=9.0, sigma=0.05, seed=7):
    rng = np.random.default_rng(seed)
    write_wav(path, rng.normal(0, sigma, int(sr * dur)), sr)


def make_png(path, with_text=True, noise=3.0, seed=3):
    rng = np.random.default_rng(seed)
    w, h = 1280, 720
    base = np.full((h, w, 3), (20, 24, 30), dtype=np.float64)
    base += rng.normal(0, noise, base.shape)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    if with_text:
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 44)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        for i, line in enumerate(FINALS[:3]):
            d.text((120, 500 + i * 70), line, fill=(240, 240, 240), font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def make_html(path):
    body = "".join(f'<div class="subtitle">{t}</div>\n' for t in FINALS)
    css = "/* " + "стили " * 200 + "*/"
    path.write_text(f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Субтитры</title>'
                    f"<style>body{{background:#141820;color:#eee}}{css}</style></head><body>\n{body}</body></html>",
                    encoding="utf-8")


def base_metrics(run_id, kind):
    finals, t = [], 1500.0
    for i, txt in enumerate(FINALS):
        finals.append({"text": txt, "t_ms": t + i * 4000, "source_end_ms": 1000.0 + i * 4000})
    partials = [{"text": p, "t_ms": 420.0 + i * 700} for i, p in enumerate(PARTIALS)]
    m = {
        "kind": kind, "run_id": run_id, "created": now(), "simulated": False, "engine": "sherpa",
        "fixture_note": "СИНТЕТИЧЕСКАЯ фикстура selftest_validator.py, не результат эксперимента",
        "source": {"type": "file", "path": "fixtures/source.wav", "duration_s": 20.0},
        "partial_count": len(partials), "final_count": len(finals),
        "first_partial_ms": 420.0, "finals": finals, "partials": partials,
        "timing": {"p50_ms": 350.0, "p95_ms": 800.0},
    }
    return m


def write_run(name, metrics, log="engine ok, 8 partials, 4 finals\n", files=None, png=True, html=True, kind="streaming"):
    d = GEN / "runs" / name
    (d / "artifacts").mkdir(parents=True, exist_ok=True)
    if metrics is not None:
        (d / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    if log is not None:
        (d / "log.txt").write_text(log, encoding="utf-8")
    if kind == "streaming":
        if png:
            make_png(d / "artifacts" / "screenshot.png")
        if html:
            make_html(d / "artifacts" / "page.html")
    return d


def streaming(name, mutate=None, **kw):
    m = base_metrics(name, "streaming")
    if mutate:
        mutate(m)
    return write_run(name, m, **kw)


def e2e(name, mutate=None, rec=None, **kw):
    """rec: функция (path)->None, пишущая запись; по умолчанию корректная запись источника."""
    src_path = GEN / "source.wav"
    m = base_metrics(name, "e2e")
    m["source"] = {"type": "loopback", "path": str(src_path), "duration_s": 8.0}
    for i, f in enumerate(m["finals"]):
        f["t_ms"] = 1500.0 + i * 1500
        f["source_end_ms"] = 1000.0 + i * 1500
    for i, p in enumerate(m["partials"]):
        p["t_ms"] = 420.0 + i * 600
    m["audio"] = {"recording_path": "artifacts/recording.wav", "snr_db": 26.0, "corr_peak": 0.99, "lag_ms": 300.0,
                  "corr_global": 0.99, "drift_ppm": 0.0, "valid_window_fraction": 1.0}
    if mutate:
        mutate(m)
    d = write_run(name, m, kind="e2e", **kw)
    rp = d / "artifacts" / "recording.wav"
    if rec is None:
        make_recording(rp, SRC)
    elif rec != "none":
        rec(rp)
    return d


def build_fixtures():
    global SRC
    if GEN.exists():
        shutil.rmtree(GEN)
    GEN.mkdir(parents=True)
    SRC = make_source(GEN / "source.wav")
    F = {}  # name -> (expected, must_fail_check)
    streaming("good_streaming");                                  F["good_streaming"] = ("PASS", None)
    # good_e2e: заявленный SNR (26) совпадает с пересчитанным из WAV (~26.1 дБ по p90/p10 кадров 30 мс).
    e2e("good_e2e");                                              F["good_e2e"] = ("PASS", None)

    def single(m):
        m["finals"] = [{"text": "добрый день коллеги сегодня обсуждаем субтитры", "t_ms": 9000.0, "source_end_ms": 8500.0}]
        m["final_count"] = 1
    streaming("good_single_final", single);                       F["good_single_final"] = ("PASS", None)

    def sim(m): m["simulated"] = True
    streaming("bad_simulated", sim);                              F["bad_simulated"] = ("FAIL", "simulated_is_false")

    def empty(m):
        m.update(finals=[], final_count=0)
    streaming("bad_empty_text", empty);                           F["bad_empty_text"] = ("FAIL", "final_count_ge_1")

    def rep(m):
        m["finals"] = [{"text": "добрый день", "t_ms": 1000.0 + i * 1000, "source_end_ms": 900.0 + i * 1000} for i in range(6)]
        m["final_count"] = 6
    streaming("bad_repeated", rep);                               F["bad_repeated"] = ("FAIL", "finals_distinct")

    def f32(m):  # история WER=1.0: пустые гипотезы, partial_count 0, а лог бодро пишет ok
        m.update(finals=[], partials=[], final_count=0, partial_count=0, first_partial_ms=0.0,
                 timing={"p50_ms": 0.0, "p95_ms": 0.0})
    streaming("bad_float32", f32, log="decode status: ok\nWER=1.000 (hyp all empty)\nstatus ok\n")
    F["bad_float32"] = ("FAIL", "partial_count_gt_0")

    e2e("bad_low_snr", mutate=lambda m: m["audio"].update(snr_db=3.0));  F["bad_low_snr"] = ("FAIL", "snr_db_min")
    # заявлено 40 дБ, а запись с шумом sigma=0.01 даёт ~12 дБ: завышение > 10 дБ ловится пересчётом
    e2e("bad_snr_inflated", mutate=lambda m: m["audio"].update(snr_db=40.0),
        rec=lambda p: make_recording(p, SRC, noise=0.01))
    F["bad_snr_inflated"] = ("FAIL", "snr_recomputed_consistent")
    # запись - стационарный шум (пересчитанный SNR ~0.7 дБ), заявлено 0.0: честно, но < min-snr
    e2e("bad_snr_zero", mutate=lambda m: m["audio"].update(snr_db=0.0), rec=make_noise_wav)
    F["bad_snr_zero"] = ("FAIL", "snr_recomputed_consistent")
    e2e("bad_missing_wav", mutate=lambda m: m["audio"].update(recording_path="artifacts/nope.wav"), rec="none")
    F["bad_missing_wav"] = ("FAIL", "recording_exists")
    write_run("bad_no_metrics", None, kind="e2e");                F["bad_no_metrics"] = ("FAIL", "metrics_readable")

    def ph(m):
        m["finals"][1]["text"] = "lorem ipsum..."
    streaming("bad_placeholder", ph);                             F["bad_placeholder"] = ("FAIL", "no_placeholder_text")

    def miss(m): del m["timing"]
    streaming("bad_missing_field", miss);                         F["bad_missing_field"] = ("FAIL", "missing_field:timing")

    e2e("bad_silent_wav", rec=lambda p: write_wav(p, np.zeros(16000 * 9)))
    F["bad_silent_wav"] = ("FAIL", "recording_peak_dbfs")
    # запись - шум, а в metrics.json заявлена корреляция 0.99: ловится только пересчётом по исходнику
    e2e("bad_wrong_corr", rec=make_noise_wav);                    F["bad_wrong_corr"] = ("FAIL", "corr_recomputed_min")
    # честно заявленный, но недопустимый дрейф 900 ppm: поля согласованы, критерий |drift|<500 не выполнен
    e2e("bad_high_drift", mutate=lambda m: m["audio"].update(drift_ppm=900.0),
        rec=lambda p: make_recording(p, SRC, drift_ppm=900.0))
    F["bad_high_drift"] = ("FAIL", "drift_ppm_limit")
    streaming("bad_no_screenshot", png=False);                    F["bad_no_screenshot"] = ("FAIL", "artifact:screenshot.png")
    # скриншот одноцветный (но > 1 КБ из-за слабого шума): ловится check_screenshot внутри слоя 1
    d = streaming("bad_blank_screenshot")
    make_png(d / "artifacts" / "screenshot.png", with_text=False, noise=0.6)
    F["bad_blank_screenshot"] = ("FAIL", "screenshot_not_blank")
    return F


# ------------------------------------------------------------------ запуск
def run_cli(args):
    env = dict(__import__("os").environ, **ENV_UTF8)
    p = subprocess.run([PY, *args], capture_output=True, text=True, encoding="utf-8", env=env, timeout=180)
    return p.returncode, p.stdout, p.stderr


def validate_fixture(name):
    d = GEN / "runs" / name
    rc, out, err = run_cli([str(HERE / "validate_run.py"), "--run", str(d), "--allow-missing-vision"])
    vj = d / "verdict.json"
    failed = []
    if vj.is_file():
        v = json.loads(vj.read_text(encoding="utf-8"))
        failed = [c["name"] for c in v["checks"] if not c["ok"]]
    return rc, failed, ("Traceback" in err or "Traceback" in out)


# ------------------------------------------------------------------ сервер для слоя 2
PHRASES = ["добрый день", "добрый день коллеги", "сегодня обсуждаем субтитры", "задержка небольшая"]


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _html(self, text):
        b = (f'<!doctype html><meta charset="utf-8"><title>t</title><body><div id="status">live</div>'
             f'<div class="subtitle">{text}</div></body>').encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        idx = int(time.time() / 0.4) % len(PHRASES)
        if self.path == "/dynamic":
            self._html(PHRASES[idx])
        elif self.path == "/static":
            self._html(PHRASES[0])
        elif self.path == "/latin":
            self._html(["hello", "hello world", "good day", "bye now"][idx])
        elif self.path == "/sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for i in range(8):
                    self.wfile.write(f"data: {json.dumps({'text': PHRASES[i % 4]}, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.3)
            except Exception:  # noqa: BLE001
                pass
        else:
            self.send_response(404)
            self.end_headers()


def free_closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    rows = []
    F = build_fixtures()
    # ---- слой 1
    for name, (exp, must) in F.items():
        rc, failed, tb = validate_fixture(name)
        actual = "PASS" if rc == 0 else "FAIL"
        ok = actual == exp and not tb
        if exp == "FAIL":
            ok = ok and must in failed
        note = "traceback!" if tb else (f"failed: {', '.join(failed[:3])}" if failed else "")
        rows.append(("L1 " + name, exp + (f" ({must})" if must else ""), actual, ok, note))

    # ---- слой 2: DOM
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    dom_dir = GEN / "dom"
    dom_dir.mkdir(parents=True, exist_ok=True)
    cases = [("dynamic", f"http://127.0.0.1:{port}/dynamic", "PASS", None),
             ("sse", f"http://127.0.0.1:{port}/sse", "PASS", None),
             ("static", f"http://127.0.0.1:{port}/static", "FAIL", "text_changes_at_least_once"),
             ("latin", f"http://127.0.0.1:{port}/latin", "FAIL", "cyrillic_present"),
             ("http404", f"http://127.0.0.1:{port}/nothing", "FAIL", "http_404"),
             ("refused", f"http://127.0.0.1:{free_closed_port()}/", "FAIL", "connection_refused")]
    for name, url, exp, must in cases:
        out = dom_dir / f"{name}.json"
        rc, so, se = run_cli([str(HERE / "check_dom.py"), "--url", url, "--samples", "6", "--interval", "0.3", "--out", str(out)])
        actual = "PASS" if rc == 0 else "FAIL"
        failed = []
        if out.is_file():
            failed = [c["name"] for c in json.loads(out.read_text(encoding="utf-8"))["checks"] if not c["ok"]]
        ok = actual == exp and "Traceback" not in se + so and (must is None or must in failed)
        rows.append(("L2 dom " + name, exp + (f" ({must})" if must else ""), actual, ok,
                     f"failed: {', '.join(failed[:3])}" if failed else ""))
    srv.shutdown()

    # ---- слой 2: скриншот
    for name, path, exp in [("good", GEN / "runs" / "good_streaming" / "artifacts" / "screenshot.png", "PASS"),
                            ("blank", GEN / "runs" / "bad_blank_screenshot" / "artifacts" / "screenshot.png", "FAIL"),
                            ("missing", GEN / "nope.png", "FAIL")]:
        out = GEN / f"shot_{name}.json"
        rc, so, se = run_cli([str(HERE / "check_screenshot.py"), "--path", str(path), "--out", str(out)])
        actual = "PASS" if rc == 0 else "FAIL"
        rows.append((f"L2 screenshot {name}", exp, actual, actual == exp and "Traceback" not in se + so, ""))
    corrupt = GEN / "corrupt.png"
    corrupt.write_bytes(b"not a png" * 1000)
    rc, so, se = run_cli([str(HERE / "check_screenshot.py"), "--path", str(corrupt), "--out", str(GEN / "shot_corrupt.json")])
    rows.append(("L2 screenshot corrupt", "FAIL", "PASS" if rc == 0 else "FAIL", rc != 0 and "Traceback" not in se + so, ""))

    # ---- gate (vision-review здесь вручную собранный JSON, НЕ настоящий разбор vision-моделью)
    run = GEN / "runs" / "good_streaming"
    shot = run / "artifacts" / "screenshot.png"
    dom_ok = dom_dir / "dynamic.json"
    dom_bad = dom_dir / "static.json"
    vis_ok = GEN / "vision_ok.json"
    vis_ok.write_text(json.dumps({"pass": True, "run_id": "good_streaming",
                                  "screenshot_sha256": hashlib.sha256(shot.read_bytes()).hexdigest()}), encoding="utf-8")
    vis_bad_hash = GEN / "vision_badhash.json"
    vis_bad_hash.write_text(json.dumps({"pass": True, "screenshot_sha256": "0" * 64}), encoding="utf-8")
    vis_false = GEN / "vision_false.json"
    vis_false.write_text(json.dumps({"pass": False}), encoding="utf-8")
    gate_cases = [
        ("all layers ok", ["--dom", dom_ok, "--vision-review", vis_ok], "PASS"),
        ("no dom (auto-required)", ["--vision-review", vis_ok], "FAIL"),
        ("no vision (auto-required)", ["--dom", dom_ok], "FAIL"),
        ("no vision, allowed", ["--dom", dom_ok, "--allow-missing-vision"], "PASS"),
        ("dom fails", ["--dom", dom_bad, "--vision-review", vis_ok], "FAIL"),
        ("vision pass=false", ["--dom", dom_ok, "--vision-review", vis_false], "FAIL"),
        ("vision hash mismatch", ["--dom", dom_ok, "--vision-review", vis_bad_hash], "FAIL"),
        ("dom file missing", ["--dom", GEN / "nope.json", "--vision-review", vis_ok], "FAIL"),
    ]
    for name, extra, exp in gate_cases:
        rc, so, se = run_cli([str(HERE / "gate.py"), "--run", str(run), *map(str, extra)])
        actual = "PASS" if rc == 0 else "FAIL"
        rows.append(("gate " + name, exp, actual, actual == exp and "Traceback" not in se + so, so.strip().splitlines()[-1][:70] if so.strip() else ""))
    # gate: слой 1 FAIL перекрывает всё
    rc, so, se = run_cli([str(HERE / "gate.py"), "--run", str(GEN / "runs" / "bad_simulated"), "--allow-missing-vision", "--allow-missing-dom"])
    rows.append(("gate layer1 fail", "FAIL", "PASS" if rc == 0 else "FAIL", rc != 0 and "Traceback" not in se + so, ""))

    # ---- таблица
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len(r[1]) for r in rows)
    print(f"{'fixture':<{w0}} | {'ожидание':<{w1}} | {'факт':<5} | ok")
    print("-" * (w0 + w1 + 20))
    for n, e, a, ok, note in rows:
        print(f"{n:<{w0}} | {e:<{w1}} | {a:<5} | {'ok' if ok else 'MISMATCH'}   {note}")
    bad = [r for r in rows if not r[3]]
    summary = {"created": now(), "total": len(rows), "mismatches": len(bad),
               "rows": [{"fixture": n, "expected": e, "actual": a, "ok": ok, "note": note} for n, e, a, ok, note in rows]}
    out_dir = HERE / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "selftest_validator.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nИтого: {len(rows)} кейсов, расхождений: {len(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
