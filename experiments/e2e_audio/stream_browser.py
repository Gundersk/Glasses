"""Потоковый прогон: WAV -> ASR в темпе реального времени -> веб-страница субтитров -> приёмка.

    python experiments/e2e_audio/stream_browser.py --wav data/fleurs_ru_test/clip_001.wav --engine sherpa \
        --run-dir experiments/e2e_audio/runs/<run_id> --port 0 --speed 1.0 --chunk-ms 100

Что делает (всё реально, без заготовленной разметки):
  1. читает WAV через soundfile (float32), приводит к 16 кГц, режет на чанки chunk_ms;
  2. подаёт чанки в ASR по расписанию реального времени (speed); отставание фиксируется как feed_lag_ms;
  3. поднимает HTTP-сервер 127.0.0.1: `/` (серверный рендер + JS-опрос /state каждые 300 мс), `/state` (JSON);
  4. во время подачи гоняет check_dom.py по живому серверу;
  5. в конце: artifacts/page.html, artifacts/screenshot.png (Playwright/Edge), metrics.json, log.txt,
     затем validate_run.py и gate.py (stdout сохраняется в artifacts/).

Определение задержки (event latency): t_ms события - момент ПОСТУПЛЕНИЯ конца последнего поданного чанка
(source_pos_ms / speed). Это задержка обработки ASR после прихода аудио; она НЕ включает длину самого чанка
и «ожидание паузы» для endpoint. source_end_ms финала = позиция конца чанка, на котором сработал endpoint
(для финала на конце файла - конец подачи).
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import pathlib
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundfile as sf

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import streaming_asr  # noqa: E402

PY = sys.executable
VISIBLE_FINALS = 3
EDGE_PATHS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]


# ------------------------------------------------------------------ состояние и страница
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.partial = ""
        self.finals = []
        self.t0 = None
        self.done = False

    def snapshot(self):
        with self.lock:
            t = round(time.perf_counter() - self.t0, 3) if self.t0 else 0.0
            return {"partial": self.partial, "finals": list(self.finals), "t": t, "done": self.done}


CSS = """
html,body{margin:0;height:100%;background:#10141a;color:#f2f2f2;font-family:'Segoe UI',Arial,sans-serif}
header{padding:18px 40px;font-size:22px;color:#8fa3b8;border-bottom:1px solid #26303c}
#subs{position:fixed;left:40px;right:40px;bottom:56px;display:flex;flex-direction:column;gap:14px}
.subtitle{font-size:40px;line-height:1.2;font-weight:600;min-height:48px}
.subtitle-final{color:#ffffff}
.subtitle-partial{color:#7fd0ff;font-style:italic}
footer{position:fixed;left:40px;bottom:16px;font-size:16px;color:#5d6e80}
"""

JS = """
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function render(st){
  var f=st.finals.slice(-%(n)d), h='';
  for(var i=0;i<f.length;i++){h+='<div class="subtitle subtitle-final">'+esc(f[i])+'</div>';}
  h+='<div class="subtitle subtitle-partial">'+esc(st.partial||'')+'</div>';
  document.getElementById('subs').innerHTML=h;
  document.getElementById('st').textContent=(st.done?'прогон завершён':'идёт приём')+', t='+st.t+' с';
}
function tick(){fetch('/state',{cache:'no-store'}).then(function(r){return r.json();}).then(render).catch(function(){});}
setInterval(tick,300);
"""


def render_page(snap, engine, run_id):
    finals = snap["finals"][-VISIBLE_FINALS:]
    body = "".join(f'<div class="subtitle subtitle-final">{html.escape(t)}</div>\n' for t in finals)
    body += f'<div class="subtitle subtitle-partial">{html.escape(snap["partial"])}</div>\n'
    status = "прогон завершён" if snap["done"] else "идёт приём"
    return (f'<!doctype html>\n<html lang="ru"><head><meta charset="utf-8">'
            f'<title>Субтитры: {html.escape(engine)}</title><style>{CSS}</style></head><body>\n'
            f'<header>Субтитры в реальном времени · движок: {html.escape(engine)} · прогон: {html.escape(run_id)}</header>\n'
            f'<div id="subs">\n{body}</div>\n'
            f'<footer><span id="st">{status}, t={snap["t"]} с</span></footer>\n'
            f'<script>{JS % {"n": VISIBLE_FINALS}}</script>\n</body></html>\n')


def make_handler(state, engine, run_id):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):  # тишина в консоли
            pass

        def _send(self, code, ctype, data):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, "text/html; charset=utf-8", render_page(state.snapshot(), engine, run_id).encode("utf-8"))
            elif path == "/state":
                self._send(200, "application/json; charset=utf-8",
                           json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8"))
            else:
                self._send(404, "text/plain; charset=utf-8", b"not found")

    return Handler


# ------------------------------------------------------------------ подача аудио
def pct(values, p):
    return float(np.percentile(values, p)) if len(values) else 0.0


class Run:
    def __init__(self, args, run_dir):
        self.args = args
        self.run_dir = run_dir
        self.log_path = run_dir / "log.txt"
        self._log = open(self.log_path, "w", encoding="utf-8")
        self.state = State()
        self.partials = []
        self.finals = []
        self.lags = []
        self.procs = []
        self.first_partial_evt = threading.Event()
        self.feed_done = threading.Event()
        self.feed_error = None
        self.feed_wall_s = 0.0

    def log(self, msg):
        line = f"{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}"
        self._log.write(line + "\n")
        self._log.flush()
        print(line, flush=True)

    def feed(self, asr, x16, tail_s):
        """Подаёт x16 (+ тишина tail_s) чанками по расписанию реального времени. Пишет события."""
        try:
            a = self.args
            sr = streaming_asr.TARGET_SR
            if tail_s > 0:
                x16 = np.concatenate([x16, np.zeros(int(tail_s * sr), dtype=np.float32)])
            n = len(x16)
            chunk = max(1, int(a.chunk_ms * sr / 1000))
            speed = a.speed
            st = self.state
            last_partial = ""
            t0 = time.perf_counter()
            with st.lock:
                st.t0 = t0
            for start in range(0, n, chunk):
                end = min(start + chunk, n)
                sched = end / sr / speed  # когда чанк «поступил» (конец чанка)
                while True:
                    rem = sched - (time.perf_counter() - t0)
                    if rem <= 0:
                        break
                    time.sleep(rem - 0.002 if rem > 0.004 else 0)
                t_feed = time.perf_counter()
                self.lags.append(max(0.0, (t_feed - t0 - sched) * 1000.0))
                partial = asr.accept(x16[start:end], sr)
                if not asr.status.ok:
                    raise RuntimeError(asr.status.message)
                is_ep = asr.is_endpoint()
                if is_ep:
                    final = asr.finalize()
                    t_ev = time.perf_counter()
                    asr.reset()
                    if final:
                        self._add_final(final, t0, t_ev, end * 1000.0 / sr, "endpoint")
                    last_partial = ""
                    with st.lock:
                        st.partial = ""
                else:
                    t_ev = time.perf_counter()
                    if partial and partial != last_partial:
                        self._add_partial(partial, t0, t_ev, end * 1000.0 / sr)
                        last_partial = partial
                        with st.lock:
                            st.partial = partial
                self.procs.append((time.perf_counter() - t_feed) * 1000.0)
            # конец входа: сбросить остаток
            final = asr.finalize()
            t_ev = time.perf_counter()
            if final:
                self._add_final(final, t0, t_ev, n * 1000.0 / sr, "eof")
            with st.lock:
                st.partial = ""
            self.feed_wall_s = time.perf_counter() - t0
        except Exception as e:  # noqa: BLE001
            self.feed_error = f"{type(e).__name__}: {str(e)[:300]}"
            self.log(f"ОШИБКА подачи: {self.feed_error}")
        finally:
            with self.state.lock:
                self.state.done = True
            self.feed_done.set()

    def _add_partial(self, text, t0, t_ev, src_ms):
        t_ms = (t_ev - t0) * 1000.0
        lat = t_ms - src_ms / self.args.speed
        self.partials.append({"text": text, "t_ms": round(t_ms, 3), "source_pos_ms": round(src_ms, 3),
                              "latency_ms": round(lat, 3)})
        self.log(f"partial t={t_ms:8.1f} ms src={src_ms:8.1f} lat={lat:6.1f}: {text}")
        self.first_partial_evt.set()

    def _add_final(self, text, t0, t_ev, src_ms, reason):
        t_ms = (t_ev - t0) * 1000.0
        lat = t_ms - src_ms / self.args.speed
        self.finals.append({"text": text, "t_ms": round(t_ms, 3), "source_end_ms": round(src_ms, 3),
                            "latency_ms": round(lat, 3), "reason": reason})
        self.log(f"FINAL   t={t_ms:8.1f} ms src_end={src_ms:8.1f} lat={lat:6.1f} [{reason}]: {text}")
        with self.state.lock:
            self.state.finals.append(text)


# ------------------------------------------------------------------ скриншот
def take_screenshot(url, out, log):
    """Возвращает (ok, method, detail). Не подделывает PNG: при неудаче файла нет."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    errors = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            for label, kw in (("playwright-msedge", {"channel": "msedge"}), ("playwright-chromium", {})):
                try:
                    b = p.chromium.launch(headless=True, **kw)
                    ver = b.version
                    try:
                        pg = b.new_page(viewport={"width": 1280, "height": 720})
                        pg.goto(url, wait_until="load", timeout=15000)
                        pg.wait_for_timeout(900)  # дать отработать JS-опросу /state
                        pg.screenshot(path=str(out))
                    finally:
                        b.close()
                    if out.is_file() and out.stat().st_size > 0:
                        return True, label, f"browser {ver}"
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{label}: {type(e).__name__}: {str(e)[:120]}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"playwright import/run: {type(e).__name__}: {str(e)[:120]}")
    for edge in EDGE_PATHS:
        if pathlib.Path(edge).is_file():
            try:
                subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                f"--screenshot={out}", "--window-size=1280,720", url],
                               capture_output=True, timeout=40)
                if out.is_file() and out.stat().st_size > 0:
                    return True, "msedge-cli", edge
                errors.append(f"msedge-cli: файл не создан ({edge})")
            except Exception as e:  # noqa: BLE001
                errors.append(f"msedge-cli: {type(e).__name__}: {str(e)[:120]}")
            break
    return False, None, "; ".join(errors) or "браузер не найден"


# ------------------------------------------------------------------ метрики
def build_metrics(run, args, run_id, wav_dur_s, fed_dur_s, asr_status, shot_info, wall_total_s):
    f_lat = [f["latency_ms"] for f in run.finals]
    p_lat = [p["latency_ms"] for p in run.partials]
    first_partial = min((p["t_ms"] for p in run.partials), default=0.0)
    return {
        "kind": "streaming", "run_id": run_id,
        "created": datetime.datetime.now().astimezone().isoformat(),
        "simulated": False, "engine": args.engine,
        "source": {"type": "file", "path": str(args.wav).replace("\\", "/"), "duration_s": round(fed_dur_s, 3),
                   "wav_duration_s": round(wav_dur_s, 3), "tail_silence_s": args.tail_s,
                   "note": "duration_s = длительность реально поданного аудио (WAV + тишина в конце)"},
        "partial_count": len(run.partials), "final_count": len(run.finals),
        "first_partial_ms": first_partial,
        "finals": run.finals, "partials": run.partials,
        "timing": {"p50_ms": round(pct(f_lat, 50), 3), "p95_ms": round(pct(f_lat, 95), 3),
                   "basis": "задержка финалов: t_ms - source_end_ms/speed", "n": len(f_lat),
                   "partial_p50_ms": round(pct(p_lat, 50), 3), "partial_p95_ms": round(pct(p_lat, 95), 3),
                   "partial_n": len(p_lat)},
        "feed": {"speed": args.speed, "chunk_ms": args.chunk_ms,
                 "feed_lag_ms_max": round(max(run.lags, default=0.0), 3),
                 "feed_lag_ms_p95": round(pct(run.lags, 95), 3),
                 "feed_lag_ms_last": round(run.lags[-1], 3) if run.lags else 0.0,
                 "chunk_proc_ms_p50": round(pct(run.procs, 50), 3),
                 "chunk_proc_ms_p95": round(pct(run.procs, 95), 3),
                 "chunk_proc_ms_max": round(max(run.procs, default=0.0), 3),
                 "chunks": len(run.procs),
                 "rtf_proc": round(sum(run.procs) / 1000.0 / (fed_dur_s / args.speed), 4) if fed_dur_s else None,
                 "feed_wall_s": round(run.feed_wall_s, 3), "run_wall_s": round(wall_total_s, 3),
                 "realtime_kept": bool(run.lags) and max(run.lags) < args.chunk_ms},
        "asr": asr_status,
        "screenshot": shot_info,
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "command": " ".join(sys.argv),
    }


def run_cli(cmd, out_path, log):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**__import__("os").environ, "PYTHONUTF8": "1"}, timeout=300)
    text = (p.stdout or "") + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")
    out_path.write_text(text, encoding="utf-8")
    return p.returncode, text


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Потоковый ASR -> страница субтитров -> приёмка")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--engine", default="sherpa", choices=sorted(streaming_asr.ENGINES))
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--chunk-ms", type=int, default=100)
    ap.add_argument("--tail-s", type=float, default=1.0, help="тишина после файла для срабатывания endpoint")
    ap.add_argument("--dom-samples", type=int, default=8)
    ap.add_argument("--dom-interval", type=float, default=0.7)
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    run_dir = pathlib.Path(args.run_dir)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    art = run_dir / "artifacts"
    run_id = run_dir.name
    for stale in ("metrics.json", "verdict.json", "run_verdict.json", "screenshot_checks.json"):
        (run_dir / stale).unlink(missing_ok=True)
    for stale in ("screenshot.png", "page.html", "missing_screenshot.txt", "dom_checks.json",
                  "gate_stdout.txt", "validate_stdout.txt", "dom_stdout.txt"):
        (art / stale).unlink(missing_ok=True)
    run = Run(args, run_dir)
    t_start = time.perf_counter()
    run.log(f"run_id={run_id} engine={args.engine} wav={args.wav} speed={args.speed} chunk_ms={args.chunk_ms} tail_s={args.tail_s}")
    run.log(f"команда: {' '.join(sys.argv)}")

    failure = None
    metrics = None
    srv = None
    try:
        data, sr = sf.read(str(args.wav), dtype="float32", always_2d=False)
        if data.ndim == 2:
            data = data.mean(axis=1)
        wav_dur = len(data) / sr
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        run.log(f"WAV: sr={sr} n={len(data)} dur={wav_dur:.3f}s peak={peak:.4f} dtype=float32 (soundfile)")
        if peak <= 0:
            raise RuntimeError("WAV беззвучный (peak=0)")
        x16 = streaming_asr.resample_to_16k(data, sr)
        if sr != streaming_asr.TARGET_SR:
            run.log(f"ресемплинг {sr} -> 16000 (scipy.signal.resample_poly)")
        fed_dur = wav_dur + args.tail_s

        t_load = time.perf_counter()
        asr, status = streaming_asr.create_asr(args.engine)
        if asr is None:
            raise RuntimeError(f"ASR не создан: {status.message}")
        run.log(f"ASR готов за {time.perf_counter() - t_load:.2f} с: {status.version}; {json.dumps(status.config, ensure_ascii=False)}")

        srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(run.state, args.engine, run_id))
        srv.daemon_threads = True
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{port}/"
        run.log(f"сервер: {url}  (state: {url}state)")

        th = threading.Thread(target=run.feed, args=(asr, x16, args.tail_s), daemon=True)
        th.start()
        # ждём первый partial (или конец подачи) и запускаем DOM-проверку на живом сервере
        while not (run.first_partial_evt.is_set() or run.feed_done.is_set()):
            time.sleep(0.02)
        run.log("запуск check_dom.py на живом сервере")
        dom_rc, dom_out = run_cli([PY, str(HERE / "check_dom.py"), "--url", url, "--samples", str(args.dom_samples),
                                   "--interval", str(args.dom_interval), "--out", str(art / "dom_checks.json")],
                                  art / "dom_stdout.txt", run.log)
        run.log(f"check_dom rc={dom_rc}: {dom_out.strip().splitlines()[-1] if dom_out.strip() else ''}")
        th.join()
        run.log(f"подача завершена: partials={len(run.partials)} finals={len(run.finals)} "
                f"feed_lag_max={max(run.lags, default=0):.1f} ms wall={run.feed_wall_s:.2f} с")
        if run.feed_error:
            raise RuntimeError(f"подача прервана: {run.feed_error}")

        # page.html: серверный рендер с накопленными субтитрами
        snap = run.state.snapshot()
        (art / "page.html").write_text(render_page(snap, args.engine, run_id), encoding="utf-8")
        # скриншот реальным браузером
        ok, method, detail = take_screenshot(url, art / "screenshot.png", run.log)
        if ok:
            shot_info = {"method": method, "path": "artifacts/screenshot.png", "detail": detail}
            run.log(f"скриншот: {method} -> {art / 'screenshot.png'} ({(art / 'screenshot.png').stat().st_size} байт)")
        else:
            shot_info = {"method": None, "path": None, "detail": detail}
            (art / "missing_screenshot.txt").write_text(
                f"Скриншот не получен: {detail}\nPNG не подделывается; слой скриншота остаётся FAIL.\n", encoding="utf-8")
            run.log(f"скриншот НЕ получен: {detail}")
        metrics = build_metrics(run, args, run_id, wav_dur, fed_dur, status.as_dict(), shot_info,
                                time.perf_counter() - t_start)
        (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        run.log("metrics.json записан")
    except Exception as e:  # noqa: BLE001
        failure = f"{type(e).__name__}: {str(e)[:300]}"
        run.log(f"ПРОГОН НЕ УДАЛСЯ: {failure}")
        (art / "error.txt").write_text(failure + "\n", encoding="utf-8")
    finally:
        # --- приёмка в самом конце (сервер ещё жив; слои считаются по файлам)
        rc_v, out_v = run_cli([PY, str(HERE / "validate_run.py"), "--run", str(run_dir), "--allow-missing-vision"],
                              art / "validate_stdout.txt", run.log)
        run.log(f"validate_run rc={rc_v}: {out_v.strip().splitlines()[-1] if out_v.strip() else ''}")
        rc_g, out_g = run_cli([PY, str(HERE / "gate.py"), "--run", str(run_dir), "--dom", str(art / "dom_checks.json"),
                               "--screenshot", str(art / "screenshot.png"), "--allow-missing-vision"],
                              art / "gate_stdout.txt", run.log)
        run.log(f"gate rc={rc_g}: {out_g.strip().splitlines()[-1] if out_g.strip() else ''}")
        if srv is not None:
            srv.shutdown()
            srv.server_close()
        run._log.close()
    print("--- validate_run ---")
    print(out_v)
    print("--- gate ---")
    print(out_g)
    return 0 if (rc_g == 0 and failure is None) else 1


if __name__ == "__main__":
    sys.exit(main())
