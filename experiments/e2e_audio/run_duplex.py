import argparse, json, math, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf
import importlib.metadata as im
try:
    import sounddevice as sd
except Exception:
    sd = None
try:
    import scipy.signal as sig
except Exception:
    sig = None
try:
    import sherpa_onnx
except Exception:
    sherpa_onnx = None

def make_clips(n, gap, sr=16000):
    clips=[]
    for i in range(n):
        dur=2.0
        t=np.arange(int(dur*sr), dtype=np.float32)/sr
        f=220+80*i
        env=np.hanning(len(t)).astype(np.float32)
        x=(np.sin(2*np.pi*f*t)+0.5*np.sin(2*np.pi*2*f*t)+0.25*np.sin(2*np.pi*3*f*t))*env
        clips.append(x.astype(np.float32))
    return clips

def record(clips, gap, sr):
    if sd is None:
        return None
    total=int((sum(len(c)/sr for c in clips)+gap*len(clips))*sr)
    try:
        rec=sd.rec(total, samplerate=sr, channels=1, dtype='float32')
        for c in clips:
            sd.play(c, samplerate=sr, blocking=False)
            time.sleep(len(c)/sr+gap)
        sd.wait()
        return np.asarray(rec, dtype=np.float32).reshape(-1)
    except Exception:
        return np.zeros(total, dtype=np.float32)

def analyze(clips, rec, gap, sr):
    peaks=[]; lags=[]
    max_lag=int(1.0*sr)
    for i,c in enumerate(clips):
        start=int(i*(len(c)/sr+gap)*sr)
        end=start+len(c)+max_lag
        seg=np.asarray(rec[start:end], dtype=np.float32)
        if len(seg)<len(c)+10:
            continue
        if sig is None:
            continue
        corr=sig.correlate(seg, c, mode='full')
        norm=math.sqrt(float(np.sum(seg.astype(np.float64)**2))*float(np.sum(c.astype(np.float64)**2)))
        if norm<=1e-12:
            continue
        peaks_arr=corr/norm
        k=int(np.argmax(peaks_arr))
        lag=k-(len(c)-1)
        peak=float(peaks_arr[k])
        peaks.append(peak)
        lags.append(lag)
    corr_peak=max(peaks) if peaks else 0.0
    corr_global=float(np.mean(peaks)) if peaks else 0.0
    drift=0.0
    if len(lags)>=2:
        period=int((len(clips[0])/sr+gap)*sr)
        slope=float(np.polyfit(np.arange(len(lags), dtype=np.float64), np.array(lags, dtype=np.float64), 1)[0])
        drift=slope/period*1e6
    valid=sum(1 for p in peaks if p>=0.6)
    return {'latency_samples_count': valid, 'corr_peak': corr_peak, 'corr_global': corr_global, 'drift_ppm': drift, 'valid_windows': valid, 'latency_ms': [float(l/sr*1000) for l in lags]}

def asr_count(rec, sr, model_dir):
    if sherpa_onnx is None:
        return 0
    md=Path(model_dir)
    paths=[md/'encoder.onnx', md/'decoder.onnx', md/'joiner.onnx', md/'tokens.txt']
    if not all(p.exists() for p in paths):
        return 0
    try:
        endpoint=sherpa_onnx.OnlineEndpointRule()
        endpoint.trailing_silence=1.5
        endpoint.min_trailing_silence=1.5
        endpoint.min_utterance_length=0.5
        recognizer=sherpa_onnx.OnlineRecognizer.from_transducer(tokens=str(paths[3]), encoder=str(paths[0]), decoder=str(paths[1]), joiner=str(paths[2]), num_threads=1, sample_rate=sr, feature_dim=80, decoding_method='greedy_search', provider='cpu', endpoint_config=endpoint)
        stream=recognizer.create_stream()
        finals=0
        chunk=1600
        for i in range(0, len(rec), chunk):
            stream.accept_waveform(sr, rec[i:i+chunk])
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            if recognizer.is_endpoint(stream):
                text=recognizer.get_result(stream)
                if text.strip():
                    finals+=1
                recognizer.reset(stream)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text=recognizer.get_result(stream)
        if text.strip():
            finals+=1
        return finals
    except Exception:
        return 0

def versions():
    d={}
    for pkg in ('numpy','scipy','sounddevice','soundfile','sherpa-onnx'):
        try:
            d[pkg]=im.version(pkg)
        except Exception:
            d[pkg]=None
    return d

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--engine', default='sherpa')
    p.add_argument('--clips', type=int, default=5)
    p.add_argument('--gap', type=float, default=1.2)
    p.add_argument('--output', required=True)
    p.add_argument('--model-dir', default='models/sherpa_streaming_zipformer_bilingual')
    a=p.parse_args()
    out=Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    sr=16000
    seed=0
    np.random.seed(seed)
    clips=make_clips(a.clips, a.gap, sr)
    total=int((sum(len(c)/sr for c in clips)+a.gap*len(clips))*sr)
    rec=record(clips, a.gap, sr)
    reason='ok'
    if rec is None:
        rec=np.zeros(total, dtype=np.float32)
        reason='no_audio'
    metrics=analyze(clips, rec, a.gap, sr)
    metrics.update({'engine':a.engine,'clips':a.clips,'gap':a.gap,'sample_rate':sr,'seed':seed,'timestamp':time.strftime('%Y-%m-%dT%H:%M:%S'),'versions':versions(),'reason':reason})
    metrics['final_count']=asr_count(rec, sr, a.model_dir)
    metrics['gate']='PASS' if metrics['latency_samples_count']>=3 and metrics['corr_peak']>=0.6 and abs(metrics['drift_ppm'])<500 and metrics['final_count']>=4 else 'FAIL'
    sf.write(out/'recording.wav', rec, sr)
    (out/'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    print(json.dumps(metrics))

if __name__=='__main__':
    try:
        main()
    except Exception as e:
        out=Path(sys.argv[sys.argv.index('--output')+1]) if '--output' in sys.argv else Path('experiments/e2e_audio/runs/e2e_duplex_sherpa_5clips')
        out.mkdir(parents=True, exist_ok=True)
        metrics={'latency_samples_count':0,'corr_peak':0.0,'corr_global':0.0,'drift_ppm':0.0,'valid_windows':0,'latency_ms':[],'final_count':0,'gate':'FAIL','reason':str(e)}
        try:
            sf.write(out/'recording.wav', np.zeros(16000, dtype=np.float32), 16000)
        except Exception:
            pass
        (out/'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
        print(json.dumps(metrics))
