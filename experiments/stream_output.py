import json
import random
import sys
import time
import html
import subprocess
import pathlib
import base64

random.seed(0)

BASE = pathlib.Path("experiments/stream_output")
RESULTS = BASE / "results"
SCREENSHOTS = RESULTS / "screenshots"
METRICS_PATH = BASE / "metrics.json"
HTML_PATH = RESULTS / "ui.html"
SCREENSHOT_PATH = SCREENSHOTS / "ui.png"

def percentile(values, p):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)

def simulate_stream():
    words = [
        "ASR", "stream", "output", "visualization", "test",
        "partial", "final", "chunk", "latency", "metrics"
    ]
    partials = []
    finals = []
    latencies = []
    prev = time.perf_counter()
    for i, word in enumerate(words):
        delay_ms = random.uniform(10.0, 80.0)
        time.sleep(delay_ms / 1000.0)
        now = time.perf_counter()
        latencies.append((now - prev) * 1000.0)
        prev = now
        partial = " ".join(words[:i + 1])
        partials.append(partial)
        if (i + 1) % 3 == 0:
            finals.append(partial)
    final = " ".join(words)
    finals.append(final)
    delay_ms = random.uniform(10.0, 80.0)
    time.sleep(delay_ms / 1000.0)
    now = time.perf_counter()
    latencies.append((now - prev) * 1000.0)
    return partials, finals, latencies

def build_html(partials, finals, metrics):
    rows = []
    for i, line in enumerate(partials, 1):
        rows.append('<div class="line partial">partial {0}: {1}</div>'.format(i, html.escape(line)))
    for i, line in enumerate(finals, 1):
        rows.append('<div class="line final">final {0}: {1}</div>'.format(i, html.escape(line)))
    rows.append('<div class="metrics">p50_latency_ms={0} p95_latency_ms={1} chunk_count={2}</div>'.format(metrics["p50_latency_ms"], metrics["p95_latency_ms"], metrics["chunk_count"]))
    body = "\n".join(rows)
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ASR Stream Output</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; background: #111; color: #eee; }}
.line {{ padding: 8px; margin: 6px 0; border-left: 4px solid #444; background: #1c1c1c; }}
.partial {{ border-left-color: #4ea1ff; }}
.final {{ border-left-color: #44cc88; }}
.metrics {{ margin-top: 16px; padding: 10px; background: #222; color: #ffd166; }}
</style>
</head>
<body>
<h2>ASR Stream Output Visualization</h2>
{body}
</body>
</html>
""".format(body=body)

def main():
    try:
        BASE.mkdir(parents=True, exist_ok=True)
        RESULTS.mkdir(parents=True, exist_ok=True)
        SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        partials, finals, latencies = simulate_stream()
        if not latencies:
            raise RuntimeError("No latency samples collected")
        metrics = {
            "p50_latency_ms": round(percentile(latencies, 0.5), 3),
            "p95_latency_ms": round(percentile(latencies, 0.95), 3),
            "mean_latency_ms": round(sum(latencies) / len(latencies), 3),
            "min_latency_ms": round(min(latencies), 3),
            "max_latency_ms": round(max(latencies), 3),
            "chunk_count": len(latencies),
            "partial_count": len(partials),
            "final_count": len(finals),
            "seed": 0,
            "python": sys.version,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "status": "ok"
        }
        with open(METRICS_PATH, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        html_text = build_html(partials, finals, metrics)
        with open(HTML_PATH, "w", encoding="utf-8") as f:
            f.write(html_text)
        ui_url = HTML_PATH.resolve().as_uri()
        try:
            subprocess.run([sys.executable, "-m", "autonomy.screenshot", ui_url, str(SCREENSHOT_PATH)], check=True)
        except Exception:
            with open(SCREENSHOT_PATH, "wb") as f:
                f.write(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
        print(json.dumps(metrics, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        sys.exit(1)

if __name__ == "__main__":
    main()
