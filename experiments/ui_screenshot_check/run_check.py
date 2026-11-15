import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("experiments/ui_screenshot_check")
RESULTS = ROOT / "results"
SHOTS = RESULTS / "screenshots"
METRICS = ROOT / "metrics.json"
URL = "http://localhost:8000"
SHOT = SHOTS / "ui.png"
SHOT_POSIX = SHOT.as_posix()

def write_metrics(status, exists, size, rc, duration, notes):
    ROOT.mkdir(parents=True, exist_ok=True)
    metrics = {
        "task_id": "ui_screenshot_check",
        "status": status,
        "screenshot_path": SHOT_POSIX,
        "screenshot_exists": bool(exists),
        "screenshot_size_bytes": int(size),
        "url": URL,
        "return_code": int(rc),
        "duration_sec": round(float(duration), 3),
        "notes": notes,
    }
    with open(METRICS, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=True, indent=2)
    print(json.dumps(metrics, ensure_ascii=True))

def main():
    start = time.time()
    rc = 1
    exists = False
    size = 0
    status = "fail"
    notes = "screenshot command not completed"
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "autonomy.screenshot", URL, SHOT_POSIX]
        proc = subprocess.run(cmd, check=True, text=True, capture_output=True, encoding="utf-8")
        rc = proc.returncode
        exists = SHOT.exists()
        size = SHOT.stat().st_size if exists else 0
        if exists and size > 0:
            status = "pass"
            notes = "screenshot file created; visual review not performed"
        else:
            status = "fail"
            notes = "screenshot command returned zero but file missing or empty"
    except Exception as exc:
        rc = 1
        exists = SHOT.exists()
        size = SHOT.stat().st_size if exists else 0
        status = "fail"
        notes = "screenshot command failed: " + str(exc)
    duration = time.time() - start
    write_metrics(status, exists, size, rc, duration, notes)
    return 0 if status == "pass" else 1

if __name__ == "__main__":
    sys.exit(main())
