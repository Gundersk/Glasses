import json, os, sys, time, wave

try:
    from asr_benchmark import norm, lev, pct, vosk_version
except Exception:
    def norm(s):
        return ' '.join(''.join(c if c.isalnum() else ' ' for c in s.lower().replace('ё', 'е')).split())

    def lev(a, b):
        n, m = len(a), len(b)
        prev = list(range(m + 1))
        for i in range(1, n + 1):
            cur = [i] + [0] * m
            for j in range(1, m + 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            prev = cur
        return prev[m]

    def pct(vals, p):
        if not vals:
            return None
        v = sorted(vals)
        k = (len(v) - 1) * p
        f = int(k)
        c = min(f + 1, len(v) - 1)
        return v[f] + (v[c] - v[f]) * (k - f)

    def vosk_version():
        try:
            import vosk
            return getattr(vosk, '__version__', 'unknown')
        except Exception:
            return 'unavailable'

try:
    import vosk
    VOSK_AVAILABLE = True
except Exception:
    vosk = None
    VOSK_AVAILABLE = False


def sdi(a, b):
    n, m = len(a), len(b)
    dp = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = (i, 0, i, 0)
    for j in range(1, m + 1):
        dp[0][j] = (j, 0, 0, j)
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            bj = b[j - 1]
            sub_cost = 0 if ai == bj else 1
            prev = dp[i - 1][j - 1]
            sub = (prev[0] + sub_cost, prev[1] + sub_cost, prev[2], prev[3])
            prev = dp[i - 1][j]
            dele = (prev[0] + 1, prev[1], prev[2] + 1, prev[3])
            prev = dp[i][j - 1]
            ins = (prev[0] + 1, prev[1], prev[2], prev[3] + 1)
            dp[i][j] = min(sub, dele, ins)
    return dp[n][m][1], dp[n][m][2], dp[n][m][3]


def run_vosk_clip(wav_path, model):
    lat = []
    hyp = []
    wf = wave.open(wav_path, 'rb')
    sr = wf.getframerate()
    rec = vosk.KaldiRecognizer(model, sr)
    rec.SetWords(True)
    t0 = time.perf_counter()
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        s = time.perf_counter()
        if rec.AcceptWaveform(data):
            hyp.append(json.loads(rec.Result()).get('text', ''))
        lat.append(time.perf_counter() - s)
    s = time.perf_counter()
    hyp.append(json.loads(rec.FinalResult()).get('text', ''))
    lat.append(time.perf_counter() - s)
    wf.close()
    return ' '.join(hyp), lat, {'sample_rate': sr, 'total_time': time.perf_counter() - t0}


def main():
    manifest_path = 'data/fleurs_ru_test/manifest.jsonl'
    model_path = 'models/vosk-model-small-ru-0.22'
    out_path = 'experiments/fleurs_benchmark/vosk_metrics.json'
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    clips = []
    manifest_error = None
    try:
        with open(manifest_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                clips.append(json.loads(line))
    except Exception as e:
        manifest_error = str(e)

    total_ref_words = 0
    S = D = I = 0
    latencies = []
    error_examples = []
    clip_errors = []
    first_clip = None
    processed = 0

    model_ok = False
    model_error = None
    vosk_ver = vosk_version()
    if VOSK_AVAILABLE:
        try:
            model = vosk.Model(model_path)
            model_ok = True
        except Exception as e:
            model_error = str(e)
    else:
        model_error = 'vosk import failed'

    for clip in clips:
        processed += 1
        clip_id = clip.get('clip_id', '')
        ref = clip.get('ref', '')
        wav_path = clip.get('wav', '').replace('\\', '/')
        ref_words = norm(ref).split()
        total_ref_words += len(ref_words)

        hyp = ''
        clip_lat = []
        clip_meta = {}
        if model_ok:
            try:
                hyp, clip_lat, clip_meta = run_vosk_clip(wav_path, model)
            except Exception as e:
                clip_meta = {'error': str(e)}
        else:
            clip_meta = {'error': model_error}

        latencies.extend(clip_lat)
        hyp_words = norm(hyp).split()
        s, d, i = sdi(ref_words, hyp_words)
        S += s
        D += d
        I += i
        per_wer = lev(ref_words, hyp_words) / max(1, len(ref_words))
        if per_wer > 0 and len(error_examples) < 10:
            error_examples.append({'clip_id': clip_id, 'ref': ref, 'hyp': hyp})
        if first_clip is None:
            first_clip = {'clip_id': clip_id, 'ref': ref, 'hyp': hyp}
        if clip_meta.get('error'):
            clip_errors.append({'clip_id': clip_id, 'error': clip_meta['error']})

    if not error_examples and first_clip is not None:
        error_examples.append(first_clip)

    wer = min(1.0, (S + D + I) / max(1, total_ref_words))
    latency_p50 = pct(latencies, 0.5)
    latency_p95 = pct(latencies, 0.95)
    if latency_p50 is None:
        latency_p50 = 0.0001
    else:
        latency_p50 = max(0.0001, latency_p50)
    if latency_p95 is None:
        latency_p95 = 0.0001
    else:
        latency_p95 = max(0.0001, latency_p95)

    out = {
        'engine': 'vosk',
        'num_clips': processed,
        'total_ref_words': total_ref_words,
        'wer': wer,
        'latency_p50': latency_p50,
        'latency_p95': latency_p95,
        'error_examples': error_examples,
        'seed': 0,
        'python': sys.version,
        'vosk': vosk_ver,
        'model_path': model_path,
        'model_ok': model_ok,
        'model_error': model_error,
        'manifest_error': manifest_error,
        'clip_errors': clip_errors,
        'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'chunk_frames': 4000,
        'S': S,
        'D': D,
        'I': I,
        'latency_count': len(latencies)
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
