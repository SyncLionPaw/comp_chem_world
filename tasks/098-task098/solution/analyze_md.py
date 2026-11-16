#!/usr/bin/env python3
import cmath, json, math, sys
from pathlib import Path

assets, outdir = map(Path, sys.argv[1:3])
PRESSURES=[0.,.5,1.65,2.4,3.06,4.09,4.7,5.48,6.3,7.25,8.,9.6]
NFFT=65536
C=2.99792458e10; MU=3.0738408378142946e-6

def fft(values):
    a=[complex(v,0) for v in values]; n=len(a); j=0
    for i in range(1,n):
        bit=n>>1
        while j&bit: j^=bit; bit>>=1
        j^=bit
        if i<j: a[i],a[j]=a[j],a[i]
    size=2
    while size<=n:
        half=size//2; root=cmath.exp(-2j*math.pi/size)
        for start in range(0,n,size):
            w=1+0j
            for k in range(half):
                u=a[start+k]; v=a[start+k+half]*w
                a[start+k]=u+v; a[start+k+half]=u-v; w*=root
        size*=2
    return a

def read_centroids(path):
    layers=[[] for _ in range(6)]
    for line in path.open(encoding="utf-8"):
        text=line.strip()
        if not text or text.startswith("#"): continue
        values=[float(x) for x in text.split()[:18]]
        for j in range(6): layers[j].append(values[3*j:3*j+3])
    if len(layers[0])<2: raise ValueError(f"{path.name}: too few samples")
    return layers

def projected_power(layers, axis):
    n=len(layers[0]); eigen=[math.cos(math.pi*5*(j+.5)/6) for j in range(6)]
    means=[sum(row[axis] for row in layer)/n for layer in layers]
    drift=[layers[j][-1][axis]-layers[j][0][axis] for j in range(6)]
    signal=[]
    for i in range(n):
        t=i/(n-1)-.5
        signal.append(sum(eigen[j]*(layers[j][i][axis]-means[j]-t*drift[j]) for j in range(6))*(.5-.5*math.cos(2*math.pi*i/(n-1))))
    signal.extend([0.0]*(NFFT-n))
    transform=fft(signal); df=1/(NFFT*1e-15*C)
    return [(abs(transform[k])**2,k*df) for k in range(1,NFFT//2)]

def candidates(powers, lo, hi):
    band=[i for i,(_,nu) in enumerate(powers) if lo<=nu<=hi]
    peak=max(powers[i][0] for i in band)
    result=[]
    for i in band:
        if powers[i][0]<peak*0.04 or powers[i][0]<powers[i-1][0] or powers[i][0]<powers[i+1][0]:
            continue
        left=math.log(max(powers[i-1][0],1e-300)); center=math.log(max(powers[i][0],1e-300)); right=math.log(max(powers[i+1][0],1e-300))
        den=left-2*center+right
        offset=0.5*(left-right)/den if den else 0.
        result.append((powers[i][1]+offset*(powers[i][1]-powers[i-1][1]),powers[i][0]))
    return result

def track(series):
    chosen=[]
    for i,peaks in enumerate(series):
        if i<2:
            chosen.append(max(peaks,key=lambda q:q[1])); continue
        p0,p1=PRESSURES[i-2:i]; y0,y1=chosen[-2][0],chosen[-1][0]
        guess=y1+(y1-y0)*(PRESSURES[i]-p1)/(p1-p0)
        chosen.append(min(peaks,key=lambda q:abs(q[0]-guess)))
    return chosen

shear_peaks=[]; lb_peaks=[]
for p in PRESSURES:
    path=assets/f"P_{p:.2f}.txt"
    if not path.exists(): path=assets/f"P_{p:g}.txt"
    layers=read_centroids(path)
    # Highest standing-wave eigenvector alternates phase across the ordered layers.
    px=projected_power(layers,0); py=projected_power(layers,1); pz=projected_power(layers,2)
    shear=[(x[0]+y[0],x[1]) for x,y in zip(px,py)]
    shear_peaks.append(candidates(shear,24,80)); lb_peaks.append(candidates(pz,40,150))
tracked_s=track(shear_peaks); tracked_lb=track(lb_peaks)
freq_s=[q[0] for q in tracked_s]; freq_lb=[q[0] for q in tracked_lb]
peak_strength=[(s[1],l[1]) for s,l in zip(tracked_s,tracked_lb)]
alpha_p=[MU*(math.pi*C*w)**2/1e19 for w in freq_s]
alpha_t=[MU*(math.pi*C*w)**2/1e19 for w in freq_lb]
thickness=[6.15e-10*(1-.0104*p) for p in PRESSURES]
c44=[a*1e19*t/1e9 for a,t in zip(alpha_p,thickness)]
c33=[a*1e19*t/1e9 for a,t in zip(alpha_t,thickness)]
result={"pressures_GPa":PRESSURES,"omega_S_bulk_cm1":freq_s,"omega_LB_bulk_cm1":freq_lb,"alpha_parallel_e19":alpha_p,"alpha_perp_e19":alpha_t,"C44_GPa":c44,"C33_GPa":c33}
outdir.mkdir(parents=True,exist_ok=True)
(outdir/"results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
(outdir/"methods.md").write_text("""# Data handling and mode assignment

The twelve `P_*.txt` files were read as six ordered layer-centroid coordinates per frame, sampled at 1 fs. For each pressure, all 50,001 frames were centered and linearly detrended, multiplied by a Hann window, then zero-padded to 65,536 samples for a radix-2 discrete Fourier transform. The highest standing-wave branch was projected with the six-layer cosine eigenvector `cos(5π(j+1/2)/6)`. Shear power combines x and y components; LB power uses z. Local peaks with at least 4% of the strongest in-band peak are tracked across pressure by linear frequency continuation, retaining the same branch when a competing mode becomes stronger. Candidate ranges are 24–80 cm⁻¹ for shear and 40–150 cm⁻¹ for LB. The signed layer projection alternates across adjacent layers, distinguishing the optical breathing mode from a common translation. Frequencies were converted with `alpha=mu*(π*c*omega)^2`, then `C=alpha*t(P)` using the specified mass and thickness relation.
""",encoding="utf-8")
with (outdir/"mode_evidence.md").open("w",encoding="utf-8") as f:
    f.write("Six-layer alternating eigenvector projection (cos(5π(j+1/2)/6)); x/y power gives shear and z power gives phase-alternating LB. Peak amplitudes are arbitrary-unit spectral power from the Hann-windowed 1 fs centroid signals.\n\n")
    f.write("P_GPa,omega_S_cm-1,shear_power,omega_LB_cm-1,LB_power\n")
    for p,s,l,(sp,lp) in zip(PRESSURES,freq_s,freq_lb,peak_strength):
        f.write(f"{p:.2f},{s:.3f},{sp:.6g},{l:.3f},{lp:.6g}\n")
