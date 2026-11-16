#!/usr/bin/env bash
set -euo pipefail
work=$(mktemp -d "${TMPDIR:-/tmp}/bench06-oracle.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
ASSETS=${ASSETS_DIR:-/app/environment/assets}
OUT=${OUTPUT_DIR:-/app/final}
[ -d "$ASSETS" ] || { echo "missing public assets: $ASSETS" >&2; exit 2; }
mkdir -p "$OUT"
cat > "$work/analysis.py" <<'BENCH06_PY_36_0'
"""Independent vector-based development candidate; not public benchmark input."""
import csv, json, sys
from pathlib import Path
import numpy as np
from ase.io.trajectory import Trajectory
from ase.geometry import find_mic

def generate(assets, output):
    output.mkdir(parents=True,exist_ok=True)
    allrows=[];summary={}
    for system in ['water_CO2','water_CO2anion','2K_CO2','2K_CO2anion']:
        t=Trajectory(assets/system/'10ps.traj');initial=t[0]
        carbon=np.where(initial.numbers==6)[0].item()
        oxygen=np.where(initial.numbers==8)[0]
        v,_=find_mic(initial.positions[oxygen]-initial.positions[carbon],initial.cell,initial.pbc)
        co2=oxygen[np.argsort(np.linalg.norm(v,axis=1))[:2]]
        selected=list(range(1000,len(t),10));vectors=[]
        for frame in selected:
            a=t[frame]
            v,lengths=find_mic(a.positions[co2]-a.positions[carbon],a.cell,a.pbc)
            # atan2(cross,dot) avoids sharing the reference's ASE get_angle implementation.
            angle=np.degrees(np.arctan2(np.linalg.norm(np.cross(v[0],v[1])),np.dot(v[0],v[1])))
            lengths=np.sort(lengths); row=[float(lengths[0]),float(lengths[1]),float(angle)]
            vectors.append(row);allrows.append([system,frame,*row])
        data=np.array(vectors); means=np.mean(data,axis=0);std=np.std(data,axis=0,ddof=1)
        summary[system]={'n_frames':len(t),'n_samples':len(data),'co_short_mean_A':means[0],'co_long_mean_A':means[1],'oco_mean_deg':means[2],'co_short_std_A':std[0],'co_long_std_A':std[1],'oco_std_deg':std[2],'block_means':[x.mean(axis=0).tolist() for x in np.array_split(data,5)]}
    comparisons={}
    for prefix,label in [('water','water'),('2K','K')]:
        a=summary[prefix+'_CO2'];b=summary[prefix+'_CO2anion']
        comparisons[label+'_reduction_bends']=bool(b['oco_mean_deg']<a['oco_mean_deg'])
        comparisons[label+'_reduction_elongates']=bool(b['co_short_mean_A']>a['co_long_mean_A'])
    comparisons['K_anion_more_bent_than_water']=bool(summary['2K_CO2anion']['oco_mean_deg']<summary['water_CO2anion']['oco_mean_deg'])
    with (output/'geometry.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['system','frame','co_short_A','co_long_A','oco_deg']);writer.writerows(allrows)
    interpretation={'geometry_directly_measures_electronic_charge':False,'geometry_alone_proves_causal_mechanism':False,'sample_std_is_SEM':False,'five_block_means_are_independent_CI':False}
    (output/'summary.json').write_text(json.dumps({'systems':summary,'conclusions':comparisons,'interpretation':interpretation},indent=2))
    report = '从作者轨迹采用最小镜像向量计算结构，首帧识别唯一C及其最近两个O；排除前1000帧后每10帧采样。\n\n'
    for name, row in summary.items():
        report += f"{name}: short C–O={row['co_short_mean_A']:.8g} Å; long C–O={row['co_long_mean_A']:.8g} Å; O–C–O={row['oco_mean_deg']:.8g} deg.\n"
    report += '\n根据上述重算值的比较：\n' + json.dumps(comparisons, ensure_ascii=False, indent=2)
    report += '\n五块均值用于显示相关/慢漂移，逐帧标准差不能当SEM；未由几何证明电子电荷或因果机制。\n'
    (output/'report.md').write_text(report)
    (output/'analysis.py').write_text(Path(__file__).read_text())

if __name__=='__main__':generate(Path(sys.argv[1]),Path(sys.argv[2]))
BENCH06_PY_36_0
python3 "$work/analysis.py" "$ASSETS" "$OUT"
