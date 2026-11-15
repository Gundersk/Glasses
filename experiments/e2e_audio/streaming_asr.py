"""Общий потоковый ASR-модуль: единый интерфейс для sherpa-onnx и Vosk.

Интерфейс (один объект = один поток распознавания):
    asr, status = create_asr("sherpa" | "vosk")      # status.ok == False -> asr is None
    partial = asr.accept(chunk_f32, sample_rate=16000)  # текущий partial-текст сегмента
    if asr.is_endpoint():                            # сработал endpoint (пауза/конец фразы)
        final = asr.finalize()                       # финальный текст сегмента
        asr.reset()                                  # начать следующий сегмент
    ...
    final = asr.finalize()                           # в конце входа: сбросить остаток (EOF)
Ошибки: исключения внутри методов НЕ летят наружу; результат пустой, а asr.status.ok == False.
Вход: float32 моно в [-1, 1]. Если sample_rate != 16000 - ресемплинг scipy.signal.resample_poly
(по-чанково, на границах возможны артефакты; для файлов лучше заранее вызвать resample_to_16k).
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from math import gcd

import numpy as np

TARGET_SR = 16000
ROOT = pathlib.Path(__file__).resolve().parents[2]
SHERPA_DIR = ROOT / "models" / "sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16"
VOSK_DIR = ROOT / "models" / "vosk-model-small-ru-0.22"


@dataclass
class Status:
    ok: bool = True
    engine: str = ""
    message: str = ""
    version: str = ""
    config: dict = field(default_factory=dict)

    def as_dict(self):
        return {"ok": self.ok, "engine": self.engine, "message": self.message,
                "version": self.version, "config": self.config}


def resample_to_16k(x, sr):
    """float32 моно -> float32 16 кГц через resample_poly."""
    x = np.asarray(x, dtype=np.float32)
    if int(sr) == TARGET_SR:
        return x
    from scipy.signal import resample_poly
    g = gcd(int(sr), TARGET_SR)
    return np.asarray(resample_poly(x, TARGET_SR // g, int(sr) // g), dtype=np.float32)


class StreamingASR:
    """Базовый класс. Наследники реализуют _accept16/_is_endpoint/_finalize/_reset."""
    name = "base"

    def __init__(self):
        self.status = Status(engine=self.name)
        self._endpoint = False

    # --- публичный интерфейс
    def accept(self, chunk_f32, sample_rate: int = TARGET_SR) -> str:
        try:
            x = np.asarray(chunk_f32, dtype=np.float32)
            if x.ndim == 2:
                x = x.mean(axis=1)
            if int(sample_rate) != TARGET_SR:
                x = resample_to_16k(x, sample_rate)
            return self._accept16(x)
        except Exception as e:  # noqa: BLE001
            self._fail("accept", e)
            return ""

    def is_endpoint(self) -> bool:
        try:
            return bool(self._is_endpoint())
        except Exception as e:  # noqa: BLE001
            self._fail("is_endpoint", e)
            return False

    def finalize(self) -> str:
        try:
            return (self._finalize() or "").strip()
        except Exception as e:  # noqa: BLE001
            self._fail("finalize", e)
            return ""

    def reset(self) -> None:
        try:
            self._reset()
            self._endpoint = False
        except Exception as e:  # noqa: BLE001
            self._fail("reset", e)

    def _fail(self, where, e):
        self.status.ok = False
        self.status.message = f"{where}: {type(e).__name__}: {str(e)[:200]}"

    # --- реализация
    def _accept16(self, x):  # pragma: no cover
        raise NotImplementedError

    def _is_endpoint(self):  # pragma: no cover
        raise NotImplementedError

    def _finalize(self):  # pragma: no cover
        raise NotImplementedError

    def _reset(self):  # pragma: no cover
        raise NotImplementedError


class SherpaASR(StreamingASR):
    name = "sherpa"

    def __init__(self, model_dir=SHERPA_DIR, num_threads=2, rule1=2.4, rule2=0.8, rule3=20.0, flush_tail_s=0.3):
        super().__init__()
        import sherpa_onnx
        for f in ("tokens.txt", "encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx"):
            if not (pathlib.Path(model_dir) / f).is_file():
                raise FileNotFoundError(f"нет файла модели: {pathlib.Path(model_dir) / f}")
        md = pathlib.Path(model_dir)
        self.status.version = f"sherpa-onnx {sherpa_onnx.__version__}"
        self.status.config = {"model_dir": str(md), "num_threads": num_threads, "decoding": "greedy_search",
                              "provider": "cpu", "sample_rate": TARGET_SR, "feature_dim": 80,
                              "rule1_min_trailing_silence": rule1, "rule2_min_trailing_silence": rule2,
                              "rule3_min_utterance_length": rule3, "flush_tail_s": flush_tail_s}
        self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(md / "tokens.txt"), encoder=str(md / "encoder.int8.onnx"),
            decoder=str(md / "decoder.onnx"), joiner=str(md / "joiner.int8.onnx"),
            num_threads=num_threads, sample_rate=TARGET_SR, feature_dim=80,
            enable_endpoint_detection=True, rule1_min_trailing_silence=rule1,
            rule2_min_trailing_silence=rule2, rule3_min_utterance_length=rule3,
            decoding_method="greedy_search", provider="cpu")
        self._flush_tail = int(flush_tail_s * TARGET_SR)
        self._stream = self._rec.create_stream()
        self._finished = False

    def _text(self):
        r = self._rec.get_result(self._stream)
        return r if isinstance(r, str) else getattr(r, "text", str(r))

    def _accept16(self, x):
        if self._finished:
            return ""
        self._stream.accept_waveform(TARGET_SR, x)
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
        self._endpoint = bool(self._rec.is_endpoint(self._stream))
        return self._text().strip()

    def _is_endpoint(self):
        return self._endpoint

    def _finalize(self):
        if not self._endpoint and not self._finished:
            # конец входа без endpoint: дополняем нулями правый контекст и закрываем поток
            if self._flush_tail:
                self._stream.accept_waveform(TARGET_SR, np.zeros(self._flush_tail, dtype=np.float32))
            self._stream.input_finished()
            self._finished = True
            while self._rec.is_ready(self._stream):
                self._rec.decode_stream(self._stream)
        return self._text()

    def _reset(self):
        if self._finished:
            self._stream = self._rec.create_stream()
            self._finished = False
        else:
            self._rec.reset(self._stream)


def _ascii_model_path(md, status):
    """Vosk (C++) на Windows не открывает абсолютные пути с кириллицей ('Failed to create a model').
    Берём относительный от cwd ASCII-путь, иначе junction в temp. Факт фиксируем в status.config."""
    import os
    import subprocess
    import tempfile
    s = str(md)
    if s.isascii():
        return s
    try:
        rel = os.path.relpath(s)
        if rel.isascii() and (pathlib.Path(rel)).is_dir():
            status.config["model_path_used"] = rel
            return rel
    except ValueError:  # другой диск
        pass
    link = pathlib.Path(tempfile.gettempdir()) / "vosk_model_ascii_link"
    if not link.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), s], capture_output=True, check=True)
    status.config["model_path_used"] = str(link)
    return str(link)


class VoskASR(StreamingASR):
    name = "vosk"

    def __init__(self, model_dir=VOSK_DIR):
        super().__init__()
        import vosk
        md = pathlib.Path(model_dir)
        if not md.is_dir():
            raise FileNotFoundError(f"нет модели vosk: {md}")
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self.status.version = f"vosk {getattr(vosk, '__version__', '0.3.45')}"
        self.status.config = {"model_dir": str(md), "sample_rate": TARGET_SR, "endpointer": "по умолчанию Vosk"}
        self._model = vosk.Model(_ascii_model_path(md, self.status))
        self._rec = vosk.KaldiRecognizer(self._model, TARGET_SR)
        self._final_text = ""

    def _accept16(self, x):
        pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        if self._rec.AcceptWaveform(pcm):
            self._endpoint = True
            self._final_text = json.loads(self._rec.Result()).get("text", "")
            return self._final_text.strip()
        self._endpoint = False
        return json.loads(self._rec.PartialResult()).get("partial", "").strip()

    def _is_endpoint(self):
        return self._endpoint

    def _finalize(self):
        if self._endpoint:
            return self._final_text
        return json.loads(self._rec.FinalResult()).get("text", "")

    def _reset(self):
        # после Result()/FinalResult() Vosk сам сбрасывает состояние; новый распознаватель дёшев
        self._rec = self._vosk.KaldiRecognizer(self._model, TARGET_SR)
        self._final_text = ""


ENGINES = {"sherpa": SherpaASR, "vosk": VoskASR}


def create_asr(engine: str, **kw):
    """Возвращает (asr | None, Status). Не бросает исключений."""
    cls = ENGINES.get(engine)
    if cls is None:
        return None, Status(ok=False, engine=engine, message=f"неизвестный движок: {engine}; доступны: {', '.join(ENGINES)}")
    try:
        asr = cls(**kw)
        return asr, asr.status
    except Exception as e:  # noqa: BLE001
        return None, Status(ok=False, engine=engine, message=f"init: {type(e).__name__}: {str(e)[:300]}")
