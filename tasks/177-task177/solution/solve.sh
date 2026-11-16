#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
mkdir -p "$APP_DIR/final"
APP="$APP_DIR" python3 - <<'PYCODE'
import json,os
from pathlib import Path
import numpy as np
root=Path(os.environ['APP']); a=root/'environment/assets'
c=np.loadtxt(a/'sfac_xray_calc.csv',delimiter=';',comments='#'); e=np.loadtxt(a/'saxs_experiment.dat',comments='#')
def unique_mean(x,y):
 o=np.argsort(x,kind='stable'); x,y=x[o],y[o]; ux,inv=np.unique(x,return_inverse=True); return ux,np.bincount(inv,weights=y)/np.bincount(inv)
# Column 2 is total S(q), as declared by units.txt.
qc,yc=unique_mean(c[:,0]/10,c[:,1]); qe,ye=unique_mean(e[:,0],e[:,1]); q=np.linspace(.5,8,300); delta=np.interp(q,qc,yc)-np.interp(q,qe,ye); shift=float(delta.mean()); r0=float(np.sqrt(np.mean(delta**2))); r1=float(np.sqrt(np.mean((delta-shift)**2))); agree=r1<=.1
# A total trace supplies one independent channel. The target Li-Li partial plus
# at least one other species-weighted contribution already exceed that rank.
total_channels=e.shape[1]-1
minimum_partial_terms=2
unique_proof=minimum_partial_terms<=total_channels
rationale=(f'The fitted shift is {shift:.4f}; shifted RMSE {r1:.4f} {"meets" if agree else "exceeds"} the 0.10 criterion. One total-S channel cannot resolve at least {minimum_partial_terms} independent partial contributions (Li-Li and other species), so this comparison does not uniquely establish short Li-Li chains.')
out={'experimental_vertical_shift':shift,'q_min_Ainv':float(q[0]),'q_max_Ainv':float(q[-1]),'rmse_unshifted':r0,'rmse_shifted':r1,'qualitative_agreement':agree,'total_s_uniquely_proves_short_li_chains':unique_proof,'rationale':rationale}
(root/'final/scattering.json').write_text(json.dumps(out,indent=2)+'\n')

PYCODE
