#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Hydrogen coverage stability and conditional surface softening.
"""Independent case-02 checker: reconstruct the three-state hull from public slabs."""
import argparse, csv, hashlib, json, math
from pathlib import Path

EV_A2 = 16.02176634
CONVENTIONS = {"sigma0":"sigma0_eV", "without_entropy":"without_entropy_eV", "toten":"TOTEN_eV"}
CORRECTIONS = {"native":0.0, "random50_minus_0.06_J_m2":-0.06}


def check_calculation_evidence(final, app, expected_input_name):
    import ast
    src=final/"calculation_source.py"; meta_path=final/"run_metadata.json"
    if not src.is_file() or not meta_path.is_file(): raise AssertionError("executable calculation source and run metadata are required")
    try:
        ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
        metadata=json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc: raise AssertionError("calculation evidence is not parseable") from exc
    if not isinstance(metadata,dict): raise AssertionError("run metadata must be a JSON object")
    if metadata.get("schema")!="compchemworld-calculation-run/v1": raise AssertionError("unsupported calculation run metadata")
    if metadata.get("calculation_source_sha256")!=sha(src): raise AssertionError("calculation source hash mismatch")
    item=metadata.get("input")
    if not isinstance(item,dict): raise AssertionError("run metadata input must be a JSON object")
    match=[p for p in (app/"assets").glob(expected_input_name) if p.is_file()]
    if len(match)!=1 or item.get("logical_name")!=expected_input_name or item.get("sha256")!=sha(match[0]): raise AssertionError("run metadata input hash does not identify the public source")
    outputs=metadata.get("output_sha256")
    if not isinstance(outputs,dict): raise AssertionError("run metadata output_sha256 must be a JSON object")
    actual={p.name:sha(p) for p in final.iterdir() if p.is_file() and p.name not in {"calculation_source.py","run_metadata.json"}}
    if not isinstance(outputs,dict) or outputs!=actual: raise AssertionError("run metadata output hashes mismatch")
    python_meta=metadata.get("python")
    python_valid=(isinstance(python_meta,str) and bool(python_meta.strip())) or (isinstance(python_meta,dict) and isinstance(python_meta.get("version"),str) and bool(python_meta["version"].strip()))
    context=metadata.get("execution_context")
    context_valid=(isinstance(context,str) and bool(context.strip())) or (isinstance(context,dict) and bool(context))
    if not python_valid or not context_valid: raise AssertionError("run environment metadata missing")

def rows(path):
    with path.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def close(a,b,tol=2e-8): return math.isfinite(float(a)) and abs(float(a)-float(b)) <= tol
def interval_equal(got,want,tol=1e-12):
    return len(got)==len(want) and all((x==y if isinstance(x,str) or isinstance(y,str) else close(x,y,tol)) for x,y in zip(got,want))

def normalize_hull_groups(groups):
    """Accept either a list of group objects or a composite-key map of the same groups."""
    if isinstance(groups, list):
        if any(not isinstance(r, dict) for r in groups):
            raise AssertionError("coverage_hull.json must contain a groups array of objects")
        return groups
    if isinstance(groups, dict):
        out = []
        for key, rec in groups.items():
            if not isinstance(rec, dict):
                raise AssertionError("coverage_hull.json composite-key groups must map to objects")
            item = dict(rec)
            needed = ("alloy", "energy_convention", "surface_correction")
            if not all(k in item for k in needed):
                parts = None
                if isinstance(key, str):
                    for sep in ("|", "/", "::", "||"):
                        trial = key.split(sep)
                        if len(trial) == 3:
                            parts = trial
                            break
                if parts is None:
                    raise AssertionError("composite hull group key must identify alloy, energy_convention, and surface_correction")
                item.setdefault("alloy", parts[0])
                item.setdefault("energy_convention", parts[1])
                item.setdefault("surface_correction", parts[2])
            out.append(item)
        return out
    raise AssertionError("coverage_hull.json must contain a groups array of objects or a composite-key map")
def preflight(app,tests):
    try: refs=json.loads((tests/"refs.json").read_text(encoding="utf8"))
    except Exception as exc: raise RuntimeError(f"integrity failure: refs.json: {type(exc).__name__}") from exc
    if not isinstance(refs,dict) or refs.get("case_id")!="case-02": raise RuntimeError("integrity failure: refs.json case/schema")
    groups=(("asset_hashes",app,"assets"),("grader_reference_hashes",tests,"references"))
    for key,base,subdir in groups:
        entries=refs.get(key)
        if not isinstance(entries,dict) or (key=='asset_hashes' and not entries): raise RuntimeError("integrity failure: missing "+key)
        expected={str(p.relative_to(base)) for p in (base/subdir).rglob("*") if p.is_file()}
        actual={name.removeprefix("tests/") for name in entries} if key=="grader_reference_hashes" else set(entries)
        if actual!=expected: raise RuntimeError("integrity failure: incomplete or extra "+key)
        for rel,digest in entries.items():
            p=base/rel.removeprefix("tests/") if key=="grader_reference_hashes" else base/rel
            try: valid=p.is_file() and "sha256:"+sha(p)==digest
            except Exception: valid=False
            if not valid: raise RuntimeError("integrity failure: "+rel)
    return refs
def canonical_mu_grid_key(value):
    mu = float(value)
    if not math.isfinite(mu):
        raise AssertionError("surface-excess chemical-potential grid must be finite")
    index = round((mu + 0.2) / 0.001)
    if not 0 <= index <= 400:
        raise AssertionError("surface-excess chemical potential is outside the display grid")
    expected = round(-0.2 + 0.001 * index, 6)
    # Accept only binary floating-point representation noise, far below the 0.001 eV spacing.
    if abs(mu - expected) > 32 * math.ulp(1.0):
        raise AssertionError("surface-excess chemical potential is off the declared display grid")
    return expected

def validate_hull_vertices(vertices, coverages, stable_intervals):
    if not isinstance(vertices, list):
        raise AssertionError("analytic hull vertices must be an array")
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vertices):
        if vertices != coverages:
            raise AssertionError("incorrect analytic lower hull vertices")
        return
    # A coverage-versus-chemical-potential endpoint representation carries the same science.
    expected = list(dict.fromkeys((row["coverage"], bound)
                                 for row in stable_intervals for bound in row["mu_tilde_eV_interval"]))
    if len(vertices) != len(expected):
        raise AssertionError("analytic hull endpoint set is incomplete or duplicated")
    matched = set()
    for vertex in vertices:
        if not isinstance(vertex, dict) or not {"coverage", "mu_tilde_eV"}.issubset(vertex):
            raise AssertionError("invalid analytic hull vertex representation")
        coverage = vertex["coverage"]
        if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
            raise AssertionError("hull vertex coverage must be numeric")
        matches = [i for i, (c, bound) in enumerate(expected)
                   if coverage == c and interval_equal([vertex["mu_tilde_eV"]], [bound])]
        if len(matches) != 1 or matches[0] in matched:
            raise AssertionError("hull vertex does not match an independent analytic endpoint")
        matched.add(matches[0])

def validate_scientific_scope(scope):
    # These evidence limits are scientific assertions, not required prose wording.
    required = ("absolute_surface_energy_identified", "actual_reservoir_identified",
                "common_magnetic_parent_confirmed")
    if not isinstance(scope, dict) or any(scope.get(key) is not False for key in required):
        raise AssertionError("the supplied records do not identify absolute surface energy, an actual reservoir, or a common magnetic parent")

def check(app, tests, final):
    preflight(app,tests)
    check_calculation_evidence(final,app,"native_slab_slice.csv")
    refs=json.loads((tests/"refs.json").read_text())
    for rel,digest in refs["asset_hashes"].items():
        p=app/rel
        if not p.is_file() or "sha256:"+sha(p)!=digest: raise RuntimeError("public input invalid: "+rel)
    for rel,digest in refs["grader_reference_hashes"].items():
        p=tests/rel.removeprefix("tests/")
        if not p.is_file() or "sha256:"+sha(p)!=digest: raise RuntimeError("grader reference invalid: "+rel)
    native=rows(app/"assets/native_slab_slice.csv")
    if len(native)!=9: raise AssertionError("native slab slice must have nine records")
    by={}
    for r in native: by.setdefault(r["alloy"],[]).append(r)
    if len(by)!=3 or any(len(v)!=3 for v in by.values()): raise AssertionError("expected three coverage records per alloy")
    expected={"coverage_contrasts.csv":18,"surface_excess.csv":21654,"softening_thresholds.csv":72}
    for name,n in expected.items():
        p=final/name
        if not p.is_file() or len(rows(p))!=n: raise AssertionError(f"{name}: expected {n} data rows")
    contrasts=rows(final/"coverage_contrasts.csv"); surface=rows(final/"surface_excess.csv"); thresholds=rows(final/"softening_thresholds.csv")
    cidx={(r["alloy"],r["energy_convention"],r["surface_correction"]):r for r in contrasts}
    tidx={(r["alloy"],r["energy_convention"],r["surface_correction"],r["transition"]):r for r in thresholds}
    hull=json.loads((final/"coverage_hull.json").read_text())
    if not isinstance(hull, dict):
        raise AssertionError("coverage_hull.json must be a JSON object")
    hull_groups=normalize_hull_groups(hull.get("groups"))
    hidx={(r["alloy"],r["energy_convention"],r["surface_correction"]):r for r in hull_groups}
    expected_groups={(a,c,s) for a in by for c in CONVENTIONS for s in CORRECTIONS}
    if set(cidx)!=expected_groups or len(cidx)!=len(contrasts): raise AssertionError("contrast key domain has missing, extra, or duplicate groups")
    expected_thresholds={(a,c,s,t) for a in by for c in CONVENTIONS for s in CORRECTIONS for t in ("0_to_50_increment_decreases","50_to_100_increment_decreases","both_stepwise_increments_decrease","total_0_to_100_excess_decreases")}
    if set(tidx)!=expected_thresholds or len(tidx)!=len(thresholds): raise AssertionError("threshold key domain has missing, extra, or duplicate rows")
    surface_index={(x["alloy"],x["energy_convention"],x["surface_correction"],canonical_mu_grid_key(x["mu_tilde_eV"]),float(x["coverage_fraction"])):x for x in surface}
    mu_grid={round(-.2+.001*i,6) for i in range(401)}
    expected_surface={(a,c,s,mu,cov) for a,c,s in expected_groups for mu in mu_grid for cov in (0.,.5,1.)}
    if set(surface_index)!=expected_surface or len(surface_index)!=len(surface): raise AssertionError("surface-excess key grid has missing, extra, or duplicate rows")
    if set(hidx)!=expected_groups or len(hidx)!=len(hull_groups):raise AssertionError("hull key domain has missing, extra, or duplicate groups")
    ident=json.loads((final/"reference_identifiability.json").read_text())
    if not isinstance(ident,dict) or not isinstance(ident.get("affine_reference_invariance"),dict): raise AssertionError("reference_identifiability.json must contain affine_reference_invariance object")
    narrative=(final/"interpretation.md").read_text(encoding="utf8")
    if not narrative.strip():
        raise AssertionError("a scientific interpretation is required")
    validate_scientific_scope(ident.get("scientific_scope"))
    for alloy, records in by.items():
        records.sort(key=lambda r:float(r["coverage_fraction"]))
        if [int(r["H_count"]) for r in records] != [0,20,40] or any(int(r["metal_count"])!=180 for r in records): raise AssertionError(alloy+": invalid cohort")
        area=float(records[0]["one_face_area_A2"])
        if max(float(r["one_face_area_A2"]) for r in records)-area>1e-6: raise AssertionError(alloy+": inconsistent area")
        for conv,field in CONVENTIONS.items():
            e0,e50,e100=(float(r[field]) for r in records); d0=e100-2*e50+e0
            for corr,cj in CORRECTIONS.items():
                d=d0-2*(cj*(2*area)/EV_A2)
                key=(alloy,conv,corr); r=cidx.get(key); h=hidx.get(key)
                if not r or not h: raise AssertionError("missing group "+str(key))
                if not close(r["delta_E100_minus_2E50_plus_E0_eV"],d): raise AssertionError("curvature does not follow native energies")
                if not close(r["candidate_curvature_J_m2"],d/(2*area)*EV_A2): raise AssertionError("area conversion incorrect")
                if not close(r["E0_eV"],e0) or not close(r["E50_native_eV"],e50) or not close(r["E50_used_eV"],e50+cj*(2*area)/EV_A2) or not close(r["E100_eV"],e100): raise AssertionError("native/corrected energies do not match source rows")
                # Exact affine-envelope identities cover all real mu_tilde, not just plotting points.
                if not close(h["delta_eV"],d): raise AssertionError("hull curvature mismatch")
                mu_star=(e100-e0)/40
                if not close(h["mu_star_eV_per_H"],mu_star):raise AssertionError("mu_star not recomputed from native endpoints")
                want = [0.0,0.5,1.0] if d>1e-12 else ([0.0,1.0] if d < -1e-12 else [0.0,0.5,1.0])
                if abs(d)>1e-12:
                    lo,hi=(-d/40,d/40) if d>0 else (0.,0.)
                    wanted_intervals=[{"coverage":0.0,"mu_tilde_eV_interval":["-inf",lo]}]
                    if d>0:wanted_intervals += [{"coverage":.5,"mu_tilde_eV_interval":[lo,hi]}]
                    wanted_intervals += [{"coverage":1.0,"mu_tilde_eV_interval":[hi,"+inf"]}]
                    wanted_trans=[{"mu_tilde_eV":lo,"coexisting_coverages":[0.,.5]},{"mu_tilde_eV":hi,"coexisting_coverages":[.5,1.]}] if d>0 else [{"mu_tilde_eV":0.,"coexisting_coverages":[0.,1.]}]
                else:
                    wanted_intervals=[{"coverage":0.0,"mu_tilde_eV_interval":["-inf",0.]},{"coverage":.5,"mu_tilde_eV_interval":[0.,0.]},{"coverage":1.0,"mu_tilde_eV_interval":[0.,"+inf"]}]
                    wanted_trans=[{"mu_tilde_eV":0.,"coexisting_coverages":[0.,.5,1.]}]
                validate_hull_vertices(h["hull_vertices"], want, wanted_intervals)
                if len(h["stable_intervals"])!=len(wanted_intervals) or any(g["coverage"]!=w["coverage"] or not interval_equal(g["mu_tilde_eV_interval"],w["mu_tilde_eV_interval"]) for g,w in zip(h["stable_intervals"],wanted_intervals)):raise AssertionError("analytic stable intervals do not span the complete real domain")
                if len(h["transitions"])!=len(wanted_trans) or any(not close(g["mu_tilde_eV"],w["mu_tilde_eV"]) or g["coexisting_coverages"]!=w["coexisting_coverages"] for g,w in zip(h["transitions"],wanted_trans)):raise AssertionError("coexistence transition set mismatch")
                if not h["finite_interval_endpoints_inclusive"] or h["line_slopes_eV_per_H"]!={"0":0.0,"0.5":-20.0,"1":-40.0} or not close(h["line_intercepts_eV"]["0.5"],-d/2):raise AssertionError("affine energy lines or tie inclusion mismatch")
                expected_segments=[(a,b,x["mu_tilde_eV"]) for x in wanted_trans for a,b in zip(x["coexisting_coverages"],x["coexisting_coverages"][1:])]
                if len(h["lower_hull_segments"])!=len(expected_segments) or any(g["coverage_from"]!=a or g["coverage_to"]!=b or not close(g["mu_tilde_eV"],mu) or not g["coexistence_tie"] for g,(a,b,mu) in zip(h["lower_hull_segments"],expected_segments)):raise AssertionError("lower-hull segment set mismatch")
                if h["zero_curvature_midpoint_is_collinear_candidate"] != (abs(d)<=1e-12):raise AssertionError("zero-curvature tie declaration mismatch")
                formula={"0_to_50_increment_decreases":-d/40,"50_to_100_increment_decreases":d/40,"both_stepwise_increments_decrease":abs(d)/40,"total_0_to_100_excess_decreases":0.0}
                for label,x in formula.items():
                    tr=tidx.get((*key,label))
                    if not tr or not close(tr["threshold_mu_tilde_eV"],x): raise AssertionError("incorrect conditional threshold: "+label)
                    expected_conditions={"0_to_50_increment_decreases":"mu_tilde_eV > -delta_eV/40","50_to_100_increment_decreases":"mu_tilde_eV > delta_eV/40","both_stepwise_increments_decrease":"mu_tilde_eV > abs(delta_eV)/40","total_0_to_100_excess_decreases":"mu_tilde_eV > 0"}
                    if tr["strict_condition"]!=expected_conditions[label]:raise AssertionError("conditional threshold inequality/tie semantics mismatch")
                # Check every emitted surface row against its analytically defined state energy and minimizer.
                for mu in mu_grid:
                  for cov in (0.,.5,1.):
                    x=surface_index[(*key,canonical_mu_grid_key(mu),cov)]
                    mu=float(x["mu_tilde_eV"]); cov=float(x["coverage_fraction"])
                    omega={0.0:0.0,0.5:-d/2-20*mu,1.0:-40*mu}[cov]
                    minimizers=[c for c,v in {0.:0.,.5:-d/2-20*mu,1.:-40*mu}.items() if abs(v-min(0.,-d/2-20*mu,-40*mu))<=1e-12]
                    named=json.loads(x["minimizing_coverages"])
                    if not close(x["omega_excess_eV"],omega,1e-10) or not close(x["surface_excess_J_m2"],omega/(2*area)*EV_A2,1e-9): raise AssertionError("surface excess formula mismatch")
                    if x["on_lower_envelope"] != str(cov in minimizers).lower() or named!=minimizers or x["grid_role"]!="visualization only; analytical hull covers the full real domain":raise AssertionError("surface lower-envelope/minimizer classification mismatch")
    if ident.get("affine_reference_invariance",{}).get("test_a_eV")!=7.3 or ident.get("affine_reference_invariance",{}).get("test_b_eV_per_H")!=-0.123:raise AssertionError("affine shift test parameters changed")
    actual={"maximum_delta_residual_eV":0.,"mu_star_shift_residual_eV_per_H":0.,"mu_tilde_residual_eV":0.,"grand_potential_residual_eV":0.,"surface_excess_residual_J_m2":0.}
    for alloy,records in by.items():
      records.sort(key=lambda r:float(r['coverage_fraction']));area=float(records[0]['one_face_area_A2'])
      for field in CONVENTIONS.values():
       es=[float(r[field]) for r in records];shift=[es[i]+7.3+[0,-.123*20,-.123*40][i] for i in range(3)];d0=es[2]-2*es[1]+es[0];d1=shift[2]-2*shift[1]+shift[0];actual['maximum_delta_residual_eV']=max(actual['maximum_delta_residual_eV'],abs(d1-d0));m0=(es[2]-es[0])/40;m1=(shift[2]-shift[0])/40;actual['mu_star_shift_residual_eV_per_H']=max(actual['mu_star_shift_residual_eV_per_H'],abs(m1-m0+.123))
       for mu in (-.2,0.,.2):
        mt0=mu-m0;mt1=(mu-.123)-m1;actual['mu_tilde_residual_eV']=max(actual['mu_tilde_residual_eV'],abs(mt1-mt0))
        for c in (0.,.5,1.):
         o0={0.:0.,.5:-d0/2-20*mt0,1.:-40*mt0}[c];o1={0.:0.,.5:-d1/2-20*mt1,1.:-40*mt1}[c];actual['grand_potential_residual_eV']=max(actual['grand_potential_residual_eV'],abs(o1-o0));actual['surface_excess_residual_J_m2']=max(actual['surface_excess_residual_J_m2'],abs((o1-o0)/(2*area)*EV_A2))
    for k,v in actual.items():
      if not math.isfinite(float(ident['affine_reference_invariance'][k])) or abs(float(ident['affine_reference_invariance'][k])-v)>1e-12:raise AssertionError('affine reference residual was not recomputed: '+k)
    declared_groups = ident.get('groups')
    if isinstance(declared_groups, list):
        try:
            declared_keys = {(g['alloy'], g['energy_convention'], g['surface_correction']) for g in declared_groups}
        except (KeyError, TypeError) as exc:
            raise AssertionError('invalid identifiability group summaries') from exc
        if len(declared_groups) != 18 or declared_keys != expected_groups:
            raise AssertionError('identifiability summaries have missing, extra, or duplicate groups')
        for g in declared_groups:
            key = (g['alloy'], g['energy_convention'], g['surface_correction'])
            for field, reference_field in (('delta_eV', 'delta_E100_minus_2E50_plus_E0_eV'),
                                          ('candidate_curvature_J_m2', 'candidate_curvature_J_m2')):
                if field in g and not close(g[field], cidx[key][reference_field]):
                    raise AssertionError('identifiability summary disagrees with the native energy contrast')
        declared_group_count = len(declared_groups)
    else:
        declared_group_count = declared_groups
    if declared_group_count != 18 or ident.get('surface_excess_rows') != 21654 or ident.get('threshold_rows') != 72:
        raise AssertionError('identifiability count declaration mismatch')
    return {"status":"PASS","reward":1,"groups":18,"native_rows":9,"surface_rows":len(surface)}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--app-dir',type=Path,required=True); p.add_argument('--tests-dir',type=Path,required=True); p.add_argument('--final-dir',type=Path,required=True); p.add_argument('--report',type=Path,required=True); a=p.parse_args()
    try: result=check(a.app_dir,a.tests_dir,a.final_dir); rc=0
    except RuntimeError as e: result={"status":"ENV_INVALID","reward":None,"reason":str(e)}; rc=2
    except (AssertionError,KeyError,ValueError,TypeError,OSError,json.JSONDecodeError) as e: result={"status":"FAIL","reward":0,"reason":f"{type(e).__name__}: {e}"}; rc=1
    a.report.parent.mkdir(parents=True,exist_ok=True); a.report.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,indent=2)); raise SystemExit(rc)
if __name__=='__main__': main()
