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

def tracts(assets, output):
    raw=read(assets/'tracts_WT.csv');rows=[]
    for r in raw:
        item={'r_A':r['r_A']}
        for tract in ['A0','A1','A2']:
            g=float(r[tract]);item[tract+'_kcalmol']=-.00198720425864083*300*math.log(g) if g>0 else ''
        rows.append(item)
    write(output/'pmf.csv',rows)
    pd=read(assets/'mutants_PD.csv');peaks={}
    for condition in ['WT','A0mut','A1mut','A2mut']:
        peak=max((r for r in pd if 40<=float(r['r_A'])<=70),key=lambda r:float(r[condition]))
        peaks[condition]={'r_A':float(peak['r_A']),'height':float(peak[condition]),'author_error':float(peak[condition+'_author_error'])}
    matrices=[]
    for lo,hi in [(5,50),(4,25),(5,20)]:
        base={t:max(float(r[t]) for r in raw if lo<=float(r['r_A'])<=hi) for t in ['A0','A1','A2']}
        matrix={}
        for mutant in ['A0','A1','A2']:
            matrix[mutant]={}
            for tract in ['A0','A1','A2']:
                values=read(assets/('mutants_'+tract+'.csv'))
                peak=max(float(r[mutant+'mut']) for r in values if lo<=float(r['r_A'])<=hi)
                matrix[mutant][tract]=(peak-base[tract])/base[tract]
        matrices.append({'metric':'relative_peak_change','window_A':[lo,hi],'matrix':matrix})
    result={'window_A':[40,70],'PD_peaks':peaks,'tract_response':matrices[0],
            'supported_rank':'A2>A0>A1 by WT pair-PMF attraction depth. A2 neutralization gives the largest nominal PD peak decrease; a statistically resolved intervention ordering is not established.',
            'indistinguishable_contrasts':['A0mut vs A1mut; no strict significance rank from ambiguous error columns'],
            'uncertainty_definition':'Source Data labels the RDF column only as error. The reviewed degree-histogram helper has a comment/code SEM/population-standard-deviation mismatch, but it does not establish how RDF uncertainty was computed. Preserve the supplied values as author_error; do not infer independent SEM or divide by sqrt(n).',
            'window_sensitivity':matrices[1:]}
    save(output/'interventions.json',result)
    (output/'report.md').write_text('''# 酸性区段与干预响应

在 300 K 下逐 bin 计算 pair PMF=-RT ln g(r)，R=0.00198720425864083 kcal/(mol K)。g=0 的 PMF 不有限，输出留空，不能写零。
WT RDF 最大关联及相应 PMF 深度支持 A2>A0>A1。pair PMF 是两体相关的有效势，不能直接当作结合自由能。
PD 首壳采用 40–70 Å；所有条件第一峰约 52.75 Å。A2 中和后的峰高点估计最低，给出最大名义削弱。
区段干预响应矩阵使用 relative_peak_change；同时检查 5–50、4–25、5–20 Å 的窗口，主要对应自身中和的关联削弱支持模块性，不据此宣称其他区段完全不变。
Source Data 将 RDF 不确定度仅标为 error。已查的度直方图辅助函数存在注释与实现的 SEM/总体标准差差异，但它不能说明 RDF error 如何计算。这里原样保留 author_error，不推断为独立重复 SEM，也不除以 sqrt(n)。
A0/A1 误差重叠，不支持严格强排；A2 名义效应最大也不等于统计上显著超过每一个其他干预，原始误差语义和重复信息不足以支持这种检验。
关联和干预响应须区分。不能将电荷与其他参数同时变化的中和模型解释为只有电荷变化的孤立因果作用。
''')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    tracts(args.input_dir,args.output_dir)

if __name__=='__main__':main()
PY_ANALYSIS
cd /app
python /app/final/analysis.py --input-dir /app/environment/assets --output-dir /app/final
