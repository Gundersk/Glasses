import json, os, socket, subprocess, sys, time, urllib.request

def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def write_metrics(path, metrics):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

def wait_ready(url, timeout=15.0, interval=0.2):
    start = time.time()
    last_error = None
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url + 'health', timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception as e:
            last_error = str(e)
        time.sleep(interval)
    raise RuntimeError('Server not ready: ' + str(last_error))

def main():
    port = free_port()
    url = 'http://127.0.0.1:' + str(port) + '/'
    out_path = 'experiments/web_demo/screenshots/ui.png'
    metrics_path = 'experiments/web_demo/results/metrics.json'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [sys.executable, 'experiments/web_subtitles_demo.py', '--host', '127.0.0.1', '--port', str(port)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    start = time.time()
    try:
        wait_ready(url)
        subprocess.run([sys.executable, '-m', 'autonomy.screenshot', url, out_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        exists = os.path.exists(out_path)
        if not exists:
            raise RuntimeError('Screenshot file not created')
        metrics = {
            'screenshot_exists': bool(exists),
            'screenshot_path': out_path,
            'server_url': url,
            'duration': float(time.time() - start),
            'seed': 0,
            'python': sys.version,
            'time': time.strftime('%Y-%m-%dT%H:%M:%S%z')
        }
        write_metrics(metrics_path, metrics)
        print('OK: ' + out_path)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

if __name__ == '__main__':
    sys.exit(main())
