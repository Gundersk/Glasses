import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asr_benchmark
import web_subtitles_demo

CYR = re.compile(r'[а-яА-ЯёЁ]')
SUBTITLE_RE = re.compile(r'<div class="subtitle">([^<]*)</div>', re.I)


def ensure_dir(path):
    if path:
        os.makedirs(path, exist_ok=True)


def write_metrics(path, metrics):
    ensure_dir(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


def split_subtitles(text):
    text = ' '.join(text.split())
    if not text:
        return []
    parts = re.split(r'(?<=[.!?])\s+', text)
    parts = [p.strip().replace('<', ' ').replace('>', ' ') for p in parts if p.strip()]
    if len(parts) > 1:
        return parts[:1000]
    words = text.split()
    chunks = []
    for i in range(0, len(words), 5):
        chunks.append(' '.join(words[i:i+5]).replace('<', ' ').replace('>', ' '))
    return chunks[:1000]


def start_server(subtitles):
    web_subtitles_demo.Handler.subtitles = subtitles
    server = ThreadingHTTPServer(('127.0.0.1', 0), web_subtitles_demo.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def wait_health(port, timeout=10.0):
    url = 'http://127.0.0.1:' + str(port) + '/health'
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                data = json.loads(r.read().decode('utf-8', 'replace'))
            if data.get('ok'):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def fetch_page(port):
    url = 'http://127.0.0.1:' + str(port) + '/'
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode('utf-8', 'replace')


def count_rendered_cyrillic(html):
    count = 0
    sample = None
    for m in SUBTITLE_RE.finditer(html):
        text = m.group(1)
        if CYR.search(text):
            count += 1
            if sample is None:
                sample = text
    return count, sample


def main():
    audio = 'experiments/data/speech_ru.wav'
    model = 'models/vosk-model-small-ru-0.22'
    out_dir = 'experiments/web_demo'
    metrics_path = os.path.join(out_dir, 'asr_bridge_metrics.json')
    png_path = os.path.join(out_dir, 'asr_ui.png')
    html_path = os.path.join(out_dir, 'asr_page.html')
    ensure_dir(out_dir)

    metrics = {
        'audio': audio,
        'model': model,
        'seed': 0,
        'python': sys.version,
        'time': time.strftime('%Y-%m-%dT%H:%M:%S%z')
    }

    hyp, lat, meta = asr_benchmark.run_vosk(audio, model)
    if hyp is None:
        metrics.update(meta)
        metrics['error'] = 'asr_failed'
        write_metrics(metrics_path, metrics)
        print(json.dumps(metrics, ensure_ascii=False))
        return 1

    subtitles = split_subtitles(hyp)
    cyrillic_subtitles = [s for s in subtitles if CYR.search(s)]
    if not cyrillic_subtitles:
        metrics['hyp'] = hyp
        metrics['error'] = 'no_cyrillic_asr'
        write_metrics(metrics_path, metrics)
        print(json.dumps(metrics, ensure_ascii=False))
        return 1

    server = None
    try:
        server, port = start_server(subtitles)
        if not wait_health(port):
            metrics['server_url'] = 'http://127.0.0.1:' + str(port) + '/'
            metrics['error'] = 'health_timeout'
            write_metrics(metrics_path, metrics)
            print(json.dumps(metrics, ensure_ascii=False))
            return 1

        html = fetch_page(port)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)

        rendered_total = html.count('class="subtitle"')
        rendered_cyrillic, sample = count_rendered_cyrillic(html)
        if rendered_cyrillic < 1:
            metrics['server_url'] = 'http://127.0.0.1:' + str(port) + '/'
            metrics['rendered_subtitles'] = rendered_total
            metrics['rendered_cyrillic_subtitles'] = rendered_cyrillic
            metrics['error'] = 'no_rendered_cyrillic'
            write_metrics(metrics_path, metrics)
            print(json.dumps(metrics, ensure_ascii=False))
            return 1

        url = 'http://127.0.0.1:' + str(port) + '/'
        cmd = [sys.executable, '-m', 'autonomy.screenshot', url, png_path]
        screenshot_ok = False
        screenshot_error = None
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            screenshot_ok = proc.returncode == 0 and os.path.exists(png_path)
            if not screenshot_ok:
                screenshot_error = (proc.stderr or proc.stdout or '').strip()
        except Exception as e:
            screenshot_error = str(e)

        metrics.update({
            'asr_final_segments': len(subtitles),
            'rendered_subtitles': rendered_total,
            'rendered_cyrillic_subtitles': rendered_cyrillic,
            'sample_subtitle': sample,
            'server_url': url,
            'screenshot_ok': screenshot_ok,
            'screenshot_cmd': ' '.join(cmd),
            'asr_hyp': hyp,
            'asr_meta': meta,
            'latency_count': len(lat)
        })
        if screenshot_error:
            metrics['screenshot_error'] = screenshot_error

        write_metrics(metrics_path, metrics)
        print(json.dumps(metrics, ensure_ascii=False))
        return 0 if screenshot_ok else 1
    finally:
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
