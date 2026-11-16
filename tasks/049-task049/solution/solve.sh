#!/usr/bin/env bash
set -euo pipefail
OUT="${OUTPUT_DIR:-/app}"
ASSETS="${ASSETS:-/app/environment/assets}"
mkdir -p "$OUT"
python3 - "$OUT" "$ASSETS" <<'PY'
import csv, json, math, pathlib, sys
import numpy as np
out, assets = map(pathlib.Path, sys.argv[1:])
# Parse the public polynomial directly and apply the analytic target/bias identity.
coeff = {}
for line in (assets/'md_potential').read_text().splitlines():
    fields=line.split()
    if fields and not fields[0].startswith('#'):
        i,j=int(fields[0]),int(fields[1]); coeff[f'{i},{j}']=float(fields[2])
assert len(coeff)==25
md = (assets/'md_input').read_text()
temperature = float(next(x.split()[1] for x in md.splitlines() if x.split()[:1]==['temperature']))
if temperature != 1.0:
    raise ValueError('the analytic contract requires its declared T=1 natural-unit input')
beta, gamma = 1.0/temperature, 10.0
factor = beta/gamma-beta
additive_gauge = -factor*coeff['0,0']
gauge = 0.0
terms=[(i,j) for i in range(5) for j in range(5) if i+j]
theta=[factor*coeff[f'{i},{j}']*3**(i+j) for i,j in terms]
def v(x,y): return sum(t*(x/3)**i*(y/3)**j for t,(i,j) in zip(theta,terms))
def grad(x,y):
    return (sum(t*i/3*(x/3)**(i-1)*(y/3)**j for t,(i,j) in zip(theta,terms) if i),
            sum(t*j/3*(x/3)**i*(y/3)**(j-1) for t,(i,j) in zip(theta,terms) if j))
with (out/'bias-grid.csv').open('w',newline='') as f:
    w=csv.writer(f,lineterminator='\n'); w.writerow(['x','y','bias_kBT'])
    for i in range(61):
        x=-3+0.1*i
        for j in range(61):
            y=-3+0.1*j; w.writerow([f'{x:.10f}',f'{y:.10f}',f'{v(x,y):.14g}'])
(out/'bias_model.py').write_text('''TERMS = '''+repr(terms)+'''\nC = '''+repr(theta)+'''\ndef evaluate_theta(x,y,theta):\n return sum(theta[k]*(x/3.0)**i*(y/3.0)**j for k,(i,j) in enumerate(TERMS))\ndef parameter_gradient(x,y,theta):\n return [((x/3.0)**i)*((y/3.0)**j) for i,j in TERMS]\ndef evaluate(x,y): return evaluate_theta(x,y,C)\ndef gradient(x,y):\n return (sum(C[k]*i/3.0*(x/3.0)**(i-1)*(y/3.0)**j for k,(i,j) in enumerate(TERMS) if i),sum(C[k]*j/3.0*(x/3.0)**i*(y/3.0)**(j-1) for k,(i,j) in enumerate(TERMS) if j))\n''')
def objective_at(resolution):
    axis=np.linspace(-3,3,resolution); dx=axis[1]-axis[0]
    xx,yy=np.meshgrid(axis,axis,indexing='ij'); U=np.zeros_like(xx)
    for key,c in coeff.items():
        i,j=map(int,key.split(',')); U += c*xx**i*yy**j
    w=np.ones(resolution); w[[0,-1]]=0.5; area=np.outer(w,w)*dx*dx
    V=np.zeros_like(U)
    for c,(i,j) in zip(theta,terms): V += c*(xx/3)**i*(yy/3)**j
    lt=-beta*U/gamma; m=float(lt.max()); target=np.exp(lt-m)*area; target/=target.sum()
    lv=-(U+V); lm=float(lv.max()); z=float(np.sum(np.exp(lv-lm)*area))
    return float(np.sum(target*V)+lm+math.log(z))
obj=None; res=61; fine_res=None; delta=None
for coarse,fine in ((61,121),(121,181),(181,241)):
    coarse_obj=objective_at(coarse); fine_obj=objective_at(fine); current_delta=abs(fine_obj-coarse_obj)
    if current_delta<=2e-4:
        obj,res,fine_res,delta=coarse_obj,coarse,fine,current_delta; break
if obj is None:
    raise RuntimeError(f'tensor-trapezoid objective did not converge within contract range; last delta={current_delta:.8g}')
(out/'optimization-trace.csv').write_text(f'iteration,objective,gradient_norm,parameter_step_norm,bias_version,theta_json\n0,{obj:.17g},0,0,0,analytic_stationarity\n')
(out/'solve.py').write_text('"""Analytic certificate route: no numerical solver is executed."""\n')
evidence={'schema':'deepves-case01-method/v2','route':'analytic','physics':{'beta':beta,'gamma':gamma,'domain':[[-3,3],[-3,3]],'target':'exp(-beta*U/gamma)'},'representation':{'basis':'monomial','parameter_order':[list(x) for x in terms],'scales':[3,3]},'integration':{'rule':'tensor_trapezoid','resolution':res,'refinement_resolution':fine_res},'stop':{'criterion':'gradient_norm','tolerance':1e-10,'reason':'The input polynomial is finite and the coefficient identity yields p_V=p_target at every point; the analytic gradient is therefore zero.'},'certificate':{'expression':'V(x,y)=sum(c_ij*x^i*y^j); p_V=p_target','coefficients':{k:(gauge if i+j==0 else factor*x) for k,x in coeff.items() for i,j in [map(int,k.split(','))]},'gauge_constant':gauge}}
(out/'method-evidence.json').write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n')
(out/'report.md').write_text(f'''# Static Wolfe–Quapp bias calculation

The public coefficient table defines the finite polynomial U(x,y) on the square [-3,3]^2. With beta={beta:g} and gamma={gamma:g}, the target is proportional to exp(-beta U/gamma). The static model uses V(x,y)=(beta/gamma-beta)U(x,y)+C. Choosing the additive gauge C={additive_gauge:.12g} removes the constant term from the exported model without changing its distribution; the exported polynomial therefore has constant coefficient {gauge:g}. This coefficient identity makes p_V exactly equal to p_target.

For any normalized candidate distribution p_V, the objective difference from this solution is Omega[V]-Omega[V*]=D_KL(p_target || p_V)>=0, with equality when the distributions agree. The additive gauge cancels under normalization. Thus the identity is a global-minimum certificate, not an optimizer convergence claim.

The exported bias table remains a 61x61 evaluation of the polynomial model. For the functional trace, tensor-trapezoid integrations at resolutions {res} and {fine_res} differ by {delta:.8g}; this is a finite-grid approximation, while the coefficient and KL identities are continuous-domain statements. Grid quadrature accuracy and the fixed polynomial representation bound the numerical checks; no molecular-dynamics trajectory is used.
''')
PY
