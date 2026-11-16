#!/usr/bin/env bash
set -euo pipefail
work=$(mktemp -d "${TMPDIR:-/tmp}/bench06-oracle.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
ASSETS=${ASSETS_DIR:-/app/environment/assets}
OUT=${OUTPUT_DIR:-/app/final}
[ -d "$ASSETS" ] || { echo "missing public assets: $ASSETS" >&2; exit 2; }
mkdir -p "$OUT"
cat > "$work/analysis.py" <<'BENCH06_PY_37_0'
"""Independent NumPy FFT/Welch reference submission from public trajectories."""
import csv,json,sys
from pathlib import Path
import numpy as np
from ase.io.trajectory import Trajectory
from ase.geometry import find_mic

SYSTEMS=['water_CO2','water_CO2anion','2K_CO2','2K_CO2anion']
C=2.99792458e-5

def transform(x,spec):
    n=len(x);length=min(spec['nperseg'],n) if spec['kind']=='welch' else n
    overlap=min(spec['noverlap'],length-1) if spec['kind']=='welch' else 0
    nfft=spec.get('nfft') or length
    if spec['window']=='hann':window=.5-.5*np.cos(2*np.pi*np.arange(length)/length)
    elif spec['window']=='blackmanharris':
        phase=2*np.pi*np.arange(length)/length;window=.35875-.48829*np.cos(phase)+.14128*np.cos(2*phase)-.01168*np.cos(3*phase)
    else:window=np.ones(length)
    spectra=[]
    for start in range(0,n-length+1,length-overlap):
        frame=x[start:start+length].copy()
        if spec['detrend']=='constant':frame-=frame.mean(axis=0)
        elif spec['detrend']=='linear':
            axis=np.linspace(-1,1,length);frame-=frame.mean(axis=0);frame-=axis[:,None]*(axis@frame/(axis@axis))[None,:]
        freq=np.fft.rfft(frame*window[:,None],n=nfft,axis=0);p=np.abs(freq)**2/np.sum(window**2)
        if spec['kind']=='vacf_fft':
            # Circular discrete covariance and its FFT are an exactly equivalent estimator.
            raw=np.fft.fft(frame*window[:,None],n=nfft,axis=0)
            vacf=np.fft.ifft(raw*raw.conjugate(),axis=0).real
            p=np.fft.rfft(vacf,axis=0).real/np.sum(window**2)
            p=np.maximum(p,0)
        p[1:-1 if nfft%2==0 else None]*=2;spectra.append(p)
    return np.fft.rfftfreq(nfft,d=1)/C,np.mean(spectra,axis=0)

def mode_peak(q,spec,mode,band):
    wave,p=transform(q,spec);curve=p[:,2:].sum(axis=1) if mode=='bending' else p[:,0 if mode=='symmetric' else 1]
    ids=np.flatnonzero((wave>=band[0])&(wave<=band[1]));return float(wave[ids[np.argmax(curve[ids])]])

def solve(assets,out,kind='welch',window='hann'):
    out.mkdir(parents=True,exist_ok=True)
    spec={'kind':kind,'window':window,'detrend':'constant','nfft':None,'block_count':4,'nperseg':2048,'noverlap':1024}
    metadata={'dt_fs':1,'speed_of_light_cm_per_fs':C,'Nyquist_cm-1':.5/C,'time_source':'1 fs from author MD setup; per-frame times are not stored','estimator':spec,'estimator_aggregation':'full_selected_sequence','absolute_IR_or_Raman_intensity':False,'mass_rescaled':False,'provided_ensembles':['OS_neutral','OS_anion'],'missing_IS_comparison':True,'selection':{},'script_diagnostics':{'loop_components':177,'required_interface_components':531,'example_system':'water_CO2','atom_scope':'whole_interface','VACF_transform':'squared_again','frequency_offset_cm-1':-50,'full_convolution_alignment':'not_corrected'}}
    rows=[];peaks={}
    for name in SYSTEMS:
        t=Trajectory(assets/name/'10ps.traj');a=t[0];c=int(np.flatnonzero(a.numbers==6)[0]);oxygen=np.flatnonzero(a.numbers==8)
        vec,_=find_mic(a.positions[oxygen]-a.positions[c],a.cell,a.pbc);o=oxygen[np.argsort(np.linalg.norm(vec,axis=1))[:2]];indices=[c,*o.tolist()]
        raw=[];projected=[]
        for index in range(1000,len(t)):
            frame=t[index];velocity=frame.get_velocities()[indices]
            vector,length=find_mic(frame.positions[o]-frame.positions[c],frame.cell,frame.pbc);unit=vector/length[:,None]
            relative=velocity[1:]-velocity[0];bond_rates=np.einsum('ij,ij->i',relative,unit)
            transverse=relative-bond_rates[:,None]*unit
            raw.append(velocity.reshape(-1));projected.append(np.r_[(bond_rates[0]+bond_rates[1])/np.sqrt(2),(bond_rates[0]-bond_rates[1])/np.sqrt(2),transverse.reshape(-1)])
        v=np.array(raw);q=np.array(projected);wave,p=transform(v,spec);power=p.sum(axis=1)
        rows.extend([name,float(w),float(x)] for w,x in zip(wave,power))
        metadata['selection'][name]={'atom_indices':indices,'start_frame':1000,'end_frame_exclusive':len(t),'mass_u':a.get_masses()[indices].tolist(),'hydrogen_masses_u':sorted(set(a.get_masses()[a.numbers==1].tolist()))}
        bands={'bending':[400,950],'symmetric':[900,1500],'asymmetric':[1300,1950] if 'anion' in name else [2000,2700]}
        item={}
        for mode,band in bands.items():
            center=mode_peak(q,spec,mode,band);blocks=[mode_peak(block,spec,mode,band) for block in np.array_split(q,spec['block_count'])]
            # A projected mode may exist without a separately observable total-PSD peak.
            local=np.flatnonzero((power[1:-1]>power[:-2])&(power[1:-1]>=power[2:]))+1
            width=max(25,float(np.max(np.diff(wave)))*2)
            resolved=any(abs(wave[i]-center)<=width for i in local)
            mask=(wave>=band[0])&(wave<=band[1]);weak=power[mask].max()<.08*power.max();drift=max(blocks)-min(blocks)>=40
            status='resolved' if resolved else 'unresolved'
            reason='weak_in_total_PSD' if weak else 'block_drift' if drift else 'mode_overlap'
            item[mode]={'wavenumber_cm-1':center,'block_peaks_cm-1':blocks,'stability_range_cm-1':[min(blocks),max(blocks)],'range_kind':'block_minmax','mode_source':{'bending':'bond_transverse','symmetric':'bond_rate_sum','asymmetric':'bond_rate_difference'}[mode],'status':status,'rationale':'基于键方向投影谱和总CO₂三维PSD，并用连续块主峰跨度表征有限轨迹稳定性。'}
            if status=='unresolved':item[mode]['unresolved_reason']=reason
        peaks[name]=item
    claims={
      'absolute_IR_Raman_intensity':{'verdict':'not_established','scope':'velocity_DOS_only','evidence':['metadata:/absolute_IR_or_Raman_intensity'],'rationale':'未计算偶极或极化率相关函数，速度DOS不能给绝对IR/Raman强度。'},
      'charge_state_structural_fingerprint':{'verdict':'conditional','scope':'provided_OS_ensembles_only','evidence':['peaks:/'+name for name in SYSTEMS],'rationale':'在提供的OS轨迹中，中性/阴离子振动指纹有变化；未由光谱直接测量电子电荷。'},
      'unique_IS_or_OS_assignment':{'verdict':'not_established','scope':'no_pathway_uniqueness_from_vibrations','evidence':['metadata:/provided_ensembles','metadata:/missing_IS_comparison'],'rationale':'本数据只有OS双态；同类弯曲/伸缩指纹可能出现在吸附态，没有唯一性证据。'},
      'block_range_is_confidence_interval':{'verdict':'not_established','scope':'finite_block_stability_not_independent_CI','evidence':['metadata:/estimator/block_count'],'rationale':'连续块有时间相关性；最小/最大主峰范围是描述性稳定性，不能冒充独立样本CI。'}}
    with (out/'spectra.csv').open('w') as f:
        w=csv.writer(f);w.writerow(['system','wavenumber_cm-1','power_arb']);w.writerows(rows)
    (out/'metadata.json').write_text(json.dumps(metadata,indent=2));(out/'peaks.json').write_text(json.dumps({'systems':peaks,'claims':claims},ensure_ascii=False,indent=2));(out/'analysis.py').write_text(Path(__file__).read_text().replace("else 'welch'",'else '+repr(kind)).replace("else 'hann'",'else '+repr(window)))
    report='独立用NumPy对CO₂全部9个速度分量计算PSD，采用可复核的窗口/分段估计，不使用作者脚本的whole-interface截断循环、二次平方VACF变换及人为频移；也不沿用full卷积而忽略对齐。键方向投影为峰指派提供物理证据，块范围为描述性稳定性。保留作者质量，不映射为绝对实验谱；光谱不提供IS/OS唯一标签。\n\n'
    report+='<!-- scientific-claims:start -->\n'+json.dumps(claims,ensure_ascii=False,indent=2)+'\n<!-- scientific-claims:end -->\n';(out/'report.md').write_text(report)

if __name__=='__main__':solve(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3] if len(sys.argv)>3 else 'welch',sys.argv[4] if len(sys.argv)>4 else 'hann')
BENCH06_PY_37_0
python3 "$work/analysis.py" "$ASSETS" "$OUT"
