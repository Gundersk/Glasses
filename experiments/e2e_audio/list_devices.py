"""List audio devices (sounddevice) and write out/devices.json."""
import json
import pathlib
import sys

import sounddevice as sd

OUT = pathlib.Path(__file__).resolve().parent / "out"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    hostapis = sd.query_hostapis()
    default_in, default_out = sd.default.device
    devices = sd.query_devices()
    rows = []
    for i, d in enumerate(devices):
        rows.append({
            "index": i,
            "name": d["name"],
            "hostapi": hostapis[d["hostapi"]]["name"],
            "max_input_channels": d["max_input_channels"],
            "max_output_channels": d["max_output_channels"],
            "default_samplerate": d["default_samplerate"],
            "is_default_input": i == default_in,
            "is_default_output": i == default_out,
        })
    info = {
        "sounddevice": sd.__version__,
        "portaudio": sd.get_portaudio_version()[1],
        "default_input_index": default_in,
        "default_output_index": default_out,
        "devices": rows,
    }
    (OUT / "devices.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"portaudio: {info['portaudio']}")
    print(f"default input idx={default_in}  default output idx={default_out}")
    print(f"{'idx':>3} {'in':>2} {'out':>3} {'sr':>7} {'def':<4} {'hostapi':<22} name")
    for r in rows:
        flag = ("I" if r["is_default_input"] else "") + ("O" if r["is_default_output"] else "")
        print(f"{r['index']:>3} {r['max_input_channels']:>2} {r['max_output_channels']:>3} "
              f"{r['default_samplerate']:>7.0f} {flag:<4} {r['hostapi']:<22} {r['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
