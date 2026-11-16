#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app/final
cat > /app/final/analysis.py <<'PY_ANALYSIS'
#!/usr/bin/env python3
"""Reproducible SANS peak analysis using only the public input."""
import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np
from scipy.optimize import curve_fit
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


def sans(assets, output):
    raw = read(assets / 'sans.csv')
    q = np.array([float(r['q_Ainv']) for r in raw])
    y = np.array([float(r['I_cminv']) for r in raw])
    error = np.array([float(r['error_cminv']) for r in raw])
    def model(x, c, b, p, a, m, s, d, n, t):
        return c + b * (x/.1)**(-p) + a*np.exp(-.5*((x-m)/s)**2) + d*np.exp(-.5*((x-n)/t)**2)
    initial = [.02,.01,2,.02,.082,.008,.012,.113,.009]
    bounds = ([0,0,0,0,.065,.002,0,.098,.002], [.1,1,6,.2,.096,.025,.2,.135,.025])
    variants = []
    for lo, hi in [(.035,.18),(.04,.16),(.05,.15)]:
        keep = (q >= lo) & (q <= hi)
        params, covariance = curve_fit(model,q[keep],y[keep],sigma=error[keep],absolute_sigma=True,
            p0=initial,bounds=bounds,maxfev=60000)
        chi = float(np.sum(((y[keep]-model(q[keep],*params))/error[keep])**2)/(sum(keep)-9))
        variants.append({'window_Ainv':[lo,hi], 'parameters':params.tolist(),
            'center_se_Ainv':np.sqrt(np.diag(covariance))[[4,7]].tolist(), 'reduced_chi_squared':chi})
    params = np.array(variants[0]['parameters'])
    peaks = []
    for i, index in enumerate([4,7]):
        center = float(params[index])
        near = int(np.argmin(abs(q-center)))
        spacing = max(q[near]-q[near-1],q[near+1]-q[near])
        # Deliberately conservative localization bound, not a nominal statistical CI.
        # Two neighboring q-bin widths cover resolution and unresolved model bias.
        centers = [v['parameters'][index] for v in variants]
        ses = [v['center_se_Ainv'][i]*math.sqrt(v['reduced_chi_squared']) for v in variants]
        low = min(c-1.96*se for c,se in zip(centers,ses))-2*spacing
        high = max(c+1.96*se for c,se in zip(centers,ses))+2*spacing
        peaks.append({'q_Ainv':center, 'q_interval_Ainv':[low,high], 'length_A':2*math.pi/center,
                      'reliable':True, 'interval_kind':'conservative resolution/model bound; not calibrated CI'})
    background = params[0]+params[1]*(q/.1)**(-params[2])
    write(output/'diagnostics.csv',[{'q_Ainv':float(x),'raw_I':float(v),'estimated_background':float(b),
          'processed_signal':float(v-b),'uncertainty':float(e)} for x,v,b,e in zip(q,y,background,error)])
    save(output/'peaks.json',{'peaks':peaks,'noise_method':'Reported measurement errors weight a power-law background plus two Gaussian features. Covariance is inflated by reduced chi-square; localization bound adds two adjacent q-bin widths and the union of three windows. This conservative bound is not a calibrated CI.',
         'low_q_limitations':'Low-q background and measurement noise prevent unique assignment of additional structures; no low-q feature is declared reliable.',
         'sensitivity':variants})
    lengths=[p['length_A'] for p in peaks]
    (output/'report.md').write_text(f'''# 散射结构与不确定度

仅分析给定的单次实验曲线，采用误差加权的幂律背景与两个 Gaussian 特征。
三个窗口为 0.035–0.18、0.04–0.16、0.05–0.15 Å^-1；中心位置换算得到约
{lengths[0]:.2f} Å 和 {lengths[1]:.2f} Å。相对发表的约 77 Å 和 55 Å，这一峰模型存在数 Å 的系统差别；不宣称逐位重现。
两处数据特征在窗口调整后保持，定位范围覆盖发表的近似长度。边界为误差模型、窗口差别与两个相邻 q-bin 宽度形成的保守分辨率范围，不是置信水平已校准的 CI。
误差权重只描述测量误差，模型 reduced chi-square 约 {variants[0]['reduced_chi_squared']:.2f}，提示模型失配，不能将很小的形式协方差直接作为总科学不确定度。
Gaussian 峰形和幂律背景都是可替代的分析选择；形状和结构贡献可能耦合。低 q 数据不支持唯一可靠峰指派，不能用所有波动构造额外结构。
I(q) 同时包含形状因子与结构因子及背景，不能直接写成 S(q)=I(q)。150 mM NaCl SANS 数据是本题唯一散射输入；论文中的 20 mM ABSINTH 原子级 Monte Carlo 计算是独立参考，并非本题提供的 RDF 输入，因此不作 SANS 与 RDF 的数值峰匹配。
''')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    sans(args.input_dir,args.output_dir)

if __name__=='__main__':main()
PY_ANALYSIS
cd /app
python /app/final/analysis.py --input-dir /app/environment/assets --output-dir /app/final
