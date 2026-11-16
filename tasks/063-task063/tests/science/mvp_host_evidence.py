"""Private host-review summaries derived from trusted public G4 sources."""
from __future__ import annotations
import math
import numpy as np


def model_native_affine_summary(module, app_root, refs):
    """Return compact 18-pair comparison stats after independent source replay.

    This describes correlations and affine fits; it never declares an identity
    mapping. Call only after the deterministic candidate replay has succeeded.
    """
    app=module.Path(app_root)
    desc_path,desc_sha=module._asset(app,refs,'g4-descriptors.csv')
    weights_path,weights_sha=module._asset(app,refs,'g4-model-weights.npz')
    trace_path,trace_sha=module._asset(app,refs,'g4-native-traces.npz')
    rows=module._trusted_csv(desc_path)
    trace=module._npz(trace_path,['time_ps','node0','node1','node2','sw','swb','swc'])
    target=np.asarray([float(r['time_ps']) for r in rows],dtype=float)
    ti=np.searchsorted(trace['time_ps'],target)
    ti=np.clip(ti,0,len(trace['time_ps'])-1); left=np.maximum(ti-1,0)
    ti=np.where(np.abs(trace['time_ps'][left]-target)<np.abs(trace['time_ps'][ti]-target),left,ti)
    if len(rows)!=64 or np.max(np.abs(trace['time_ps'][ti]-target))>0.01 or len(np.unique(ti))!=64:
        raise module.TrustedInputError('trusted model/native descriptor join invalid for host summary')
    x=np.asarray([[float(r[f'd{i}_normalized']) for i in range(1,13)] for r in rows],dtype=np.float32)
    pairs=[]
    for mid in module.MODEL_IDS:
        w=module.load_weights(weights_path,mid)
        s,sw,_,_=module.forward_and_gradient(x,w,mid)
        for native in ('node0','node1','node2','sw','swb','swc'):
            model_values=np.asarray(s if native.startswith('node') else sw,dtype=float)
            native_values=np.asarray(trace[native][ti],dtype=float)
            xm=model_values-model_values.mean(); ym=native_values-native_values.mean()
            den=float(np.dot(xm,xm))
            slope=float(np.dot(xm,ym)/den) if den>0 else 0.0
            intercept=float(native_values.mean()-slope*model_values.mean())
            residual=native_values-(slope*model_values+intercept)
            yden=float(np.dot(ym,ym)); r=float(np.dot(xm,ym)/math.sqrt(den*yden)) if den>0 and yden>0 else None
            pairs.append({'model_id':mid,'native_column':native,'model_scalar':'s_raw' if native.startswith('node') else 'sw',
                          'n':len(rows),'pearson_r':r,'affine_slope':slope,'affine_intercept':intercept,
                          'rmse':float(np.sqrt(np.mean(residual*residual))),'max_abs_residual':float(np.max(np.abs(residual)))})
    return {'interpretation':'Numerical comparison only; correlation or affine fit does not establish model/native identity or independent validation.',
            'comparison_count':len(pairs),'descriptor_rows':len(rows),'pairs':pairs,
            'source_hashes':{'g4-descriptors.csv':desc_sha,'g4-model-weights.npz':weights_sha,'g4-native-traces.npz':trace_sha}}
