#!/usr/bin/env bash
set -euo pipefail
mkdir -p /app/final
cat > /app/final/analysis.py <<'PY_ANALYSIS'
#!/usr/bin/env python3
"""Reproducible single-task network analysis from public topology and trajectory."""
import argparse
import json
from pathlib import Path
import numpy as np

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def network(assets, output):
    import MDAnalysis as mda
    from MDAnalysis.lib.distances import capped_distance
    from scipy.signal import find_peaks
    selection=json.loads((assets/'selections.json').read_text());cuts={}
    for tract in ['A0','A1','A2']:
        rdf=np.loadtxt(assets/('RDFs_rpL5_charged_'+tract+'Pep.txt'));x,g=rdf[0],rdf[1]
        # First prominent positive association peak, then first local minimum.
        maxima,_=find_peaks(g,prominence=.1);peak=next(i for i in maxima if g[i]>1)
        minima,_=find_peaks(-g);minimum=next(i for i in minima if i>peak)
        cuts[tract]=float(x[minimum])
    universe=mda.Universe(str(assets/'rpL5_init.data'),str(assets/'rpL5_example_traj.dcd'),format='DCD')
    mids=np.unique(universe.atoms.resids);n=len(mids);graphs={};degrees={}
    basic=universe.select_atoms('type '+' '.join(map(str,selection['rpL5_basic_types'])));bi=np.searchsorted(mids,basic.resids)
    stats={}
    for tract,types in selection['N130_acidic_types'].items():
        acid=universe.select_atoms('type '+' '.join(map(str,types)));ai=np.searchsorted(mids,acid.resids)
        base_cutoff=cuts[tract]
        thresholds=[base_cutoff-.5,base_cutoff,base_cutoff+.5]
        arrays=[np.zeros((len(universe.trajectory),n,n),dtype=np.uint8) for _ in thresholds]
        for f,ts in enumerate(universe.trajectory):
            pairs,d=capped_distance(acid.positions,basic.positions,max_cutoff=thresholds[-1],box=ts.dimensions,return_distances=True)
            for array,cutoff in zip(arrays,thresholds):
                selected=pairs[d<cutoff]
                if len(selected):
                    left=ai[selected[:,0]];right=bi[selected[:,1]];array[f,left,right]=1;array[f,right,left]=1
                np.fill_diagonal(array[f],0)
        degrees_by_threshold=[array.sum(axis=2,dtype=np.int64) for array in arrays]
        base_index=1
        graphs[tract]=arrays[base_index];degrees[tract]=degrees_by_threshold[base_index]
        pd_ids=np.unique(universe.select_atoms('type 1').resids);pdmask=np.isin(mids,pd_ids)
        def metrics(degree):
            return {'PD_mean_degree_by_frame':degree[:,pdmask].mean(axis=1).tolist(),
                    'rpL5_mean_degree_by_frame':degree[:,~pdmask].mean(axis=1).tolist(),
                    'all_mean_degree_by_frame':degree.mean(axis=1).tolist(),
                    'all_zero_degree_count_by_frame':(degree==0).sum(axis=1).tolist(),
                    'undirected_edge_count_by_frame':(degree.sum(axis=1,dtype=np.int64)//2).tolist()}
        base_metrics=metrics(degrees_by_threshold[base_index])
        stats[tract]={'PD_mean_degree_by_frame':base_metrics['PD_mean_degree_by_frame'],
                      'rpL5_mean_degree_by_frame':base_metrics['rpL5_mean_degree_by_frame'],
                      'all_mean_degree_by_frame':base_metrics['all_mean_degree_by_frame'],
                      'all_zero_degree_count_by_frame':base_metrics['all_zero_degree_count_by_frame'],
                      'species_degree_histograms':{name:[np.bincount(frame,minlength=n).tolist() for frame in degrees_by_threshold[base_index][:,mask]]
                          for name,mask in [('PD',pdmask),('rpL5',~pdmask),('all',np.ones(n,dtype=bool))]}}
        sensitivity=[]
        metric_names=list(base_metrics)
        base_means={name:float(np.mean(base_metrics[name])) for name in metric_names}
        for delta,cutoff,degree in zip([-.5,0.,.5],thresholds,degrees_by_threshold):
            values=metrics(degree)
            ranges={name:[float(np.min(values[name])),float(np.max(values[name]))] for name in metric_names}
            mean_values={name:float(np.mean(values[name])) for name in metric_names}
            relative={name:(None if base_means[name]==0 else 100*(mean_values[name]-base_means[name])/base_means[name]) for name in metric_names}
            sensitivity.append({'cutoff_A':float(cutoff),'delta_from_rdf_minimum_A':float(delta),
                                'per_frame':values,'range_across_11_frames':ranges,
                                'relative_change_in_frame_mean_percent_vs_base':relative})
        stats[tract]['cutoff_sensitivity']={'step_A':.5,'interpretation':'Adjacent RDF-bin perturbation, not statistical uncertainty or an alternate accepted cutoff.','thresholds':sensitivity}
    sensitivity_report=[]
    for tract,item in stats.items():
        entries=item['cutoff_sensitivity']['thresholds'];low,mid,high=entries
        details=[]
        for name,label in [('PD_mean_degree_by_frame','PD'),('rpL5_mean_degree_by_frame','rpL5'),('all_mean_degree_by_frame','all'),('all_zero_degree_count_by_frame','isolated nodes'),('undirected_edge_count_by_frame','edges')]:
            lo=min(x['range_across_11_frames'][name][0] for x in entries)
            hi=max(x['range_across_11_frames'][name][1] for x in entries)
            delta_low=low['relative_change_in_frame_mean_percent_vs_base'][name]
            delta_high=high['relative_change_in_frame_mean_percent_vs_base'][name]
            details.append(f"{label} {lo:.3f}–{hi:.3f}; mean change at −0.5/+0.5 Å {delta_low if delta_low is not None else 'n/a':.2f}%/{delta_high if delta_high is not None else 'n/a':.2f}%" if delta_low is not None and delta_high is not None else f"{label} {lo:.3f}–{hi:.3f}; relative change unavailable when baseline mean is zero")
        sensitivity_report.append(f"- {tract} ({low['cutoff_A']:.2f}/{mid['cutoff_A']:.2f}/{high['cutoff_A']:.2f} Å): "+'; '.join(details)+'.')
    np.savez_compressed(output/'graphs.npz',**graphs);np.savez_compressed(output/'degrees.npz',**degrees)
    save(output/'cutoffs.json',cuts);save(output/'degree_statistics.json',stats)
    (output/'report.md').write_text('''# 分子接触网络

输入为真实拓扑与 11 帧 DCD。按排序 molecule/residue ID 保留全部 1728 个节点；PD 珠子 type 1 标识 N130，其他分子为 rpL5。
A0/A1/A2 与碱性 rpL5 类型由 selections.json 指定。各 RDF 首关联峰后的第一极小值给出 13.75、12.75、12.25 Å 截断；作者固定网络阈值 13、13、12.5 Å 是不同的约定，不能冒称本输入的实际首极小值。
逐帧采用周期盒 minimum-image 距离和严格 d<cutoff。任意珠子对接触形成一条无权分子边，多个珠子接触只计一次；无自环、对称。
degrees 是邻接矩阵行和；分物种和整体度分布包含 degree=0 节点。degree_statistics.json 保存各帧分物种与整体直方图及隔离节点数。

## RDF-bin cutoff sensitivity

For each data-derived minimum, the graph and degree summaries were recomputed at the minimum and at ±0.5 Å (one supplied RDF bin). These are sensitivity checks, not confidence intervals. The shallow A1 minimum is not uniquely localized: its adjacent bin at 13.25 Å has a similarly low RDF value. Values below are the ranges across the three thresholds and 11 paired frames; relative changes compare frame means against the baseline minimum.
'''+ '\n'.join(sensitivity_report)+'''

This 11-frame sample is not a set of independent replicates and does not establish ensemble-wide bimodality or percolation.
''')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    network(args.input_dir,args.output_dir)

if __name__=='__main__':main()
PY_ANALYSIS
cd /app
python /app/final/analysis.py --input-dir /app/environment/assets --output-dir /app/final
