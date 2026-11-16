#!/usr/bin/env python3
"""Zero-MD analytic checks; these are not trajectory/science acceptance evidence."""
import ast, hashlib, json
from pathlib import Path
import numpy as np

root=Path(__file__).resolve().parents[1]
source=root/'analysis/independent_validation.py'
tree=ast.parse(source.read_text())
funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='deposit']
ns={'np':np}
exec(compile(ast.Module(body=funcs,type_ignores=[]),str(source),'exec'),ns)
E=1.602176634e-19; EPS0=8.8541878128e-12; KB=1.380649e-23; T=300.
q=np.array([-.8476,.4238,.4238]); oh=1.; hh=1.633
c=np.sqrt(oh*oh-(hh/2)**2)
xyz=np.array([[0.,0.,0.],[c,hh/2,0.],[c,-hh/2,0.]])
mu=(xyz*q[:,None]).sum(axis=0)
debye=np.linalg.norm(mu)*E*1e-10/3.33564e-30
analytic=2*.4238*c*E*1e-10/3.33564e-30
box=np.array([10.,10.,10.]); moved=xyz+np.array([9.8,5.,5.]); wrapped=moved%box
relative=wrapped[1:]-wrapped[:1]; relative-=box*np.rint(relative/box)
mu_pbc=(relative*q[1:,None]).sum(axis=0)
mu_gauge=((xyz+np.array([7.5,-3.25,8.])*box)*q[:,None]).sum(axis=0)
# Integer-grid particles give an exact charge-assignment/Fourier identity.
n=16; pos=np.array([[2.,3.,4.],[5.,6.,7.],[8.,1.,9.]])
grid=ns['deposit'](n,pos,q,np.full(3,float(n)))
mode=np.array([1,-2,3]); rho=(q*np.exp(2j*np.pi*(pos@mode)/n)).sum()
ff=np.fft.fftn(grid)[tuple(mode%n)]
L=65.; k_A=2*np.pi*np.linalg.norm(mode)/L; V=L**3*1e-30
strict=abs(rho)**2/(k_A*1e10)**2*E**2/(V*EPS0*KB*T)
rho_C=rho*E; k_m=2*np.pi*np.linalg.norm(mode)/(L*1e-10)
si=abs(rho_C)**2/(V*EPS0*KB*T*k_m*k_m)
checks={
 'charge_neutrality':bool(abs(q.sum())<1e-14),
 'SPCE_analytic_dipole_agreement':bool(abs(debye-analytic)<1e-12 and 2.34<debye<2.36),
 'whole_molecule_gauge_invariance':bool(np.allclose(mu,mu_gauge,atol=1e-13,rtol=0)),
 'OW_relative_minimum_image_dipole_agreement':bool(np.allclose(mu,mu_pbc,atol=1e-13,rtol=0)),
 'actual_CIC_deposit_charge_conservation':bool(abs(grid.sum())<1e-14),
 'integer_grid_FFT_direct_power_identity':bool(np.isclose(abs(ff)**2,abs(rho)**2,rtol=1e-13,atol=1e-14)),
 'modewise_response_SI_normalization_identity':bool(np.isclose(strict,si,rtol=1e-13)),
}
result={'kind':'zero-MD analytic sanity only','scientific_acceptance':'NOT_EVALUATED','checks':checks,'SPCE_dipole_D':float(debye),'analysis_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'sanity_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'status':'PASS' if all(checks.values()) else 'FAIL'}
out=root/'preflight-evidence/analytic_sanity.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if not all(checks.values()):raise SystemExit(2)
