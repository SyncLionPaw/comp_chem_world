"""Independent scalar-per-mode reference calculation for Case 008."""
from __future__ import annotations
import math
import numpy as np
EPS0=8.8541878128e-12
KB=1.380649e-23
E=1.602176634e-19
T=300.0
BLOCK_PS=1000.0
BOOT_SEED=20261008
BOOT_REPS=2000
LOW=(0.15,1.20)
PEAK=(2.0,4.5)

def canonical_vectors():
    return np.asarray([(n,0,0) for n in range(1,63)] + [(0,n,0) for n in range(1,63)] + [(0,0,n) for n in range(1,63)],dtype=np.int16)

def structure_factors(positions, charges, box_a, vectors):
    """Independent direct cosine/sine sum, no recurrence or analyzer import."""
    vectors=np.asarray(vectors,dtype=np.int64)
    nframes=len(positions); result=np.empty((nframes,len(vectors)),dtype=np.float64)
    kval=2.0*np.pi/float(box_a)*vectors
    for f in range(nframes):
        xyz=np.remainder(np.asarray(positions[f],dtype=np.float64),box_a)
        for m in range(len(vectors)):
            angle=xyz @ kval[m]
            rho_re=np.sum(charges*np.cos(angle),dtype=np.float64)
            rho_im=-np.sum(charges*np.sin(angle),dtype=np.float64)
            result[f,m]=rho_re*rho_re+rho_im*rho_im
    return result

def molecular_dipoles_si(positions, charges, box_a):
    """SI dipole vectors from independently centered molecular coordinates."""
    xyz=np.asarray(positions,dtype=np.float64).reshape(len(positions),9033,3,3)
    delta=xyz[:,:,1:,:]-xyz[:,:,:1,:]
    delta-=float(box_a)*np.rint(delta/float(box_a))
    qh=np.asarray(charges,dtype=np.float64).reshape(9033,3)[:,1:]
    # Explicitly convert e*Angstrom to C*m before summation.
    mu=np.sum(delta*qh[None,:,:,None],axis=(1,2))*E*1e-10
    return mu

def groups(times_ps):
    t=np.asarray(times_ps,dtype=np.float64)
    dt=np.median(np.diff(np.sort(t)))
    ids=np.floor((t-t.min()+1e-8)/BLOCK_PS).astype(int)
    labels=np.unique(ids)
    if len(labels)<8 or len(labels)%2 or not np.array_equal(labels,np.arange(labels[0],labels[-1]+1)):
        raise ValueError("reference requires an even number of at least eight populated contiguous one-ns groups")
    counts=np.asarray([np.count_nonzero(ids==i) for i in labels])
    if np.any(counts!=counts[0]): raise ValueError("reference requires equal sample counts per one-ns group")
    return ids,labels,float(dt)

def quadratic_extremum(k,y,i,kind):
    dx=float(k[i+1]-k[i]); yl,yc,yr=map(float,y[i-1:i+2])
    denom=yl-2*yc+yr
    if abs(denom)<1e-30 or (kind=="min" and denom<=0) or (kind=="max" and denom>=0):
        return float(k[i]),yc
    off=0.5*(yl-yr)/denom
    if abs(off)>1: return float(k[i]),yc
    kval=float(k[i]+off*dx)
    value=float(yc-0.25*(yl-yr)*off)
    return kval,value

def features(k,chi,se):
    mask=(k>=LOW[0])&(k<=LOW[1]); widx=np.flatnonzero(mask)
    cand=[i for i in range(1,len(k)-1) if mask[i] and chi[i]<chi[i-1] and chi[i]<=chi[i+1]]
    lowv=chimin=None; lowstatus="unresolved"; lowreason="no interior local minimum in fixed 0.15–1.20 A^-1 window"
    if cand:
        i=min(cand,key=lambda j:chi[j]); left=max(0,int(widx[0])-1); right=min(len(k)-1,int(widx[-1])+1)
        if i>left and i<right:
            prominence=min(float(np.max(chi[left:i])),float(np.max(chi[i+1:right+1])))-float(chi[i])
            noise=math.sqrt(float(se[i])**2+max(float(np.max(se[left:i+1])),float(np.max(se[i:right+1])))**2)
            if prominence>2*noise:
                lowv,chimin=quadratic_extremum(k,chi,i,"min");lowstatus="resolved";lowreason=None
            else: lowreason="low-k trough prominence is not greater than two block standard errors"
    pmask=(k>=PEAK[0])&(k<=PEAK[1]); inds=np.flatnonzero(pmask)
    i=int(inds[np.argmax(chi[inds])]); kmax=width=km=kp=None; peakstatus=widthstatus="unresolved"
    peakreason="overscreening peak is at the fixed-window boundary";widthreason="peak does not have an interior maximum"
    if i>inds[0] and i<inds[-1]:
        kmax,cmax=quadratic_extremum(k,chi,i,"max");peakstatus="resolved";peakreason=None
        half=cmax/2
        lcross=[j for j in range(i) if (chi[j]-half)*(chi[j+1]-half)<=0]
        rcross=[j for j in range(i,len(k)-1) if (chi[j]-half)*(chi[j+1]-half)<=0]
        if lcross and rcross and cmax>0:
            def cross(j):
                dy=float(chi[j+1]-chi[j]);return float((k[j]+k[j+1])/2) if abs(dy)<1e-15 else float(k[j]+(half-chi[j])*(k[j+1]-k[j])/dy)
            km=cross(lcross[-1]);kp=cross(rcross[0]);width=kp-km;widthstatus="resolved";widthreason=None
        else: widthreason="chi(k_max)/2 crossing is not bracketed on both sides"
    return {"k_min_Ainv":lowv,"chi_min":chimin,"k_min_status":lowstatus,"chi_min_status":lowstatus,
      "k_min_reason":lowreason,"chi_min_reason":lowreason,"k_max_Ainv":kmax,"k_max_status":peakstatus,
      "k_max_reason":peakreason,"delta_k_Ainv":width,"delta_k_status":widthstatus,"delta_k_reason":widthreason,
      "k_minus_Ainv":km,"k_plus_Ainv":kp}

def summarize(positions,box6,charges,times,vectors=None,do_boot=True):
    if vectors is None:vectors=canonical_vectors()
    vectors=np.asarray(vectors,dtype=np.int16)
    p=structure_factors(positions,charges,float(np.mean(box6[0,:3])),vectors)
    shell=np.rint(np.sqrt(np.sum(vectors.astype(np.int64)**2,axis=1))).astype(int)
    maxn=int(shell.max()); raw=np.stack([p[:,shell==n].mean(axis=1) for n in range(1,maxn+1)],axis=1)
    ids,labels,dt=groups(times)
    bp=np.stack([raw[ids==b].mean(axis=0) for b in labels]); meanp=raw.mean(axis=0)
    L=float(np.mean(box6[0,:3])); volume_a3=L**3; V=volume_a3*1e-30
    k=2*np.pi*np.arange(1,maxn+1)/L; km=k*1e10
    factor=E*E/(EPS0*KB*T*V*km**2); chi=meanp*factor; bc=bp*factor
    se1=np.std(bc,axis=0,ddof=1)/math.sqrt(len(labels))
    complete=len(labels)-(len(labels)%2); use=ids<complete
    ids2=np.floor((np.asarray(times)[use]-np.min(times)+1e-8)/(2*BLOCK_PS)).astype(int)
    labels2=np.unique(ids2); raw2=raw[use]
    bc2=np.stack([raw2[ids2==b].mean(axis=0)*factor for b in labels2]);chi2=bc2.mean(axis=0)
    se2=np.std(bc2,axis=0,ddof=1)/math.sqrt(len(labels2))
    dip=molecular_dipoles_si(positions,charges,L)
    mu=dip.mean(axis=0); factor_eps=1/(3*EPS0*V*KB*T)
    vals=1+factor_eps*np.sum((dip-mu)**2,axis=1)
    full_eps=float(vals.mean())
    # Delete-one contiguous-block jackknife, recentering dipoles globally per replicate.
    jk=[]
    for b in labels:
        keep=ids!=b; m=dip[keep].mean(axis=0); jk.append(1+factor_eps*np.mean(np.sum((dip[keep]-m)**2,axis=1)))
    jk=np.asarray(jk);epsse=float(math.sqrt((len(jk)-1)/len(jk)*np.sum((jk-jk.mean())**2)))
    vals2=vals[use];dip2=dip[use];eps2=float(vals2.mean());jk2=[]
    for b in labels2:
        keep=ids2!=b;m=dip2[keep].mean(axis=0);jk2.append(1+factor_eps*np.mean(np.sum((dip2[keep]-m)**2,axis=1)))
    jk2=np.asarray(jk2);epsse2=float(math.sqrt((len(jk2)-1)/len(jk2)*np.sum((jk2-jk2.mean())**2)))
    feat=features(k,chi,se1);feat2=features(k,chi2,se2)
    out={"chi":chi,"se1":se1,"se2":se2,"counts":np.bincount(shell,minlength=maxn+1)[1:],
       "k":k,"features":feat,"features2":feat2,"eps":full_eps,"eps_se":epsse,"eps2":eps2,"eps_se2":epsse2,
       "block_chi":bc,"block_ids":ids,"dipoles_SI":dip,"raw_mode_power":p,"mode_shells":shell}
    if do_boot:
        rng=np.random.default_rng(BOOT_SEED);names=("k_min_Ainv","chi_min","k_max_Ainv","delta_k_Ainv")
        boot={x:[] for x in names}; reps=BOOT_REPS
        for _ in range(reps):
            picked=bc[rng.integers(0,len(bc),size=len(bc))]
            curve=picked.mean(axis=0); bse=np.std(picked,axis=0,ddof=1)/math.sqrt(len(picked))
            ff=features(k,curve,bse)
            for name in names:
                v=ff[name]
                if v is not None and math.isfinite(v):boot[name].append(float(v))
        floor_k=(k[1]-k[0])/math.sqrt(12)
        floor_w=(k[1]-k[0])/math.sqrt(6)
        out["bootstrap"]={}
        floors={"k_min_Ainv":floor_k,"chi_min":0.,"k_max_Ainv":floor_k,"delta_k_Ainv":floor_w}
        for name in names:
            a=np.asarray(boot[name]); sd=float(a.std(ddof=1)) if len(a)>1 else None
            out["bootstrap"][name]={"n":len(a),"sd":sd,"se":max(sd,floors[name]) if sd is not None and len(a)>=max(100,int(.8*reps)) else None}
    return out
