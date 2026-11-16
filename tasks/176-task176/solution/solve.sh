#!/bin/sh
set -eu
APP_DIR=${APP:-/app}
mkdir -p "$APP_DIR/final"
APP="$APP_DIR" python3 - <<'PYCODE'
import json, os
from pathlib import Path
import numpy as np
root=Path(os.environ['APP']); a=root/'environment/assets'
def tab(f): return np.loadtxt(a/f,comments='#')
# Public Figure 4 mapping and Figure 2 region-I shortest interval.
regions={'blue':'I','green':'II','red':'III'}; short=next(c for c,r in regions.items() if r=='I')
h={c:tab('window_'+c+'.dat') for c in (*regions,'all')}; ave=int(h['all'][np.argmax(h['all'][:,1]),0]); x=h[short]; total=int(x[np.argmax(x[:,1]),0]); anion=int(x[np.argmax(x[:,2]),0])
ang=tab('angle_li_ow_li.dat'); bulk=tab('angle_bulk_water_exp.dat'); modes=[]
for lo,hi in ((0,90),(90,180)):
 z=ang[(ang[:,0]>lo)&(ang[:,0]<hi)]; modes.append(float(z[np.argmax(z[:,1]),0]))
bm=float(bulk[np.argmax(bulk[:,1]),0]); out={'short_contact_window':short,'short_contact_mode_total_cn':total,'average_mode_total_cn':ave,'short_contact_cn_higher_than_average':total>ave,'short_contact_modal_anion_cn':anion,'angle_modes_deg':modes,'acute_mode_tighter_than_bulk_water':modes[0]<bm}
(root/'final/solvation.json').write_text(json.dumps(out,indent=2)+'\n')

PYCODE
