"""Слой 2: детерминированная проверка скриншота страницы субтитров.

Проверяет не «красоту», а то, что на картинке есть текстоподобное содержимое:
  - файл существует, размер > 5 КБ;
  - картинка не одноцветная (std яркости > 2);
  - есть >= 2 горизонтальных полос «строк текста»;
  - нижняя треть не пустая.

Полярность (светлый текст на тёмном или наоборот) не важна: «передний план» -
пиксели, отличающиеся от медианной яркости фона больше чем на FG_DELTA уровней.
Это эвристика: она НЕ читает текст и не отличает субтитры от любых других полос.

CLI: python check_screenshot.py --path shot.png --out screenshot_checks.json
Код выхода 0 при pass, 1 иначе.
"""
import argparse
import datetime
import json
import pathlib
import sys

MIN_BYTES = 5 * 1024
MIN_STD = 2.0
FG_DELTA = 64          # отличие яркости от фона, 0..255
ROW_FRAC_MIN = 0.03    # доля «переднего плана» в строке пикселей: 3 %
ROW_FRAC_MAX = 0.40    # ... 40 %
MIN_BAND_HEIGHT = 3    # полоса короче 3 строк пикселей - линия, а не текст
MIN_BANDS = 2
BOTTOM_FG_MIN = 0.002  # доля переднего плана в нижней трети >= 0.2 %


def _check(name, ok, expected, actual, detail=""):
    return {"name": name, "ok": bool(ok), "expected": expected, "actual": actual, "detail": detail}


def count_bands(mask_rows):
    """mask_rows: bool-массив по строкам. Возвращает список (start, height) полос >= MIN_BAND_HEIGHT."""
    bands = []
    start = None
    for i, v in enumerate(list(mask_rows) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= MIN_BAND_HEIGHT:
                bands.append((start, i - start))
            start = None
    return bands


def check_image(path):
    """Возвращает (pass, values, checks). Не бросает исключений на битых данных."""
    path = pathlib.Path(path)
    checks = []
    values = {"path": str(path)}
    if not path.is_file():
        checks.append(_check("file_exists", False, "file", "missing", str(path)))
        return False, values, checks
    size = path.stat().st_size
    values["size_bytes"] = size
    checks.append(_check("file_exists", True, "file", "present"))
    checks.append(_check("size_gt_5kb", size > MIN_BYTES, f">{MIN_BYTES}", size))
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            values["width"], values["height"] = im.size
            gray = np.asarray(im.convert("L"), dtype=np.float64)
    except Exception as e:  # noqa: BLE001
        checks.append(_check("image_readable", False, "readable png", f"{type(e).__name__}", str(e)[:200]))
        return False, values, checks
    checks.append(_check("image_readable", True, "readable png", f"{values['width']}x{values['height']}"))
    if gray.size == 0 or gray.ndim != 2:
        checks.append(_check("image_nonempty", False, "h*w>0", str(gray.shape)))
        return False, values, checks

    std = float(gray.std())
    values["pixel_std"] = std
    checks.append(_check("not_monochrome", std > MIN_STD, f"std>{MIN_STD}", round(std, 3)))

    bg = float(np.median(gray))
    fg = np.abs(gray - bg) > FG_DELTA
    row_frac = fg.mean(axis=1)
    rows_ok = (row_frac >= ROW_FRAC_MIN) & (row_frac <= ROW_FRAC_MAX)
    bands = count_bands(rows_ok)
    values["background_gray"] = bg
    values["fg_pixel_fraction"] = float(fg.mean())
    values["text_like_bands"] = len(bands)
    values["text_like_band_rows"] = [{"start": s, "height": h} for s, h in bands[:50]]
    checks.append(_check("text_bands", len(bands) >= MIN_BANDS, f">={MIN_BANDS}", len(bands),
                         f"полосы строк с долей переднего плана {ROW_FRAC_MIN:.0%}-{ROW_FRAC_MAX:.0%}, "
                         f"высота >= {MIN_BAND_HEIGHT} px, фон={bg:.0f}, порог отличия={FG_DELTA}"))

    third = gray.shape[0] // 3
    bottom_frac = float(fg[gray.shape[0] - third:, :].mean()) if third > 0 else 0.0
    values["bottom_third_fg_fraction"] = bottom_frac
    checks.append(_check("bottom_third_nonempty", bottom_frac >= BOTTOM_FG_MIN,
                         f">={BOTTOM_FG_MIN}", round(bottom_frac, 5)))
    return all(c["ok"] for c in checks), values, checks


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", required=True, help="путь к png")
    ap.add_argument("--out", required=True, help="куда писать screenshot_checks.json")
    a = ap.parse_args(argv)
    try:
        ok, values, checks = check_image(a.path)
    except Exception as e:  # noqa: BLE001
        ok, values, checks = False, {"path": a.path}, [_check("unexpected_error", False, "no error", type(e).__name__, str(e)[:200])]
    res = {"layer": 2, "kind": "screenshot", "pass": ok, "values": values, "checks": checks,
           "created": datetime.datetime.now().astimezone().isoformat()}
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in checks:
        print(f"{c['name']:<24} {'ok' if c['ok'] else 'FAIL':<5} expected={c['expected']} actual={c['actual']}")
    print("SCREENSHOT PASS" if ok else "SCREENSHOT FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
