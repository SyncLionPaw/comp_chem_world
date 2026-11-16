#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: α-quartz surface energy and thickness effects.
"""Portable L1/L2/L3 verifier for α-quartz slab surface energies."""
from __future__ import annotations
import csv,hashlib,json,math,os,sys
from pathlib import Path

ORIENTATIONS=("001","011","100_alpha","100_beta","101")
HEADERS={
 "orientation_audit.csv":["orientation","slab_file","N_atoms","N_Si","N_O","area_A2","atomic_span_A","cell_vectors_A","stoichiometry","geometry_note"],
 "slab_fit.csv":["orientation","reconstruction","window_files","window_N_min","window_N_max","slope_eV_per_atom","intercept_eV","residual_RMSE_eV","n_points","fit_assumptions"],
 "surface_energy.csv":["orientation","reconstruction","area_A2","gamma_eV_per_A2","gamma_J_per_m2","uncertainty_eV_per_A2","uncertainty_J_per_m2","bulk_reference","converged","decision","reason"]}

class ScienceFailure(Exception):pass
class EnvironmentFailure(Exception):pass

def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest()
def read_csv(p,header):
 try:
  with p.open(encoding="utf-8",newline="") as f:
   r=csv.DictReader(f)
   if r.fieldnames!=header:raise ScienceFailure(f"{p.name}: incorrect CSV header")
   rows=list(r)
 except ScienceFailure:raise
 except Exception as e:raise ScienceFailure(f"{p.name}: unreadable CSV ({e})") from e
 if not rows:raise ScienceFailure(f"{p.name}: no data rows")
 return rows
def num(row,key,ctx):
 try:x=float(row[key])
 except Exception as e:raise ScienceFailure(f"{ctx}: {key} must be numeric") from e
 if not math.isfinite(x):raise ScienceFailure(f"{ctx}: {key} must be finite")
 return x
def close(a,b,tol,ctx):
 if not math.isfinite(a) or not math.isfinite(b) or abs(a-b)>tol:raise ScienceFailure(f"{ctx}: {a:g} differs from {b:g} by >{tol:g}")
def integer(row,key,ctx):
 x=num(row,key,ctx)
 if x!=round(x):raise ScienceFailure(f"{ctx}: {key} must be an integer")
 return int(x)

def parse_xyz(path):
 try:
  lines=path.read_text(encoding="utf-8").splitlines();n=int(lines[0].strip());comment=lines[1]
  lm=__import__("re").search(r'Lattice="([^"]+)"',comment);em=__import__("re").search(r"(?:^|\s)energy=([-+0-9.eE]+)",comment)
  if not lm or not em:raise ValueError("cell/energy metadata absent")
  cell=[[float(x) for x in lm.group(1).split()[j:j+3]] for j in (0,3,6)]
  symbols=[];pos=[]
  for line in lines[2:2+n]:
   row=line.split();symbols.append(row[0]);pos.append([float(x) for x in row[1:4]])
  if len(symbols)!=n:raise ValueError("atom count differs from file header")
  import math as m
  a,b,c=cell
  normal=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
  area=m.sqrt(sum(x*x for x in normal));normal=[x/area for x in normal]
  z=[sum(p[k]*normal[k] for k in range(3)) for p in pos]
  return {"N":n,"Si":symbols.count("Si"),"O":symbols.count("O"),"cell":cell,"area":area,"span":max(z)-min(z),"energy":float(em.group(1))}
 except Exception as e:raise EnvironmentFailure(f"slab input malformed ({path.name}: {e})") from e

def ref_load(refs):
 try:
  bundle=refs["private_reference"]; r=bundle["metadata"]; d=bundle["surface"]
 except Exception as e:raise EnvironmentFailure(f"private reference missing/damaged in refs.json ({e})") from e
 if r.get("reference_type")!="independent E(N) fit cross-checked to private published relaxed row" or set(r.get("orientations",{}))!=set(ORIENTATIONS):raise EnvironmentFailure("private reference provenance/schema invalid")
 for o in ORIENTATIONS:
  x=r["orientations"][o]
  try:
   for k in ("published_relaxed_eV_per_A2","gamma_reference_eV_per_A2","comparison_tolerance_eV_per_A2","gamma_last4_eV_per_A2","area_A2"): 
    if not math.isfinite(float(x[k])):raise ValueError(k)
   if len(x["expected_counts"])!=len(x["expected_file_names"]):raise ValueError("slab manifest length")
  except Exception as e:raise EnvironmentFailure(f"private reference damaged for {o}: {e}") from e
 return r,d

def public_input_root(root):
 app_inputs=root/"inputs"
 if (app_inputs/"cleaved_dft_surface_energies.csv").is_file(): return app_inputs
 assets=root/"environment/assets"
 if (assets/"cleaved_dft_surface_energies.csv").is_file(): return assets
 raise EnvironmentFailure("public inputs are missing from /inputs or environment/assets")

def check_inputs(root,ref):
 input_root=public_input_root(root)
 hashes=ref.get("input_sha256")
 if not isinstance(hashes,dict) or len(hashes)<37:raise EnvironmentFailure("private input hash manifest incomplete")
 for rel,digest in hashes.items():
  p=input_root/rel.removeprefix("inputs/")
  if not p.is_file():raise EnvironmentFailure(f"required input missing: {rel}")
  if sha(p)!=digest:raise EnvironmentFailure(f"required input hash mismatch: {rel}")
 return input_root

def fit(data):
 n=[x["N"] for x in data];e=[x["energy"] for x in data];nm=sum(n)/len(n);em=sum(e)/len(e)
 den=sum((x-nm)**2 for x in n)
 if den<=0:raise ScienceFailure("fit has duplicate atom counts")
 m=sum((x-nm)*(y-em) for x,y in zip(n,e))/den;b=em-m*nm
 rmse=math.sqrt(sum((y-(m*x+b))**2 for x,y in zip(n,e))/len(n))
 return m,b,rmse

def png(path):
    try:
        from PIL import Image
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError("not a PNG")
            image.verify()
        with Image.open(path) as image:
            image.load()
    except ImportError as exc:
        raise EnvironmentFailure(f"Pillow required for PNG verification: {exc}") from exc
    except Exception as exc:
        raise ScienceFailure(f"missing/invalid scientific figure: {exc}") from exc


def scoring_refs(tests):
 try:
  d=json.loads((tests/"refs.json").read_text(encoding="utf-8"))
  required=("eV_A2_to_J_m2","geometry_area_tolerance_A2","geometry_span_tolerance_A","cell_vector_tolerance_A","fit_slope_tolerance_eV_per_atom","fit_intercept_tolerance_eV","fit_rmse_tolerance_eV","fit_rmse_max_eV","fit_window_area_comparison_tolerance_eV_per_A2","relaxed_surface_energy_uncertainty_max_eV_per_A2","minimum_relaxation_drop_eV_per_A2","published_cleaved_rounding_uncertainty_eV_per_A2")
  if not isinstance(d,dict) or set(d)!=(set(required)|{"relaxed_published_tolerance_from_private_reference","private_reference"}):raise ValueError("missing or unexpected scoring reference key")
  numeric=[k for k in required if k!="published_cleaved_rounding_uncertainty_eV_per_A2"]
  if any(isinstance(d[k],bool) or not isinstance(d[k],(int,float)) or not math.isfinite(float(d[k])) or float(d[k])<0 for k in numeric):raise ValueError("scoring references must be finite nonnegative numbers")
  bounds=d["published_cleaved_rounding_uncertainty_eV_per_A2"]
  if not isinstance(bounds,list) or len(bounds)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)) for v in bounds) or bounds[0]<0 or bounds[0]>bounds[1]:raise ValueError("published rounding uncertainty range is malformed")
  if d["relaxed_published_tolerance_from_private_reference"] is not True:raise ValueError("private-reference comparison binding must be enabled")
  return d
 except Exception as e:raise EnvironmentFailure(f"tests/refs.json missing or malformed ({e})") from e

def verify(root,refdir,refs):
 input_refs=scoring_refs(Path(__file__).resolve().parent); ref,full=ref_load(input_refs);input_root=check_inputs(root,ref);out=root/"outputs"
 summary_path=out/"summary.json"
 if not summary_path.is_file():raise ScienceFailure("missing outputs/summary.json")
 try:s=json.loads(summary_path.read_text(encoding="utf-8"))
 except Exception as e:raise ScienceFailure(f"invalid summary.json ({e})") from e
 required=("method","orientation_audit","bulk_reference","surface_energy","reconstruction_effect","ranking","uncertainty","limitations","figure_panels")
 if not isinstance(s,dict) or any(k not in s for k in required):raise ScienceFailure("summary missing required scientific fields")
 if set(s["figure_panels"])!={"orientation_specific_E_N_fits","cleaved_vs_relaxed_surface_energy"}:raise ScienceFailure("figure panel manifest must include E(N) fits and cleaved/relaxed comparison")
 if not isinstance(s["limitations"],list) or not any(
  ("cleaved" in str(x).lower() and "geometr" in str(x).lower()) or
  (any(term in str(x) for term in ("解理","劈裂")) and any(term in str(x) for term in ("几何","结构")))
  for x in s["limitations"]):raise ScienceFailure("summary must disclose absent cleaved geometries")
 if float(s["method"].get("conversion_eV_per_A2_to_J_per_m2",0))!=refs["eV_A2_to_J_m2"]:raise ScienceFailure("surface-energy conversion factor is missing/wrong")
 cleaved_inputs={r["orientation"]:r for r in csv.DictReader((input_root/"cleaved_dft_surface_energies.csv").open(encoding="utf-8"))}
 if set(cleaved_inputs)!=set(ORIENTATIONS):raise EnvironmentFailure("public cleaved-only input is malformed")
 byfile={};audit=read_csv(out/"orientation_audit.csv",HEADERS["orientation_audit.csv"])
 if len(audit)!=35:raise ScienceFailure("orientation_audit must contain all 35 slabs")
 for row in audit:
  o=row["orientation"];fn=row["slab_file"]
  if o not in ORIENTATIONS:raise ScienceFailure(f"unknown orientation {o}")
  path=input_root/f"surfaces/alpha_quartz/{o}/{fn}"
  if not path.is_file():raise ScienceFailure(f"audit names unknown slab {o}/{fn}")
  if (o,fn) in byfile:raise ScienceFailure(f"duplicate slab audit row {o}/{fn}")
  data=parse_xyz(path);ctx=f"{o}/{fn}"
  for k,v in (("N_atoms",data["N"]),("N_Si",data["Si"]),("N_O",data["O"])):
   if integer(row,k,ctx)!=v:raise ScienceFailure(f"{ctx}: {k} differs from input")
  if data["Si"]*2!=data["O"] or data["Si"]+data["O"]!=data["N"]:raise ScienceFailure(f"{ctx}: slab must be stoichiometric SiO2")
  close(num(row,"area_A2",ctx),data["area"],refs["geometry_area_tolerance_A2"],ctx+" surface area")
  close(num(row,"atomic_span_A",ctx),data["span"],refs["geometry_span_tolerance_A"],ctx+" atomic thickness")
  try:cell=json.loads(row["cell_vectors_A"])
  except Exception as e:raise ScienceFailure(f"{ctx}: cell_vectors_A must be a JSON array") from e
  for i in range(3):
   for j in range(3):close(float(cell[i][j]),data["cell"][i][j],refs["cell_vector_tolerance_A"],ctx+" cell vector")
  if row["stoichiometry"]!="Si:O=1:2" or not row["geometry_note"].strip():raise ScienceFailure(f"{ctx}: geometry/stochiometry interpretation missing")
  byfile[(o,fn)]=data
 if set(o for o,_ in byfile)!=set(ORIENTATIONS):raise ScienceFailure("all five orientations must be audited")
 expected_counts={"001":4,"011":9,"100_alpha":7,"100_beta":6,"101":9}
 for o,c in expected_counts.items():
  if sum(x==o for x,_ in byfile)!=c:raise ScienceFailure(f"{o}: incorrect slab count")
  files=ref["orientations"][o]["expected_file_names"]
  if set(fn for oo,fn in byfile if oo==o)!=set(files):raise ScienceFailure(f"{o}: audit must cover its exact input file set")
  areas=[byfile[(o,fn)]["area"] for fn in files]
  if max(areas)-min(areas)>refs["geometry_area_tolerance_A2"]:raise ScienceFailure(f"{o}: in-plane area changes across slab sequence")

 fits=read_csv(out/"slab_fit.csv",HEADERS["slab_fit.csv"]);fit_by={}
 if len(fits)<10:raise ScienceFailure("slab_fit must report thick-window diagnostics for all orientations")
 for row in fits:
  o=row["orientation"];ctx=f"{o} fit"
  if o not in ORIENTATIONS or row["reconstruction"]!="relaxed_from_slab":raise ScienceFailure("slab fits must map to one relaxed orientation")
  try:names=json.loads(row["window_files"])
  except Exception as e:raise ScienceFailure(f"{ctx}: window_files must be a JSON array") from e
  if len(names)<3:raise ScienceFailure(f"{ctx}: use at least three thick slabs")
  expected=ref["orientations"][o]["expected_file_names"][-len(names):]
  if names!=expected:raise ScienceFailure(f"{ctx}: fit window must be the contiguous thick-slab tail")
  data=[byfile[(o,fn)] for fn in names];m,b,r=fit(data)
  if integer(row,"n_points",ctx)!=len(data):raise ScienceFailure(f"{ctx}: wrong number of fit points")
  if integer(row,"window_N_min",ctx)!=min(x["N"] for x in data) or integer(row,"window_N_max",ctx)!=max(x["N"] for x in data):raise ScienceFailure(f"{ctx}: window bounds mismatch")
  close(num(row,"slope_eV_per_atom",ctx),m,refs["fit_slope_tolerance_eV_per_atom"],ctx+" slope")
  close(num(row,"intercept_eV",ctx),b,refs["fit_intercept_tolerance_eV"],ctx+" intercept")
  close(num(row,"residual_RMSE_eV",ctx),r,refs["fit_rmse_tolerance_eV"],ctx+" residual RMSE")
  if r>refs["fit_rmse_max_eV"]:raise ScienceFailure(f"{ctx}: thick-slab fit residual is too large to support a linear surface excess")
  if (o,len(names)) in fit_by:raise ScienceFailure(f"{ctx}: duplicate fit window size")
  fit_by[(o,len(names))]=(m,b,r)
  if not row["fit_assumptions"].strip():raise ScienceFailure(f"{ctx}: fit assumptions missing")
 if any((o,k) not in fit_by for o in ORIENTATIONS for k in (3,4)):raise ScienceFailure("need last-3 and last-4 slab fits for measured thickness sensitivity")

 surface=read_csv(out/"surface_energy.csv",HEADERS["surface_energy.csv"]);surface_by={};relaxed_fit_size={}
 if len(surface)!=10:raise ScienceFailure("surface_energy must contain cleaved and relaxed values for all orientations")
 for row in surface:
  o,stage=row["orientation"],row["reconstruction"]
  if o not in ORIENTATIONS or stage not in ("cleaved_published_input","relaxed_from_slab") or (o,stage) in surface_by:raise ScienceFailure("invalid/duplicate surface-energy row")
  ctx=f"{o} {stage}";area=num(row,"area_A2",ctx);gamma=num(row,"gamma_eV_per_A2",ctx);j=num(row,"gamma_J_per_m2",ctx)
  close(area,ref["orientations"][o]["area_A2"],refs["geometry_area_tolerance_A2"],ctx+" area")
  close(j,gamma*refs["eV_A2_to_J_m2"],1e-8,ctx+" eV/A2 to J/m2 conversion")
  uncertainty=num(row,"uncertainty_eV_per_A2",ctx)
  close(num(row,"uncertainty_J_per_m2",ctx),uncertainty*refs["eV_A2_to_J_m2"],1e-8,ctx+" uncertainty unit conversion")
  if stage=="cleaved_published_input":
   source=float(cleaved_inputs[o]["gamma_cleaved_eV_per_A2"])
   close(gamma,source,1e-12,ctx+" public cleaved value")
   if not refs["published_cleaved_rounding_uncertainty_eV_per_A2"][0] <= uncertainty <= refs["published_cleaved_rounding_uncertainty_eV_per_A2"][1]:raise ScienceFailure(f"{ctx}: include three-decimal source rounding uncertainty")
   if row["converged"]!="not_applicable":raise ScienceFailure(f"{ctx}: cleaved reference is not an E(N) fit")
  else:
   if row["converged"].lower()!="true":raise ScienceFailure(f"{ctx}: relaxed fit must be reported converged")
   match=next((k for (oo,k),v in fit_by.items() if oo==o and abs(gamma-v[1]/(2*area))<refs["fit_window_area_comparison_tolerance_eV_per_A2"]),None)
   if match is None:raise ScienceFailure(f"{ctx}: gamma must be derived from one reported E(N) fit and the two-face area")
   relaxed_fit_size[o]=match
   valid_g=[]
   for k in range(3,expected_counts[o]+1):
    source_data=[byfile[(o,fn)] for fn in ref["orientations"][o]["expected_file_names"][-k:]]
    _,ib,rmse=fit(source_data)
    if rmse<=refs["fit_rmse_max_eV"]:valid_g.append(ib/(2*area))
   observed_drift=max(valid_g)-min(valid_g)
   if uncertainty+1e-9<observed_drift:raise ScienceFailure(f"{ctx}: uncertainty omits valid thick-window sensitivity measured from raw slabs")
   if row["converged"].lower()!="true" or observed_drift>refs["relaxed_surface_energy_uncertainty_max_eV_per_A2"]:raise ScienceFailure(f"{ctx}: convergence flag conflicts with measured valid-window spread")
   if uncertainty>refs["relaxed_surface_energy_uncertainty_max_eV_per_A2"]:raise ScienceFailure(f"{ctx}: uncertainty exceeds calibrated fit/source comparison scale")
   tol=ref["orientations"][o]["comparison_tolerance_eV_per_A2"]
   close(gamma,ref["orientations"][o]["published_relaxed_eV_per_A2"],tol,ctx+" hidden published relaxed-row cross-check")
  if not row["decision"].strip() or not row["reason"].strip():raise ScienceFailure(f"{ctx}: ranking decision/reason missing")
  surface_by[(o,stage)]={"gamma":gamma,"uncertainty":uncertainty,"decision":row["decision"]}
 if any((o,st) not in surface_by for o in ORIENTATIONS for st in ("cleaved_published_input","relaxed_from_slab")):raise ScienceFailure("missing cleaved/relaxed orientation energies")

 for o in ORIENTATIONS:
  audit_sum=s["orientation_audit"].get(o,{})
  if audit_sum.get("n_slabs")!=expected_counts[o] or audit_sum.get("N_atoms")!=ref["orientations"][o]["expected_counts"] or audit_sum.get("stoichiometry")!="Si:O=1:2":raise ScienceFailure(f"{o}: summary slab audit conflicts with its per-file table")
  close(float(audit_sum.get("area_A2",float("nan"))),ref["orientations"][o]["area_A2"],refs["geometry_area_tolerance_A2"],o+" summary area")
  bulk=s["bulk_reference"].get(o,{})
  mu=float(bulk.get("mu_eV_per_atom",float("nan")))
  fit_size=relaxed_fit_size[o]
  if abs(mu-fit_by[(o,fit_size)][0])>=refs["fit_slope_tolerance_eV_per_atom"]:raise ScienceFailure(f"{o}: bulk chemical potential must use the same E(N) window as relaxed gamma")
  c=surface_by[(o,"cleaved_published_input")]["gamma"];g=surface_by[(o,"relaxed_from_slab")]["gamma"]
  if c<=g or c-g<refs["minimum_relaxation_drop_eV_per_A2"]:raise ScienceFailure(f"{o}: relaxation energy change is absent or physically inconsistent")
  if not ("near_degenerate" in surface_by[(o,"cleaved_published_input")]["decision"] if o in ("100_alpha","011") else surface_by[(o,"cleaved_published_input")]["decision"].startswith("rank_")):
   raise ScienceFailure(f"{o}: cleaved-stage ranking/near-degeneracy label missing")
  if not ("near_degenerate" in surface_by[(o,"relaxed_from_slab")]["decision"] if o in ("100_alpha","011") else surface_by[(o,"relaxed_from_slab")]["decision"].startswith("rank_")):
   raise ScienceFailure(f"{o}: relaxed-stage ranking/near-degeneracy label missing")
  rs=s.get("surface_energy",{}).get(o,{})
  close(float(rs.get("gamma_relaxed_eV_per_A2",float("nan"))),g,1e-9,o+" summary relaxed gamma")
  close(float(rs.get("gamma_cleaved_eV_per_A2",float("nan"))),c,1e-12,o+" summary cleaved gamma")
  close(float(rs.get("relaxation_energy_drop_eV_per_A2",float("nan"))),c-g,1e-9,o+" summary relaxation difference")
  effect=s.get("reconstruction_effect",{}).get(o,{})
  close(float(effect.get("drop_eV_per_A2",float("nan"))),c-g,1e-9,o+" reconstruction effect")
  close(float(effect.get("drop_J_per_m2",float("nan"))),(c-g)*refs["eV_A2_to_J_m2"],1e-8,o+" reconstruction effect units")
  if effect.get("significant") is not True:raise ScienceFailure(f"{o}: reconstruction energy lowering must be assessed")
  close(float(s["uncertainty"].get("relaxed_surface_energy_eV_per_A2",{}).get(o,float("nan"))),surface_by[(o,"relaxed_from_slab")]["uncertainty"],1e-9,o+" summary uncertainty")
  expected_decision="near_degenerate" if o in ("100_alpha","011") else ("rank_3" if o=="101" else ("rank_4" if o=="001" else "rank_5"))
  if surface_by[(o,"cleaved_published_input")]["decision"]!=expected_decision or surface_by[(o,"relaxed_from_slab")]["decision"]!=expected_decision:
   raise ScienceFailure(f"{o}: rank label/near-degeneracy classification conflicts with the calibrated orientation sequence")
 ranking=s["ranking"]
 cleaved_order=ranking.get("cleaved_low_to_high");relaxed_order=ranking.get("relaxed_low_to_high")
 if cleaved_order not in (["011","100_alpha","101","001","100_beta"],["100_alpha","011","101","001","100_beta"]):raise ScienceFailure("cleaved orientation ranking conflicts with measured values")
 if relaxed_order not in (["100_alpha","011","101","001","100_beta"],["011","100_alpha","101","001","100_beta"]):raise ScienceFailure("relaxed orientation ranking conflicts with fitted energies")
 for key in ("cleaved_near_degenerate","relaxed_near_degenerate"):
  if set(ranking.get(key,[]))!={"100_alpha","011"}:raise ScienceFailure(f"summary must identify the Alpha-100/011 near-degeneracy in {key}")
 if ranking.get("rank_change_robust") is not False or set(ranking.get("rank_change_near_degenerate",[]))!={"100_alpha","011"}:
  raise ScienceFailure("summary must structurally mark the Alpha-100/011 rank-order change as non-robust")
 png(out/"figures/thickness_fit.png")
 return {"status":"PASS","reward":1,"levels":{"L1":"PASS","L2":"PASS","L3":"PASS"},"coverage":{"orientation_count":5,"slab_count":35,"fit_windows_per_orientation":[3,4],"surface_energy_rows":10,"ranking_tie":["100_alpha","011"]}}

def main():
 try:
  root=Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()
  tests=Path(__file__).resolve().parent
  print(json.dumps(verify(root,None,scoring_refs(tests)),sort_keys=True));return 0
 except ScienceFailure as e:
  print(json.dumps({"status":"FAIL","reward":0,"error_type":"science_failure","message":str(e)},sort_keys=True));return 1
 except EnvironmentFailure as e:
  print(json.dumps({"status":"ERROR","reward":None,"error_type":"environment_or_reference_error","message":str(e)},sort_keys=True));return 2
 except Exception as e:
  print(json.dumps({"status":"ERROR","reward":None,"error_type":"verifier_error","message":str(e)},sort_keys=True));return 2
if __name__=="__main__":raise SystemExit(main())
