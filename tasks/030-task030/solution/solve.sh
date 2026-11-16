#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app/final
cat > /app/final/analysis.py <<'PY_ANALYSIS'
#!/usr/bin/env python3
"""Reproducible single-task analysis using public inputs only."""
import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np
from scipy.optimize import curve_fit
from scipy.stats import t as student_t

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

def frap(assets, output):
    raw = read(assets/'frap.csv'); repeats = read(assets/'frap_replicates.csv')
    times = np.array([float(r['time_s']) for r in raw]); fits = {}; curves = {}
    def rational(t,b,p,h): return b+(p-b)*t/(t+h)
    def exponential(t,b,p,tau): return b+(p-b)*(1-np.exp(-t/tau))
    bounds=([-1,0,.0001],[1,2,1e5])
    for species in ['WT','plusA2']:
        y=np.array([float(r[species+'_mean']) for r in raw])
        params,cov=curve_fit(rational,times,y,p0=[0,.4,60],bounds=bounds,maxfev=30000)
        predicted=rational(times,*params);curves[species]=predicted
        rt=np.array([float(r[species+'_time_s']) for r in repeats]);replicate_parameters=[]
        for i in range(1,13):
            ry=np.array([float(r[species+'_'+str(i)]) for r in repeats])
            fit,_=curve_fit(rational,rt,ry,p0=[0,.4,60],bounds=bounds,maxfev=30000)
            replicate_parameters.append(fit.tolist())
        half=np.array([p[2] for p in replicate_parameters]);se=float(half.std(ddof=1)/math.sqrt(12))
        exp_params,_=curve_fit(exponential,times,y,p0=[0,.4,60],bounds=bounds,maxfev=30000)
        window=times <= times.max()*.8
        alt,_=curve_fit(rational,times[window],y[window],p0=params,bounds=bounds,maxfev=30000)
        fits[species]={'family':'rational','equation':'I(t)=baseline+(plateau-baseline)*t/(t+t_half)',
            'baseline':float(params[0]),'plateau':float(params[1]),'timescale_s':float(params[2]),
            'time_parameter':'t_half','window_s':[0,float(times[-1])],'weighting':'unweighted',
            'unweighted_sse':float(np.sum((y-predicted)**2)),
            'uncertainty':{'replicate_parameters_baseline_plateau_t_half':replicate_parameters,
                'replicate_mean_t_half_s':float(half.mean()),'replicate_sample_sd_s':float(half.std(ddof=1)),
                'replicate_mean_se_s':se,'replicate_mean_t_interval_95_s':[float(half.mean()-student_t.ppf(.975,11)*se),float(half.mean()+student_t.ppf(.975,11)*se)],
                'summary_fit_parameter_se':np.sqrt(np.diag(cov)).tolist(),
                'alternative_exponential':{'baseline':float(exp_params[0]),'plateau':float(exp_params[1]),
                    'tau_s':float(exp_params[2]),'half_recovery_s':float(exp_params[2]*math.log(2)),
                    'sse':float(np.sum((y-exponential(times,*exp_params))**2))},
                'alternative_window_s':[0,float(times[window][-1])],'alternative_window_t_half_s':float(alt[2]),
                'method':'12 separately fit experiments; between-replicate sample SD/SE and mean t interval, distinct from covariance SE and model sensitivity.'}}
    save(output/'fits.json',fits)
    write(output/'fitted_curves.csv',[{'time_s':r['time_s'],'WT_observed':r['WT_mean'],'WT_fitted':curves['WT'][i],
        'plusA2_observed':r['plusA2_mean'],'plusA2_fitted':curves['plusA2'][i]} for i,r in enumerate(raw)])
    wt,mut=fits['WT'],fits['plusA2']
    (output/'report.md').write_text(f'''# FRAP 恢复比较

按有理函数 I(t)=b+(p-b)t/(t+h) 自由拟合基线、平台与半恢复时间 h。
WT 为 {wt['timescale_s']:.3f} s，+A2 为 {mut['timescale_s']:.3f} s；增强酸性区段后恢复较慢。
每个条件 12 个重复分别拟合，不能把时间点作为独立实验重复。fits.json 保存每个重复的参数、样本 SD、均值 SE 和 t 区间；这些不是平均曲线拟合协方差的 SE。
发表的 53±2 s 与 103±8 s 采用特定拟合/误差定义，不能强制重复间 SE 等于发表误差。
另拟合指数模型；其 tau 是指数时间常数，半恢复时间为 ln(2)*tau，不能把 tau 直接与有理函数 h 混用。替代模型残差及截去末段的窗口敏感性均保存于 uncertainty。
自由平台与时间尺度存在耦合，观测窗口不足以保证平台完全可辨识。未恢复的荧光比例不能直接解释成唯一不动组分。
FRAP 同时混合分子传输、交联及其他恢复过程，单个恢复模型不足以唯一反演微观扩散率或交联寿命；结论限定为所给实验和所检验模型支持的较慢恢复。
''')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    frap(args.input_dir,args.output_dir)

if __name__=='__main__':main()
PY_ANALYSIS
cd /app
python /app/final/analysis.py --input-dir /app/environment/assets --output-dir /app/final
