import argparse, json, os, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_SUBTITLES = ["Hello", "Hello world", "Hello world final"]

def make_html(subtitles):
    rows = []
    for s in subtitles:
        rows.append('<div class="subtitle">' + str(s) + '</div>')
    return '<!doctype html><html><head><meta charset="utf-8"><title>Subtitles</title></head><body><div id="subtitles">' + ''.join(rows) + '</div></body></html>'

class Handler(BaseHTTPRequestHandler):
    subtitles = DEFAULT_SUBTITLES
    def do_GET(self):
        if self.path == '/':
            html = make_html(self.subtitles)
            data = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == '/health':
            data = json.dumps({'ok': True}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, format, *args):
        pass

def write_metrics(path, metrics):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

def check_demo(output, duration=1.0, interval=0.2):
    Handler.subtitles = DEFAULT_SUBTITLES
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:' + str(port) + '/'
    rendered = 0
    demo_ready = False
    last_error = None
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(url, timeout=1) as r:
                    html = r.read().decode('utf-8', 'replace')
                rendered = html.count('class="subtitle"')
                demo_ready = rendered >= 1
                break
            except Exception as e:
                last_error = str(e)
                time.sleep(interval)
    finally:
        server.shutdown()
        server.server_close()
    metrics = {
        'demo_ready': bool(demo_ready),
        'subtitles_rendered': int(rendered),
        'server_url': url,
        'duration': float(duration),
        'interval': float(interval),
        'seed': 0,
        'python': sys.version,
        'time': time.strftime('%Y-%m-%dT%H:%M:%S%z')
    }
    if last_error:
        metrics['last_error'] = last_error
    write_metrics(output, metrics)
    print(json.dumps(metrics, ensure_ascii=False))
    return 0 if demo_ready else 1

def serve(host='127.0.0.1', port=8000):
    Handler.subtitles = DEFAULT_SUBTITLES
    server = ThreadingHTTPServer((host, port), Handler)
    print('Serving subtitles at http://' + host + ':' + str(port) + '/')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

def main():
    ap = argparse.ArgumentParser(description='Local web server for partial/final subtitles demo')
    ap.add_argument('--check-demo', action='store_true')
    ap.add_argument('--output', default='experiments/web_demo_metrics.json')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--duration', type=float, default=1.0)
    ap.add_argument('--interval', type=float, default=0.2)
    a = ap.parse_args()
    if a.check_demo:
        sys.exit(check_demo(a.output, a.duration, a.interval))
    serve(a.host, a.port)

if __name__ == '__main__':
    main()
