#!/usr/bin/env python3
"""Independent reference extraction from one trusted native COM trace; no job submission."""
import argparse
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.signal import find_peaks
from scipy.signal.windows import dpss

import score_reference as native

C_CM_S = 2.99792458e10
DT_FS = 1.0
PHYSICAL_BAND = (5.0, 150.0)


def _spectral_resolution(nframes):
    return 1.0e15 / (nframes * DT_FS) / C_CM_S


def _ring(q, frequencies, band, assigned, power):
    excluded = np.zeros(len(frequencies), dtype=bool)
    excluded[max(0, q-3):q+4] = True
    for other in assigned:
        excluded[max(0, other-3):other+4] = True
    local = (np.abs(frequencies-frequencies[q]) <= 10.0) & band & ~excluded
    peaks = [ix for ix in np.flatnonzero(band)
             if ix > 0 and ix < len(power)-1
             and power[ix] >= power[ix-1] and power[ix] >= power[ix+1]]
    for other in peaks:
        if (other != q and power[other] >= .1*power[q]
                and abs(frequencies[other]-frequencies[q]) <= 10.0):
            local[max(0, other-3):other+4] = False
    return local


def _half_peaks(projected, frequency):
    found=[]
    for half in (projected[:len(projected)//2], projected[len(projected)//2:]):
        window=np.hanning(len(half))
        spec=np.fft.rfft(half*window[:,None],axis=0)
        power=np.sum(np.abs(spec)**2,axis=1)
        f=np.fft.rfftfreq(len(half),d=DT_FS*1e-15)/C_CM_S
        inband=np.flatnonzero((f>=PHYSICAL_BAND[0])&(f<=PHYSICAL_BAND[1]))
        peaks=[int(q) for q in inband if q>0 and q<len(power)-1
               and power[q]>=power[q-1] and power[q]>=power[q+1]]
        q=min(peaks,key=lambda x:abs(f[x]-frequency)) if peaks else int(inband[np.argmax(power[inband])])
        found.append(float(f[q]))
    return found


@lru_cache(maxsize=8)
def _half_window_tapers(half_len):
    return dpss(half_len,NW=3.5,Kmax=5,sym=False)


def _half_window_support(projection, full_frequency, assigned_full_frequencies,
                         half_channels, half_frequencies, half_band, full_direction):
    """Independent 25 ps Hann support plus a data-derived spatial-subspace check."""
    results=[]; half_len=len(projection)//2
    df_half=float(half_frequencies[1]-half_frequencies[0])
    tolerance=2.0*df_half+1e-10
    tapers=_half_window_tapers(half_len)
    for hi in range(2):
        piece=projection[hi*half_len:(hi+1)*half_len]
        window=np.hanning(half_len)
        coeff=np.fft.rfft(piece*window[:,None],axis=0)
        power=np.sum(np.abs(coeff)**2,axis=1)
        band_bins=np.flatnonzero(half_band)
        maxima=[int(q) for q in band_bins if q>0 and q<len(power)-1
                and power[q]>=power[q-1] and power[q]>=power[q+1]]
        nearby=[q for q in maxima if abs(float(half_frequencies[q])-full_frequency)<=tolerance]
        pool=nearby if nearby else maxima
        peak=min(pool,key=lambda q:abs(float(half_frequencies[q])-full_frequency)) if pool else int(band_bins[np.argmax(power[band_bins])])
        peak_frequency=float(half_frequencies[peak])
        excluded=np.zeros(len(half_frequencies),dtype=bool)
        excluded[max(0,peak-3):peak+4]=True
        for frequency in assigned_full_frequencies:
            mapped=int(round(float(frequency)/df_half))
            excluded[max(0,mapped-3):mapped+4]=True
        initial_ring=(np.abs(half_frequencies-peak_frequency)<=10.0)&half_band&~excluded
        initial_background_bins=int(np.count_nonzero(initial_ring))
        initial_background=float(np.median(power[initial_ring])) if initial_background_bins>=3 else None
        strong=[q for q in maxima if q!=peak and initial_background is not None
                and power[q]>=.1*power[peak] and power[q]>=5.0*initial_background
                and abs(float(half_frequencies[q])-peak_frequency)<=10.0]
        ring=initial_ring.copy()
        for q in strong: ring[max(0,q-3):q+4]=False
        background_bins=int(np.count_nonzero(ring))
        background=float(np.median(power[ring])) if background_bins>=3 else None
        snr=float(power[peak]/background) if background is not None and background>0 else None
        overlap=None; rank=0; bg_eig=None; peak_eig=None
        if full_direction is not None and background_bins>=3:
            spectra=np.asarray([np.fft.rfft(half_channels[hi]*taper[:,None],axis=0) for taper in tapers])
            vectors=spectra[:,peak,:]
            bg=[np.einsum('ki,kj->ij',spectra[:,q,:],spectra[:,q,:].conj(),optimize=False)/len(tapers)
                for q in np.flatnonzero(ring)]
            background_csd=np.mean(bg,axis=0)
            sample_direction=full_direction[0] if isinstance(full_direction,(list,tuple)) else full_direction
            n_layers,n_axes=sample_direction['layer_shape']
            bg4=background_csd.reshape(n_layers,n_axes,n_layers,n_axes)
            bg_layer=np.einsum('lama->lm',bg4,optimize=False)
            bg_eig=max(0.0,float(np.linalg.eigvalsh(bg_layer).real[-1]))
            half_layer_signal=np.zeros((n_layers,n_layers),dtype=np.complex128)
            half_layer_noise=np.zeros_like(half_layer_signal)
            family_bins=[q for q in maxima if abs(float(half_frequencies[q])-full_frequency)<=tolerance]
            for family_peak in family_bins:
                family_vectors=spectra[:,family_peak,:]
                csd=np.einsum('ki,kj->ij',family_vectors,family_vectors.conj(),optimize=False)/len(tapers)
                csd4=csd.reshape(n_layers,n_axes,n_layers,n_axes)
                half_layer_signal+=np.einsum('lama->lm',csd4,optimize=False)
                bg4=background_csd.reshape(n_layers,n_axes,n_layers,n_axes)
                bg_layer=np.einsum('lama->lm',bg4,optimize=False)
                half_layer_noise+=bg_layer
            bg_layer_max=max(0.0,float(np.linalg.eigvalsh(half_layer_noise).real[-1]))
            half_values,half_vectors=np.linalg.eigh(half_layer_signal)
            peak_eig=max(0.0,float(half_values[-1].real))
            half_basis=half_vectors[:,half_values.real>max(5.0*bg_layer_max,1e-8*peak_eig,1e-300)]
            rank=int(half_basis.shape[1])
            if rank:
                directions=full_direction if isinstance(full_direction,(list,tuple)) else [full_direction]
                full_layer_signal=np.zeros((n_layers,n_layers),dtype=np.complex128)
                full_layer_noise=np.zeros_like(full_layer_signal); used_peaks=set()
                for item in directions:
                    if item['peak'] in used_peaks: continue
                    used_peaks.add(item['peak'])
                    csd4=np.asarray(item['csd']).reshape(n_layers,n_axes,n_layers,n_axes)
                    b4=np.asarray(item['background_csd']).reshape(n_layers,n_axes,n_layers,n_axes)
                    full_layer_signal+=np.einsum('lama->lm',csd4,optimize=False)
                    b_layer=np.einsum('lama->lm',b4,optimize=False)
                    full_layer_noise+=b_layer
                full_noise_max=max(0.0,float(np.linalg.eigvalsh(full_layer_noise).real[-1]))
                full_values,full_vectors=np.linalg.eigh(full_layer_signal)
                full_eig=max(0.0,float(full_values[-1].real))
                full_basis=full_vectors[:,full_values.real>max(10.0*full_noise_max,1e-8*full_eig,1e-300)]
                if full_basis.shape[1] and half_basis.shape[1]>=full_basis.shape[1]:
                    cosines=np.linalg.svd(full_basis.conj().T@half_basis,compute_uv=False)
                    overlap=float(np.min(cosines[:full_basis.shape[1]])) if len(cosines)>=full_basis.shape[1] else 0.0
            else:
                rank=0
        spatial=bool(overlap is not None and overlap>=np.cos(np.deg2rad(30)))
        results.append({'frequency_cm1':peak_frequency,'peak_in_full_window':bool(nearby),
            'local_power_snr':snr,'background_bins':background_bins,'spatial_subspace_overlap':overlap,
            'spatial_subspace_rank':rank,'background_eigenvalue_max':bg_eig,
            'peak_eigenvalue_max':peak_eig,'spatial_supported':spatial,
            'supported':bool(nearby and background_bins>=3 and snr is not None and np.isfinite(snr)
                             and snr>=5.0 and spatial)})
    return results


def _complex_overlap(a,b,branch):
    if branch=='LB':
        x=a[:,0]; y=b[:,0]
        return float(abs(np.vdot(x,y))/(np.linalg.norm(x)*np.linalg.norm(y)+1e-300))
    best=0.0
    for theta in np.linspace(0.0,2*np.pi,361,endpoint=False):
        rotation=np.asarray([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
        best=max(best,float(abs(np.vdot(a,b@rotation))/(np.linalg.norm(a)*np.linalg.norm(b)+1e-300)))
    return best


def extract(xyz):
    """Use Hann peak positions, data-derived multitaper spatial directions, and exact diagnostics."""
    nt,n,_=xyz.shape
    if n not in (2,3,6) or nt!=50000 or not np.isfinite(xyz).all():
        raise ValueError('expected finite 50000-frame COM for N=2,3,6')
    t=np.arange(nt,dtype=float); t-=t.mean()
    centered=xyz-xyz.mean(axis=0,keepdims=True)
    centered-=t[:,None,None]*np.einsum('t,tlc->lc',t,centered)[None,:,:]/np.dot(t,t)
    relative=centered-centered.mean(axis=1,keepdims=True)
    frequencies=np.fft.rfftfreq(nt,d=DT_FS*1e-15)/C_CM_S
    df=float(frequencies[1]-frequencies[0]); band=(frequencies>=5)&(frequencies<=150)
    window=np.hanning(nt); window_sum=float(window.sum())
    basis={j:np.sqrt(2/n)*np.cos(np.pi*j*(np.arange(n)+.5)/n) for j in range(1,n)}
    output=[]; diagnostics=[]
    for branch,axes in (('S',(0,1)),('LB',(2,))):
        channels=relative[:,:,axes].reshape(nt,n*len(axes))
        half_len=nt//2
        half_frequencies=np.fft.rfftfreq(half_len,d=DT_FS*1e-15)/C_CM_S
        half_band=(half_frequencies>=PHYSICAL_BAND[0])&(half_frequencies<=PHYSICAL_BAND[1])
        half_channels=[relative[:half_len,:,axes].reshape(half_len,n*len(axes)),
                       relative[half_len:2*half_len,:,axes].reshape(half_len,n*len(axes))]
        hann_fft=np.fft.rfft(channels*window[:,None],axis=0)*(2.0/window_sum)
        projections={j:np.einsum('l,tlc->tc',vector,relative[:,:,axes]) for j,vector in basis.items()}
        projected_fft={j:np.fft.rfft(value*window[:,None],axis=0)*(2.0/window_sum) for j,value in projections.items()}
        projected_power={j:np.sum(np.abs(value)**2,axis=1) for j,value in projected_fft.items()}
        bins=set()
        for j,power in projected_power.items():
            peaks,_=find_peaks(power)
            peaks=[int(q) for q in peaks if band[q]]
            peaks=sorted(peaks,key=lambda q:power[q],reverse=True)
            cutoff=max(float(power[peaks[0]])*1e-3,1e-300) if peaks else 1e-300
            bins.update(q for q in peaks[:max(12,n*4)] if power[q]>=cutoff)
        bins=sorted(bins)
        taper_spectra=np.asarray([np.fft.rfft(channels*taper[:,None],axis=0) for taper in dpss(nt,NW=3.5,Kmax=5,sym=False)])
        slots=[]
        for q in bins:
            exclusion=np.zeros(len(frequencies),dtype=bool)
            for candidate in bins: exclusion[max(0,candidate-3):candidate+4]=True
            ring=(np.abs(frequencies-frequencies[q])<=10)&band&~exclusion
            peak=taper_spectra[:,q,:]
            csd=np.einsum('ki,kj->ij',peak,peak.conj(),optimize=False)/len(taper_spectra)
            background=[]
            for qb in np.flatnonzero(ring):
                xb=taper_spectra[:,qb,:]
                background.append(np.einsum('ki,kj->ij',xb,xb.conj(),optimize=False)/len(taper_spectra))
            noise_eig=0.0
            if background:
                background_csd=np.mean(background,axis=0)
                noise_eig=max(0.0,float(np.linalg.eigvalsh(background_csd).real[-1]))
            else:
                background_csd=np.zeros_like(csd)
            eigvals,eigvecs=np.linalg.eigh(csd); order=np.argsort(eigvals)[::-1]
            limit=max(10*noise_eig,1e-8*max(0.0,float(eigvals[order[0]].real)),1e-300)
            significant=[int(ix) for ix in order if float(eigvals[ix].real)>limit]
            for ix in significant:
                vector=eigvecs[:,ix]; fitted=np.vdot(vector,hann_fft[q]); amp_power=float(abs(fitted)**2)
                candidate_vec=vector.reshape(n,len(axes)); scores={}
                for j,template in basis.items():
                    projected=np.einsum('l,la->a',template,candidate_vec)
                    overlap2=float(np.sum(np.abs(projected)**2)/(np.linalg.norm(candidate_vec)**2+1e-300))
                    scores[j]=np.log(max(overlap2,1e-12))+.1*np.log(max(amp_power,1e-300))
                slots.append({'peak':q,'direction':ix,'vector':vector,'csd':csd,
                    'background_csd':background_csd,'eigenvalue':float(eigvals[ix].real),
                    'layer_shape':(n,len(axes)),'score_by_j':scores,
                    'rank':len(significant),'eigenvalues':eigvals[order].real.tolist(),'noise_eigenvalue':noise_eig})
        assignments={}
        if slots:
            matrix=np.asarray([[slot['score_by_j'][j] for slot in slots] for j in basis])
            rows,cols=linear_sum_assignment(-matrix)
            assignments={list(basis)[int(row)]:slots[int(col)] for row,col in zip(rows,cols)}
        residual_by_peak={}
        for q in {slot['peak'] for slot in assignments.values()}:
            model=np.zeros(channels.shape[1],dtype=np.complex128)
            for slot in assignments.values():
                if slot['peak']!=q: continue
                vector=slot['vector']
                model += vector*np.vdot(vector,hann_fft[q])
            residual_by_peak[q]=(hann_fft[q]-model).reshape(n,len(axes))
        branch_modes={}
        for j,template in basis.items():
            slot=assignments.get(j)
            if slot is None:
                # Preserve an unresolved frequency diagnosis from the projected data,
                # without manufacturing an independent spatial eigenvector.
                q=max(bins,key=lambda q:projected_power[j][q]) if bins else None
                if q is None:
                    empty=np.full((n,len(axes)),np.nan)
                    branch_modes[j]={'branch':branch,'j':j,'peak_bin':None,'assigned_direction':False,'frequency_cm1':None,
                        'raw':np.zeros((n,len(axes)),complex),'reason':'LOW_LOCAL_SNR','snr':None,
                        'half':[None,None],'bins':0,'df':df,'width':None,'floor':empty,
                        'model_uncertainty':empty,'confidence_floor':empty}
                    continue
                reason='FREQUENCY_SPACE_AMBIGUITY'
                raw=hann_fft[q].reshape(n,len(axes))
                assigned_peaks=[x['peak'] for x in assignments.values()]
                ring=_ring(q,frequencies,band,assigned_peaks,projected_power[j])
                floor=float(np.median(projected_power[j][ring])) if ring.sum()>=3 else None
                snr=float(projected_power[j][q]/floor) if floor is not None and floor>0 else None
                half_support=_half_window_support(projections[j],frequencies[q],
                    [frequencies[x['peak']] for x in assignments.values()],half_channels,
                    half_frequencies,half_band,None)
                half=[x['frequency_cm1'] for x in half_support]
                width=df
                local_noise=np.median(np.abs(hann_fft[ring]),axis=0).reshape(n,len(axes)) if ring.sum()>=3 else np.full((n,len(axes)),np.nan)
                model_uncertainty=np.abs(residual_by_peak.get(q,np.full((n,len(axes)),np.nan+0j))).astype(float)
                confidence_floor=2.0*local_noise+model_uncertainty
                branch_modes[j]={'branch':branch,'j':j,'peak_bin':q,'assigned_direction':False,'frequency_cm1':float(frequencies[q]),
                    'raw':raw,'reason':reason,'snr':snr,'half':half,'bins':int(ring.sum()),'df':df,'width':width,
                    'floor':local_noise,'model_uncertainty':model_uncertainty,'confidence_floor':confidence_floor,
                    'half_support':half_support}
                continue
            q=slot['peak']; vector=slot['vector']; fitted=np.vdot(vector,hann_fft[q]); raw=vector.reshape(n,len(axes))*fitted
            other=[value['peak'] for key,value in assignments.items() if key!=j]
            ring=_ring(q,frequencies,band,other,projected_power[j])
            local_power=projected_power[j]
            background=float(np.median(local_power[ring])) if ring.sum()>=3 else None
            snr=float(local_power[q]/background) if background is not None and background>0 else None
            half_support=_half_window_support(projections[j],frequencies[q],
                [frequencies[x['peak']] for x in assignments.values()],half_channels,
                half_frequencies,half_band,[{'peak':x['peak'],'vector':x['vector'],'csd':x['csd'],
                    'background_csd':x['background_csd'],'eigenvalue':x['eigenvalue'],'layer_shape':x['layer_shape']} for x in slots
                    if abs(float(frequencies[x['peak']])-float(frequencies[q]))<=2.0*(half_frequencies[1]-half_frequencies[0])+1e-10])
            half=[x['frequency_cm1'] for x in half_support]
            half_delta=abs(half[0]-half[1])
            lo=q; hi=q; halfpower=local_power[q]/2
            while lo>0 and local_power[lo-1]>=halfpower: lo-=1
            while hi+1<len(local_power) and local_power[hi+1]>=halfpower: hi+=1
            width=(hi-lo+1)*df
            floor=np.median(np.abs(hann_fft[ring]),axis=0).reshape(n,len(axes)) if ring.sum()>=3 else np.full((n,len(axes)),np.nan)
            model_uncertainty=np.abs(residual_by_peak.get(q,np.full((n,len(axes)),np.nan+0j))).astype(float)
            reason=None
            if snr is None or snr<10: reason='LOW_LOCAL_SNR'
            elif half_delta>2.67 or width>6 or any(not item['supported'] for item in half_support): reason='HALF_WINDOW_UNSTABLE'
            elif not np.isfinite(floor).all(): reason='LOW_PHASE_RELIABILITY'
            confidence_floor=2.0*floor+model_uncertainty
            layer_signal=np.linalg.norm(raw,axis=1); layer_floor=np.linalg.norm(confidence_floor,axis=1) if branch=='S' else confidence_floor[:,0]
            reliable_signal=np.asarray([
                np.linalg.norm([raw[li,ai] for ai,axis in enumerate(('x','y') if branch=='S' else ('z',))
                               if abs(raw[li,ai])>confidence_floor[li,ai]])
                for li in range(n)],dtype=float)
            trusted_signal=layer_signal>layer_floor
            if reason is None and any(reliable_signal[li]<=layer_floor[li]
                                      for li in range(n) if trusted_signal[li]):
                reason='LOW_PHASE_RELIABILITY'
            branch_modes[j]={'branch':branch,'j':j,'peak_bin':q,'assigned_direction':True,'frequency_cm1':float(frequencies[q]),
                'raw':raw,'reason':reason,'snr':snr,'half':half,'bins':int(ring.sum()),'df':df,'width':width,
                'floor':floor,'model_uncertainty':model_uncertainty,'confidence_floor':confidence_floor,
                'half_support':half_support}
        # Near-frequency duplicate spatial directions are ambiguous; independent
        # directions, including a true degenerate pair, remain separately usable.
        group=list(branch_modes.values())
        for i,a in enumerate(group):
            for b in group[i+1:]:
                if a.get('frequency_cm1') is None or b.get('frequency_cm1') is None: continue
                if abs(a['frequency_cm1']-b['frequency_cm1'])>max(df,.5*((a.get('width') or df)+(b.get('width') or df))): continue
                if _complex_overlap(a['raw'],b['raw'],branch)>=np.cos(np.deg2rad(30)):
                    a['reason']=b['reason']='FREQUENCY_SPACE_AMBIGUITY'
        # A nearby spatially independent branch is not a competing peak. If a
        # same-direction peak leaves no feasible frequency interval, report it unresolved.
        for j,m in branch_modes.items():
            f=m.get('frequency_cm1')
            if f is None: continue
            half_delta=abs(m['half'][0]-m['half'][1]) if None not in m['half'] else 0.0
            nearest=6.6666667
            for other_j,other in branch_modes.items():
                if other_j==j or other.get('frequency_cm1') is None: continue
                if abs(other['frequency_cm1']-f)<=df: continue
                if _complex_overlap(m['raw'],other['raw'],branch)>=np.cos(np.deg2rad(30)):
                    nearest=min(nearest,abs(other['frequency_cm1']-f))
            tolerance=min(3.0,.45*nearest,max(2*df,half_delta,.5*(m.get('width') or df)))
            if max(df,half_delta/2)>tolerance: m['reason']='FREQUENCY_SPACE_AMBIGUITY'
        for j,m in branch_modes.items():
            f=m.get('frequency_cm1'); reason=m.get('reason'); raw=m['raw']; floor=m['floor']
            model_uncertainty=m['model_uncertainty']; confidence_floor=m['confidence_floor']
            layers=[]
            if np.isfinite(floor).all():
                for li in range(n):
                    comps={}; node=bool(np.linalg.norm(raw[li])<=np.linalg.norm(confidence_floor[li]))
                    for ai,axis in enumerate(('x','y') if branch=='S' else ('z',)):
                        z=complex(raw[li,ai]); reliable=not node and abs(z)>float(confidence_floor[li,ai])
                        comps[axis]={'complex':[float(z.real),float(z.imag)],'amplitude_A':float(abs(z)),
                            'phase_rad':float(np.angle(z)) if reliable else None,'phase_reliable':bool(reliable),'node_mask':node}
                    layers.append({'layer':li+1,'components':comps})
            else:
                for li in range(n):
                    comps={axis:{'complex':[0.0,0.0],'amplitude_A':0.0,'phase_rad':None,
                        'phase_reliable':False,'node_mask':True} for axis in (('x','y') if branch=='S' else ('z',))}
                    layers.append({'layer':li+1,'components':comps})
            if reason is None and f is not None:
                uncertainty=max(df,abs(m['half'][0]-m['half'][1])/2)
                status='DETECTED'; freq=f; unc=uncertainty; interval=[f-unc,f+unc]
                diagnosis='Resolved by projected Hann peak, local background, and two half-window checks.'
            else:
                status='UNRESOLVED'; freq=unc=interval=None
                diagnosis='Independent mode direction or reliability is unresolved in this finite record.'
            output.append({'branch':branch,'j':j,'label':f'S_{n},{n-j}' if branch=='S' else f'LB_{n},{n-j}',
                'status':status,'frequency_cm1':freq,'frequency_uncertainty_cm1':unc,'frequency_interval_cm1':interval,
                'complex_layer_amplitudes':layers,
                'reliability_metrics':{'local_power_snr':m['snr'],'fft_resolution_cm1':df,
                    'half_window_frequencies_cm1':m['half'],'local_background_bins':m['bins']},
                'diagnosis':diagnosis,'evidence_path':'mode_evidence/spectra.npz',
                **({'unresolved_reason':reason or 'LOW_LOCAL_SNR'} if status=='UNRESOLVED' else {})})
            diagnostics.append({'branch':branch,'j':j,'peak_bin':m['peak_bin'],'assigned_direction':m['assigned_direction'],
                'frequency_cm1':f,'reason_code':reason,
                'half_window_support':m.get('half_support'),
                'local_noise_floor_A_by_component':floor.tolist() if np.isfinite(floor).all() else None,
                'refit_model_uncertainty_A_by_component':model_uncertainty.tolist() if np.isfinite(model_uncertainty).all() else None,
                'phase_node_confidence_bound_A_by_component':confidence_floor.tolist() if np.isfinite(confidence_floor).all() else None})
    layer_fft=np.fft.rfft(relative*window[:,None,None],axis=0)*(2.0/window_sum)
    return output,{'frequencies_cm1':frequencies,'hann_layer_spectrum':layer_fft,
        'hann_channel_spectrum':hann_fft if n else np.array([])},diagnostics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--native-root',type=Path,help='Path for a pinned historical replay')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    envelope=json.loads(args.context.read_text(encoding='utf-8'))
    context=envelope.get('bench15_few_layer_md',envelope)
    root=args.native_root or Path(context['native_root'])
    files={row['role']:root/row['path'] for row in context['files']}
    n=context['expected_selection']['N']; seed=context['expected_selection']['seed']
    com=native.parse_layer_com(files['com'],n)
    modes,spectra,diagnostics=extract(com[:,1:].reshape(50000,n,3))
    final=args.output/'final'; (final/'mode_evidence').mkdir(parents=True,exist_ok=True); (final/'md_inputs').mkdir(exist_ok=True)
    run={'N':n,'seed':seed,'request_id':context['request_id'],'job_id':context['job_id'],
        'sampling':{'native_com_rows':50001,'canonical_com_rows':50000,'native_eqmon_rows':251,'dt_fs':1},
        'evidence':{row['role']:row['path'] for row in context['files'] if row['role'] not in {'host_receipt','terminal_receipt','sacct_receipt','sha_inventory'}},
        'modes':modes}
    payload={'schema':'case05-generic-mode-evidence/v1','task_version':'case05-generic-native-modes-v4','runs':[run]}
    (final/'modes.json').write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    np.savez_compressed(final/'mode_evidence'/'spectra.npz',**spectra)
    (final/'mode_evidence'/'diagnostics.json').write_text(json.dumps(diagnostics,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    public_inputs={'manifest':'manifest.json','input':'input.lmp','data':'data.lmp','deletion_map':'deletion-map.json',
        'potential_rebomos_source':'MoS.rebomos','potential_rebomos_derived':'MoS.rebomos.rebo-only','potential_ilp':'TMD.ILP'}
    for role,name in public_inputs.items():
        if role in files:
            source=files[role]
            if role=='input': name=source.name
            elif role=='data': name=source.name
            elif role=='deletion_map': name=source.name
            (final/'md_inputs'/name).write_bytes(source.read_bytes())
    monitor,_=native.parse_equilibration_monitor(files['eqmon'],n)
    equilibrium=native.summarize_equilibrium(monitor,n,3534*n)
    thermo=native.parse_thermo_by_stage(files['thermo_log'].read_text(encoding='utf-8',errors='replace'),3534*n)
    drift=native.summarize_nve_drift(thermo['production'],3534*n)
    equilibrium_doc={'equilibrium':equilibrium,'nve_drift':drift,
        'status':'DIAGNOSTIC_ONLY','criteria_frozen':False,
        'note':'Values summarize the host-pinned native trace; this report does not alter scheduler or scorer status.'}
    (final/'equilibrium.md').write_text('# Native equilibrium and drift\n\n```json\n'+
        json.dumps(equilibrium_doc,indent=2,allow_nan=False)+'\n```\n',encoding='utf-8')

if __name__=='__main__': main()
