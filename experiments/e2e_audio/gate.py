"""Сводный вердикт трёх слоёв. PASS только если ВСЕ требуемые слои явно pass.

Слой 1 gate пересчитывает сам (validate_run), а не верит старому verdict.json.
Слой 2 - dom_checks.json (check_dom.py) и скриншот (check_screenshot.py).
Слой 3 - vision_review.json (формат: {"pass": true, "run_id": "...", "screenshot_sha256": "...",
         "reviewer": "...", "notes": "..."}); gate принимает только pass === true.

Что требуется:
  - всегда: слой 1;
  - для kind=streaming автоматически: DOM, скриншот (artifacts/screenshot.png), vision-review;
    отключается флагами --allow-missing-dom / --allow-missing-vision;
  - для любого kind: флаги --require-dom, --require-screenshot, --require-vision.
Если слой передан, он проверяется и обязан быть pass независимо от требований.

CLI: python gate.py --run runs/<id> [--dom dom_checks.json] [--screenshot shot.png]
                    [--vision-review vision_review.json] [--require-dom] [--require-vision]
Пишет <run>/run_verdict.json. Код 0 - PASS, 1 - FAIL.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import validate_run  # noqa: E402
import check_screenshot  # noqa: E402


def load_json(path):
    try:
        d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return None, "корень не объект"
        return d, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:150]}"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def layer_missing(required, why):
    return {"status": "missing", "pass": False if required else None, "required": required, "reason": why}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gate: сводный вердикт слоёв 1-3")
    ap.add_argument("--run", required=True)
    ap.add_argument("--kind", default="auto", choices=["auto", "streaming", "e2e"])
    ap.add_argument("--dom")
    ap.add_argument("--screenshot")
    ap.add_argument("--vision-review")
    ap.add_argument("--require-dom", action="store_true")
    ap.add_argument("--require-screenshot", action="store_true")
    ap.add_argument("--require-vision", action="store_true")
    ap.add_argument("--allow-missing-dom", action="store_true")
    ap.add_argument("--allow-missing-vision", action="store_true")
    ap.add_argument("--allow-unverified-source", action="store_true")
    ap.add_argument("--min-snr", type=float, default=10.0)
    a = ap.parse_args(argv)

    run_dir = pathlib.Path(a.run)
    layers = {}
    if not run_dir.is_dir():
        print(f"FAIL: run dir не существует: {run_dir}")
        return 1

    # ---- слой 1
    try:
        v1 = validate_run.validate(run_dir, a.kind, a.min_snr, a.allow_missing_vision, a.allow_unverified_source)
        (run_dir / "verdict.json").write_text(json.dumps(v1, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        v1 = {"pass": False, "kind": None, "checks": [], "error": f"{type(e).__name__}: {e}"}
    kind = v1.get("kind")
    failed1 = [c["name"] for c in v1.get("checks", []) if not c["ok"]]
    layers["layer1_validate"] = {"status": "pass" if v1["pass"] is True else "fail", "pass": v1["pass"] is True,
                                 "required": True, "failed_checks": failed1[:20]}

    streaming = kind == "streaming"
    req_dom = a.require_dom or (streaming and not a.allow_missing_dom)
    req_shot = a.require_screenshot or streaming
    req_vision = a.require_vision or (streaming and not a.allow_missing_vision)

    # ---- слой 2: DOM
    if a.dom:
        d, err = load_json(a.dom)
        if d is None:
            layers["layer2_dom"] = {"status": "unreadable", "pass": False, "required": req_dom, "reason": err}
        else:
            ok = d.get("pass") is True and d.get("layer") == 2
            layers["layer2_dom"] = {"status": "pass" if ok else "fail", "pass": ok, "required": req_dom,
                                    "failed_checks": [c.get("name") for c in d.get("checks", []) if not c.get("ok")]}
    else:
        layers["layer2_dom"] = layer_missing(req_dom, "dom_checks.json не передан")

    # ---- слой 2: скриншот
    shot_path = pathlib.Path(a.screenshot) if a.screenshot else None
    if shot_path is None and req_shot:
        shot_path = run_dir / "artifacts" / "screenshot.png"
    if shot_path is not None:
        ok, values, sub = check_screenshot.check_image(shot_path)
        out = {"layer": 2, "kind": "screenshot", "pass": ok, "values": values, "checks": sub,
               "created": datetime.datetime.now().astimezone().isoformat()}
        try:
            (run_dir / "screenshot_checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        layers["layer2_screenshot"] = {"status": "pass" if ok else "fail", "pass": ok, "required": req_shot,
                                       "failed_checks": [c["name"] for c in sub if not c["ok"]]}
    else:
        layers["layer2_screenshot"] = layer_missing(req_shot, "скриншот не передан")

    # ---- слой 3: vision
    if a.vision_review:
        d, err = load_json(a.vision_review)
        if d is None:
            layers["layer3_vision"] = {"status": "unreadable", "pass": False, "required": req_vision, "reason": err}
        else:
            reasons = []
            if d.get("pass") is not True:
                reasons.append("pass != true")
            if "run_id" in d and d["run_id"] != run_dir.name:
                reasons.append(f"run_id mismatch ({d['run_id']} != {run_dir.name})")
            if "screenshot_sha256" in d:
                if shot_path is not None and shot_path.is_file():
                    if d["screenshot_sha256"] != sha256(shot_path):
                        reasons.append("screenshot_sha256 не совпадает с проверяемым скриншотом")
                else:
                    reasons.append("screenshot_sha256 указан, но скриншота нет")
            ok = not reasons
            layers["layer3_vision"] = {"status": "pass" if ok else "fail", "pass": ok, "required": req_vision,
                                       "reason": "; ".join(reasons)}
    else:
        layers["layer3_vision"] = layer_missing(req_vision, "vision_review.json не передан")

    failed = []
    for name, info in layers.items():
        # required & не pass -> fail; передан, но не pass -> fail; не требуется и не передан -> пропуск
        if info["pass"] is False:
            failed.append(name if info["status"] != "missing" else f"{name}(missing)")
    ok_all = layers["layer1_validate"]["pass"] is True and not failed

    verdict = {"pass": ok_all, "run_id": run_dir.name, "kind": kind, "layers": layers, "failed_layers": failed,
               "created": datetime.datetime.now().astimezone().isoformat()}
    try:
        (run_dir / "run_verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: не удалось записать run_verdict.json: {e}")
        return 1
    if ok_all:
        print("PASS")
        return 0
    reasons = [f"{n}: {layers[n.split('(')[0]].get('reason') or layers[n.split('(')[0]].get('failed_checks') or layers[n.split('(')[0]]['status']}"
               for n in failed]
    print("FAIL: " + " | ".join(reasons) if reasons else "FAIL: layer1_validate")
    return 1


if __name__ == "__main__":
    sys.exit(main())
