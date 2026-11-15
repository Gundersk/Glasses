import argparse,json,os,random,sys,time
random.seed(0)
def norm(s): return ' '.join(''.join(c if c.isalnum() else ' ' for c in s.lower().replace('ё','е')).split())
def lev(a,b):
 n,m=len(a),len(b); prev=list(range(m+1))
 for i in range(1,n+1):
  cur=[i]+[0]*m
  for j in range(1,m+1):
   cur[j]=min(prev[j]+1,cur[j-1]+1,prev[j-1]+(a[i-1]!=b[j-1]))
  prev=cur
 return prev[m]
def wer(ref,hyp):
 r=norm(ref).split(); h=norm(hyp).split(); return lev(r,h)/max(1,len(r))
def pct(vals,p):
 if not vals: return None
 v=sorted(vals); k=(len(v)-1)*p; f=int(k); c=min(f+1,len(v)-1); return v[f]+(v[c]-v[f])*(k-f)
def vosk_version():
 try:
  import vosk
  return getattr(vosk,'__version__','unknown')
 except Exception:
  return 'unavailable'
def run_vosk(audio,model):
 try:
  import wave,vosk
 except Exception as e:
  return None,None,{'error':str(e),'vosk':vosk_version()}
 try:
  wf=wave.open(audio,'rb'); sr=wf.getframerate(); m=vosk.Model(model); rec=vosk.KaldiRecognizer(m,sr); rec.SetWords(True)
 except Exception as e:
  return None,None,{'error':str(e),'vosk':vosk_version()}
 lat=[]; hyp=[]; t0=time.perf_counter()
 while True:
  data=wf.readframes(4000)
  if not data: break
  s=time.perf_counter()
  if rec.AcceptWaveform(data):
   hyp.append(json.loads(rec.Result()).get('text',''))
  lat.append(time.perf_counter()-s)
 s=time.perf_counter(); hyp.append(json.loads(rec.FinalResult()).get('text','')); lat.append(time.perf_counter()-s); wf.close()
 return ' '.join(hyp),lat,{'sample_rate':sr,'model':model,'total_time':time.perf_counter()-t0,'vosk':vosk_version()}
def main():
 ap=argparse.ArgumentParser(description='ASR benchmark: WER and latency p50/p95')
 ap.add_argument('--audio'); ap.add_argument('--ref'); ap.add_argument('--out',default='reports/asr_benchmark.json'); ap.add_argument('--model',default='models/vosk-small-ru')
 a=ap.parse_args()
 if not a.audio: ap.error('--audio required')
 if not a.ref: ap.error('--ref required')
 try: ref=open(a.ref,encoding='utf-8').read()
 except Exception as e: print(json.dumps({'error':str(e)})); sys.exit(1)
 hyp,lat,meta=run_vosk(a.audio,a.model)
 if hyp is None: print(json.dumps(meta)); sys.exit(1)
 out={'audio':a.audio,'ref':a.ref,'hyp':hyp,'wer':wer(ref,hyp),'latency_p50':pct(lat,0.5),'latency_p95':pct(lat,0.95),'latency_count':len(lat),'seed':0,'python':sys.version,'vosk':meta.get('vosk'),'time':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'meta':meta}
 d=os.path.dirname(a.out)
 if d: os.makedirs(d,exist_ok=True)
 with open(a.out,'w',encoding='utf-8') as f: json.dump(out,f,ensure_ascii=False,indent=2)
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__': main()