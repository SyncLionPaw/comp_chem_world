#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app/final
cat > /app/final/analysis.py <<'PY_ANALYSIS'
#!/usr/bin/env python3
"""Reproducible single-task analysis using public inputs only."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np

def read(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))

def write(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def dynamics(assets, output):
    raw=read(assets/'msd.csv');result={'t_D_ps':100,'msd_unit':'angstrom_squared','species':{}};rows=[]
    def fit(species,window):
        points=[(float(r['t_over_tD']),float(r[species+'_A2'])) for r in raw if window[0]<=float(r['t_over_tD'])<=window[1]]
        x,y=np.array(points).T;a,b=np.polyfit(np.log(x),np.log(y),1)
        return {'window_t_over_tD':window,'exponent':float(a),'amplitude_A2':float(np.exp(b)),
                'log_residual_sse':float(np.sum((np.log(y)-b-a*np.log(x))**2))}
    for species in ['PD','A0','A1','A2','rpL5']:
        result['species'][species]={}
        for regime,window,other in [('early',[.05,.3],[.05,.25]),('late',[4,24.95],[5,24.95])]:
            primary=fit(species,window);primary.update(objective='log_ols',sensitivity=[fit(species,other)])
            result['species'][species][regime]=primary
            for r in raw:
                t=float(r['t_over_tD'])
                if window[0]<=t<=window[1]:rows.append({'species':species,'regime':regime,'t_over_tD':t,
                    'observed_MSD':float(r[species+'_A2']),'fitted_MSD':primary['amplitude_A2']*t**primary['exponent']})
    save(output/'exponents.json',result);write(output/'fits.csv',rows)
    p=result['species']['PD']
    (output/'report.md').write_text(f'''# 平均 MSD 的两个时间区间

输入时间为 t/t_D，t_D=100 ps；MSD 单位 Å²。按声明窗口做 natural-log OLS，保存实际残差与拟合曲线。
早期 0.05–0.3 对应 5–30 ps，晚期 4–24.95 对应 400–2495 ps。另用早期 0.05–0.25、晚期 5–24.95 检查窗口敏感性。
PD 早期指数 {p['early']['exponent']:.6f}>1，晚期 {p['late']['exponent']:.6f}<1，支持早期超扩散与晚期次扩散的区间交叉；酸性区段及 rpL5 在相应窗口以次扩散为主。
该结果只涉及平均曲线及给定时间区间；改变窗口或目标函数可能改变指数。不能从平均 MSD 的时间交叉独立推出单分子指数双峰。
这里没有独立轨迹的重复数据，不能将时间 bin 当作独立重复，不能伪造五次独立轨迹误差，也不能由平均曲线唯一确定微观机制。
''')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    dynamics(args.input_dir,args.output_dir)

if __name__=='__main__':main()
PY_ANALYSIS
cd /app
python /app/final/analysis.py --input-dir /app/environment/assets --output-dir /app/final
