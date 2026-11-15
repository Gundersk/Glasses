# -*- coding: utf-8 -*-
"""Скриншот страницы для UI-метрик и отчётов.

Использование (доступно исполнителю как команда):
    python -m autonomy.screenshot http://127.0.0.1:8765/ experiments/xxx/results/screenshots/ui.png [--full] [--wait-ms 2000] [--timeout-ms 30000]

Нужен playwright + chromium (установка один раз: pip install playwright; python -m playwright install chromium).
"""
import sys


def main(argv):
    if len(argv) < 3:
        print("использование: python -m autonomy.screenshot URL OUT.png [--full] [--wait-ms N] [--timeout-ms N]")
        return 2
    url, out = argv[1], argv[2]
    flags = argv[3:]
    full = "--full" in flags
    wait_ms = 1500
    timeout_ms = 30000
    for i, f in enumerate(flags):
        if f == "--wait-ms" and i + 1 < len(flags):
            wait_ms = int(flags[i + 1])
        if f == "--timeout-ms" and i + 1 < len(flags):
            timeout_ms = int(flags[i + 1])

    try:
        from pathlib import Path
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright не установлен. Выполните: pip install playwright; python -m playwright install chromium")
        return 3

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=out, full_page=full)
        browser.close()
    print(f"скриншот сохранён: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
